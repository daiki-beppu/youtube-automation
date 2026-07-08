"""CHANGELOG 運用の GitHub 契約を静的に検証する。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PR_TEMPLATE_PATH = _REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
_CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_CHANGELOG_GATE_PATH = _REPO_ROOT / ".lefthook" / "pre-push" / "changelog-gate.sh"
_LEFTHOOK_CONFIG_PATH = _REPO_ROOT / "lefthook.yml"

_CHANGELOG_LABEL = "skip-changelog"

# CHANGELOG ゲート対象パスの単一ソース。CI workflow の path filter regex と
# changelog-gate.sh の GATED_PATHS の双方をこの定数と照合する。
# 末尾 `/` はディレクトリ prefix、それ以外はファイル完全一致。
_CHANGELOG_GATED_PATHS = (
    "src/youtube_automation/",
    ".claude/skills/",
    ".claude/CLAUDE.template.md",
    "pyproject.toml",
)


def _build_ci_path_filter_pattern(gated_paths: tuple[str, ...]) -> str:
    """ゲート対象パス集合から CI workflow の grep -E パターンを組み立てる。"""
    alternatives = []
    for path in gated_paths:
        escaped = re.escape(path)
        if not path.endswith("/"):
            escaped += "$"
        alternatives.append(escaped)
    return "^(" + "|".join(alternatives) + ")"


_PATH_FILTER_PATTERN = _build_ci_path_filter_pattern(_CHANGELOG_GATED_PATHS)
# push で CI を回す対象 branch。PR は stacked PR base でも発火するよう branch 制限しない。
_PUSH_TRIGGER_BRANCHES = ["main", "feat/1143-suno-bulk-download"]
_CHANGELOG_FILE_PATTERN = "^CHANGELOG\\.md$"
_LABELS_JOIN_EXPRESSION = "${{ join(github.event.pull_request.labels.*.name, ',') }}"
_PR_EVENT_GUARD = "github.event_name == 'pull_request'"
_PR_TEMPLATE_TEXT = """## 概要

<!-- 何を、なぜ変更したか。issue があれば `Closes #N` -->

## 変更内容

<!-- 主要な変更点を箇条書きで -->

## チェックリスト

- [ ] `CHANGELOG.md::[Unreleased]` にエントリを追加した
  - 免除する場合は `skip-changelog` ラベルを付与（tests / docs / 内部リファクタのみ）
- [ ] 下流チャンネルに影響する変更なら `### Migration` セクションも更新した
  - フォーマット: [docs/changelog-contract.md](../docs/changelog-contract.md)
- [ ] 必要なテストを追加・更新した

## 関連

<!-- 関連 issue / PR / 参照ドキュメント -->
"""
_EXPECTED_RUN_LINES = [
    "set -eu",
    'if [[ ",${PR_LABELS}," == *",skip-changelog,"* ]]; then',
    'changed=$(git diff --name-only "$BASE_SHA" "$HEAD_SHA")',
    f"if ! echo \"$changed\" | grep -qE '{_PATH_FILTER_PATTERN}'; then",
    f"if ! echo \"$changed\" | grep -q '{_CHANGELOG_FILE_PATTERN}'; then",
    'echo "CHANGELOG.md updated"',
]


def _read_text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"必須ファイルが存在しない: {path.relative_to(_REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _load_ci_workflow() -> dict[str, object]:
    return yaml.safe_load(_read_text(_CI_WORKFLOW_PATH))


def test_pull_request_template_matches_issue_485_contract() -> None:
    """PR template が issue #485 仕様の本文と一致することを保証する。"""
    assert _read_text(_PR_TEMPLATE_PATH) == _PR_TEMPLATE_TEXT


def test_ci_workflow_declares_changelog_job_for_pull_requests_only() -> None:
    """changelog job は pull_request のみで動く独立 job である必要がある。"""
    workflow = _load_ci_workflow()
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "jobs セクションが存在しない"

    changelog_job = jobs.get("changelog")
    assert isinstance(changelog_job, dict), "changelog job が存在しない"
    assert changelog_job.get("runs-on") == "ubuntu-latest"
    assert changelog_job.get("if") == _PR_EVENT_GUARD


def test_ci_workflow_changelog_job_uses_expected_environment_contract() -> None:
    """ラベル判定と base..head diff の入力は spec の GitHub context に固定する。"""
    workflow = _load_ci_workflow()
    changelog_step = workflow["jobs"]["changelog"]["steps"][1]

    env = changelog_step.get("env")
    assert env == {
        "PR_LABELS": _LABELS_JOIN_EXPRESSION,
        "BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
    }


