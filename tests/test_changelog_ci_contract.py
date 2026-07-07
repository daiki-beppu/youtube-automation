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
_OXFMT_CONFIG_PATH = _REPO_ROOT / "oxfmt.config.ts"

_CHANGELOG_LABEL = "skip-changelog"
_PATH_FILTER_PATTERN = (
    "^(src/youtube_automation/|\\.claude/skills/|\\.claude/CLAUDE\\.template\\.md$"
    "|pyproject\\.toml$|packages/|package\\.json$)"
)
# push で CI を回す対象 branch。PR は stacked PR base でも発火するよう branch 制限しない。
_PUSH_TRIGGER_BRANCHES = ["main", "feat/ts-rewrite", "feat/1143-suno-bulk-download"]
_CHANGELOG_FILE_PATTERN = "^CHANGELOG\\.md$"
_LABELS_JOIN_EXPRESSION = "${{ join(github.event.pull_request.labels.*.name, ',') }}"
_PR_EVENT_GUARD = "github.event_name == 'pull_request'"
_OXFMT_STAGED_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".jsonc"}
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


def _oxfmt_ignore_patterns() -> set[str]:
    text = _read_text(_OXFMT_CONFIG_PATH)
    match = re.search(r"ignorePatterns:\s*\[(?P<body>.*?)\],", text, flags=re.DOTALL)
    assert match is not None, "oxfmt.config.ts の ignorePatterns が見つからない"
    return set(re.findall(r'"([^"]+)"', match.group("body")))


def _ignore_pattern_has_oxfmt_staged_files(pattern: str) -> bool:
    if not pattern.endswith("/**"):
        return False
    root = _REPO_ROOT / pattern.removesuffix("/**")
    if not root.exists() or not root.is_dir():
        return False
    return any(path.is_file() and path.suffix in _OXFMT_STAGED_SUFFIXES for path in root.rglob("*"))


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
    """#964: feat/ts-rewrite branch への push でも CI が走る必要がある。

    #790 cutover で feat/ts-rewrite を branches から外したら本テストも更新する。
    """
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


def test_ci_changelog_gate_covers_ts_packages() -> None:
    """#964: CI と lefthook の changelog ゲートが packages/ と package.json を対象にする。"""
    run_script = _load_ci_workflow()["jobs"]["changelog"]["steps"][1]["run"]
    gate_script = _read_text(_CHANGELOG_GATE_PATH)

    assert _PATH_FILTER_PATTERN in run_script
    for token in ("packages/", "package\\.json$"):
        assert token in run_script, f"CI path filter に {token} が無い"

    # lefthook 側 GATED_PATHS は CI と同じ範囲を担保する。
    for token in ('"packages/"', '"package.json"'):
        assert token in gate_script, f"changelog-gate.sh に {token} が無い"


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


def test_lefthook_oxfmt_exclude_matches_formatter_ignore_contract() -> None:
    """#1428 同型: oxfmt ignore 対象だけの staged commit で hook が失敗しない契約を固定する。"""
    lefthook_config = yaml.safe_load(_read_text(_LEFTHOOK_CONFIG_PATH))
    oxfmt_command = lefthook_config["pre-commit"]["commands"]["oxfmt"]
    lefthook_excludes = set(oxfmt_command.get("exclude", []))
    ignore_patterns = _oxfmt_ignore_patterns()
    required_excludes = {pattern for pattern in ignore_patterns if _ignore_pattern_has_oxfmt_staged_files(pattern)}

    assert required_excludes <= lefthook_excludes, (
        "lefthook.yml の pre-commit.commands.oxfmt.exclude は、oxfmt.config.ts の ignorePatterns のうち "
        f"対象拡張子の実ファイルがある path を含めること: {sorted(required_excludes - lefthook_excludes)}"
    )
    assert lefthook_excludes <= ignore_patterns, (
        "lefthook.yml の oxfmt.exclude は oxfmt.config.ts の ignorePatterns と同期してください: "
        f"{sorted(lefthook_excludes - ignore_patterns)}"
    )