def test_ci_workflow_changelog_job_checks_expected_paths_and_messages() -> None:
    """要 CHANGELOG path, exempt label, error 文言の契約を固定する。"""
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["changelog"]["steps"]

    checkout_step = steps[0]
    assert checkout_step == {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}}

    changelog_step = steps[1]
    assert changelog_step.get("name") == "Check CHANGELOG update"

    run_script = changelog_step.get("run")
    assert isinstance(run_script, str), "run スクリプトが存在しない"
    for expected_line in _EXPECTED_RUN_LINES:
        assert expected_line in run_script

    assert _CHANGELOG_LABEL in run_script
    assert _CHANGELOG_FILE_PATTERN in run_script
    assert (
        "::error::CHANGELOG.md must be updated under [Unreleased]. Add an entry or apply 'skip-changelog' label."
        in run_script
    )


def test_ci_workflow_keeps_push_branch_allowlist() -> None:
    """push トリガーの branch allowlist を固定する（ADR-0021 で feat/ts-rewrite は除外済み）。"""
    workflow = _load_ci_workflow()
    # PyYAML は YAML 1.1 で bare な `on` を真偽値 True にパースするため両キーを許容する。
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "on トリガーが存在しない"

    push = triggers.get("push")
    assert isinstance(push, dict), "push トリガーが存在しない"
    assert push.get("branches") == _PUSH_TRIGGER_BRANCHES


def test_ci_workflow_pull_requests_allow_stacked_pr_base_branches() -> None:
    """stacked PR の base branch を allowlist で遮断しない。"""
    workflow = _load_ci_workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "on トリガーが存在しない"

    pull_request = triggers.get("pull_request")
    assert isinstance(pull_request, dict), "pull_request トリガーが存在しない"
    assert "branches" not in pull_request


def test_changelog_gate_paths_match_single_source_in_ci_and_lefthook() -> None:
    """CI と lefthook の changelog ゲート対象パスを _CHANGELOG_GATED_PATHS と正方向に照合する。

    どちらか一方からパスが落ちても（あるいは想定外のパスが増えても）fail する。
    """
    # CI 側: path filter の grep -E パターンを抽出し、定数から組み立てた regex と完全一致させる。
    run_script = _load_ci_workflow()["jobs"]["changelog"]["steps"][1]["run"]
    ci_pattern_match = re.search(r"grep -qE '([^']+)'", run_script)
    assert ci_pattern_match is not None, "CI run スクリプトに path filter の grep -qE が無い"
    assert ci_pattern_match.group(1) == _PATH_FILTER_PATTERN, (
        "CI workflow の path filter regex が _CHANGELOG_GATED_PATHS と一致しない"
    )

    # lefthook 側: changelog-gate.sh の GATED_PATHS 配列を抽出し、定数と順序込みで完全一致させる。
    gate_script = _read_text(_CHANGELOG_GATE_PATH)
    gated_paths_match = re.search(r"GATED_PATHS=\((.*?)\)", gate_script, re.DOTALL)
    assert gated_paths_match is not None, "changelog-gate.sh に GATED_PATHS 配列が無い"
    gate_paths = tuple(re.findall(r'"([^"]+)"', gated_paths_match.group(1)))
    assert gate_paths == _CHANGELOG_GATED_PATHS, (
        "changelog-gate.sh の GATED_PATHS が _CHANGELOG_GATED_PATHS と一致しない"
    )


def test_lefthook_changelog_gate_skips_branch_deletion_push() -> None:
    """#1420: ブランチ削除 push（local sha 全ゼロ）は changelog ゲート対象外。

    削除 push スキップは 2 ファイルで 1 つの不変条件:
    changelog-gate.sh の stdin 判定と lefthook.yml の use_stdin: true。
    use_stdin が落ちるとスクリプトの空 stdin フォールバックが回帰を隠して
    削除 push が再びブロックされるため、両側をここで固定する。
    """
    gate_script = _read_text(_CHANGELOG_GATE_PATH)
    for token in (
        'ZERO_SHA="0000000000000000000000000000000000000000"',
        "ブランチ削除 push のためスキップします",
    ):
        assert token in gate_script, f"changelog-gate.sh に {token} が無い"

    lefthook_config = yaml.safe_load(_read_text(_LEFTHOOK_CONFIG_PATH))
    gate_command = lefthook_config["pre-push"]["commands"]["changelog-gate"]
    assert gate_command.get("use_stdin") is True, (
        "lefthook.yml の changelog-gate に use_stdin: true が無いと削除 push スキップが黙って無効化される"
    )
