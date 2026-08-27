"""CHANGELOG 運用の GitHub 契約を静的に検証する。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.changelog_fragments import SECTION_ORDER

_REPO_ROOT = REPO_ROOT
_CLAUDE_PATH = _REPO_ROOT / "CLAUDE.md"
_PR_TEMPLATE_PATH = _REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
_CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_DEVELOPMENT_DOC_PATH = _REPO_ROOT / "docs" / "development.md"
_FRAGMENTS_DIR = _REPO_ROOT / "changelog.d"
_FRAGMENTS_README_PATH = _FRAGMENTS_DIR / "README.md"
_FRAGMENT_VALIDATOR_PATH = _REPO_ROOT / ".github" / "scripts" / "validate-changelog-fragments.py"
_FRAGMENT_VALIDATOR_RELATIVE = ".github/scripts/validate-changelog-fragments.py"
_FRAGMENT_VALIDATOR_STEP_NAME = "Validate changelog fragments"
_FRAGMENT_VALIDATOR_COMMAND = f"python {_FRAGMENT_VALIDATOR_RELATIVE}"
_CHANGELOG_UPDATE_STEP_NAME = "Check CHANGELOG update"
_FRAGMENT_RULES_MODULE = "youtube_automation.commands.system.changelog_fragments"

_CHANGELOG_LABEL = "skip-changelog"

# 書式の正本（README）に置く実行可能な記述例の在り処。節を限定するのは、
# 「間違えやすい形」の反例を記述例として拾わないため。
_README_EXAMPLE_HEADING = "## 記述例"
_README_EXAMPLE_FENCE = "```markdown"
# CLAUDE.md が書く type 一覧は SECTION_ORDER から組み立てて完全一致で照合する。
# 各要素の包含だけを見ると、実装から type を削っても文書に残った古い一覧を検出できない。
_DOCUMENTED_TYPE_LIST = " / ".join(SECTION_ORDER)
_DOCUMENTED_BULLET_RULE = "全非空行を `- ` 始まりの bullet にする"
# 規則の到達性を担保する文書。いずれも takt の自作 workflow 資産と独立に残る（#4666）。
_FRAGMENT_RULE_DOCS = (_FRAGMENTS_README_PATH, _DEVELOPMENT_DOC_PATH, _CLAUDE_PATH)

# CHANGELOG ゲート対象パスの単一ソース。CI workflow の path filter regex を
# この定数と照合する。
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
_PUSH_TRIGGER_BRANCHES = ["main"]
_CHANGELOG_FRAGMENT_PATTERN = "^changelog\\.d/.+\\.md$"
_LABELS_JOIN_EXPRESSION = "${{ join(github.event.pull_request.labels.*.name, ',') }}"
_HEAD_REF_EXPRESSION = "${{ github.head_ref }}"
_PR_EVENT_GUARD = "github.event_name == 'pull_request'"
_PR_TEMPLATE_TEXT = """## 概要

<!-- 何を、なぜ変更したか。issue があれば `Closes #N` -->

## 変更内容

<!-- 主要な変更点を箇条書きで -->

## チェックリスト

- [ ] `changelog.d/` に fragment を追加した（書き方: [`changelog.d/README.md`](../changelog.d/README.md)。\
通常 PR では `CHANGELOG.md` を直接編集しない）
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
    'if [[ "$HEAD_REF" == release/* ]]; then',
    "if echo \"$changed\" | grep -q '^CHANGELOG\\.md$'; then",
    f"if ! echo \"$changed\" | grep -qE '{_PATH_FILTER_PATTERN}'; then",
    f"if ! echo \"$changed\" | grep -qE '{_CHANGELOG_FRAGMENT_PATTERN}'; then",
    'echo "Changelog fragment found"',
]


def _read_text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"必須ファイルが存在しない: {path.relative_to(_REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _load_ci_workflow() -> dict[str, object]:
    return yaml.safe_load(_read_text(_CI_WORKFLOW_PATH))


def _run_changelog_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    changed_files: tuple[str, ...],
    head_ref: str,
) -> subprocess.CompletedProcess[str]:
    """CI の shell script を fake git diff に対して実行する。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text('#!/bin/sh\nprintf "%s\\n" "$CHANGED_FILES"\n', encoding="utf-8")
    fake_git.chmod(0o755)

    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("CHANGED_FILES", "\n".join(changed_files))
    monkeypatch.setenv("PR_LABELS", "")
    # fake git は値を解釈しないが、実際の git diff と同じ非空引数を渡す。
    monkeypatch.setenv("BASE_SHA", "base")
    monkeypatch.setenv("HEAD_SHA", "head")
    monkeypatch.setenv("HEAD_REF", head_ref)

    run_script = _load_ci_workflow()["jobs"]["changelog"]["steps"][1]["run"]
    return subprocess.run(
        ["bash", "-c", run_script],
        check=False,
        capture_output=True,
        text=True,
    )


def _run_fragment_validator(fragments_dir: Path) -> subprocess.CompletedProcess[str]:
    """CI が呼ぶ fragment 検証スクリプトを、指定した fragment 集合に対して実行する。"""
    return subprocess.run(
        [sys.executable, str(_FRAGMENT_VALIDATOR_PATH), "--fragments-dir", str(fragments_dir)],
        check=False,
        capture_output=True,
        text=True,
    )


def _readme_example() -> tuple[str, str]:
    """README の「記述例」節から fragment のファイル名と本文を取り出す。

    節を跨がないのは、後続の「間違えやすい形」に載る反例を記述例と取り違えないため。
    """
    readme = _read_text(_FRAGMENTS_README_PATH)
    heading_index = readme.find(_README_EXAMPLE_HEADING)
    assert heading_index != -1, f"{_README_EXAMPLE_HEADING} の節が無い"

    section_end = readme.find("\n## ", heading_index + len(_README_EXAMPLE_HEADING))
    section = readme[heading_index:] if section_end == -1 else readme[heading_index:section_end]

    name_match = re.search(r"`changelog\.d/([^`/]+\.md)`", section)
    assert name_match is not None, "記述例の節に fragment のファイル名が無い"

    body_match = re.search(rf"{re.escape(_README_EXAMPLE_FENCE)}\n(.*?)```", section, re.DOTALL)
    assert body_match is not None, f"記述例の節に {_README_EXAMPLE_FENCE} の本文が無い"

    return name_match.group(1), body_match.group(1)


def _write_fragment_fixture(tmp_path: Path, name: str, body: str) -> Path:
    fragments_dir = tmp_path / "changelog.d"
    fragments_dir.mkdir()
    (fragments_dir / name).write_text(body, encoding="utf-8")
    return fragments_dir


def test_pull_request_template_matches_issue_485_contract() -> None:
    """PR template が issue #485 仕様の本文と一致することを保証する。"""
    assert _read_text(_PR_TEMPLATE_PATH) == _PR_TEMPLATE_TEXT


def test_claude_requires_fragments_and_forbids_direct_changelog_edits() -> None:
    """Codex Cloud 向けの通常 PR の変更履歴契約を固定する。"""
    claude = _read_text(_CLAUDE_PATH)

    assert "通常 PR の変更履歴は `changelog.d/<issue>-<slug>.<type>.md` に追加" in claude
    assert "`CHANGELOG.md` を直接編集しない" in claude
    assert "`release/*` の release prepare だけが例外" in claude


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
        "HEAD_REF": _HEAD_REF_EXPRESSION,
    }


def test_ci_workflow_changelog_job_checks_expected_paths_and_messages() -> None:
    """要 CHANGELOG path, exempt label, error 文言の契約を固定する。"""
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["changelog"]["steps"]

    checkout_step = steps[0]
    assert checkout_step == {
        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "with": {"fetch-depth": 0},
    }

    changelog_step = steps[1]
    assert changelog_step.get("name") == "Check CHANGELOG update"

    run_script = changelog_step.get("run")
    assert isinstance(run_script, str), "run スクリプトが存在しない"
    for expected_line in _EXPECTED_RUN_LINES:
        assert expected_line in run_script

    assert _CHANGELOG_LABEL in run_script
    assert _CHANGELOG_FRAGMENT_PATTERN in run_script
    assert "::error::Normal PRs must not edit CHANGELOG.md directly; add a fragment under changelog.d/." in run_script
    assert "::error::Release PRs must update CHANGELOG.md." in run_script
    assert "::error::Add a changelog fragment under changelog.d/, or apply 'skip-changelog' label." in run_script


@pytest.mark.parametrize(
    ("changed_files", "head_ref", "expected_returncode", "expected_message"),
    [
        (
            ("src/youtube_automation/example.py",),
            "feature/example",
            1,
            "Add a changelog fragment under changelog.d/",
        ),
        (
            ("CHANGELOG.md",),
            "feature/example",
            1,
            "Normal PRs must not edit CHANGELOG.md directly",
        ),
        (
            ("CHANGELOG.md",),
            "release/1.2.3",
            0,
            "Release CHANGELOG update found",
        ),
    ],
)
def test_ci_changelog_gate_enforces_normal_and_release_pr_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_files: tuple[str, ...],
    head_ref: str,
    expected_returncode: int,
    expected_message: str,
) -> None:
    """通常 PR の fragment 必須化と release branch 例外を実行結果で固定する。"""
    result = _run_changelog_gate(
        tmp_path,
        monkeypatch,
        changed_files=changed_files,
        head_ref=head_ref,
    )

    assert result.returncode == expected_returncode, f"CHANGELOG ゲートの終了コードが想定外: stderr={result.stderr!r}"
    assert expected_message in result.stdout, (
        f"CHANGELOG ゲートの出力に期待するメッセージがない: stdout={result.stdout!r}"
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


def test_changelog_gate_paths_match_single_source_in_ci() -> None:
    """CI の changelog ゲート対象パスを _CHANGELOG_GATED_PATHS と正方向に照合する。

    パスが落ちても（あるいは想定外のパスが増えても）fail する。
    """
    # path filter の grep -E パターンを抽出し、定数から組み立てた regex と完全一致させる。
    run_script = _load_ci_workflow()["jobs"]["changelog"]["steps"][1]["run"]
    ci_pattern_match = re.search(r"grep -qE '([^']+)'", run_script)
    assert ci_pattern_match is not None, "CI run スクリプトに path filter の grep -qE が無い"
    assert ci_pattern_match.group(1) == _PATH_FILTER_PATTERN, (
        "CI workflow の path filter regex が _CHANGELOG_GATED_PATHS と一致しない"
    )


def test_ci_workflow_changelog_job_validates_fragment_format() -> None:
    """fragment の存在確認だけでなく、type / bullet 体裁の検証 step も持つことを固定する。"""
    steps = _load_ci_workflow()["jobs"]["changelog"]["steps"]
    names = [step.get("name") for step in steps]

    assert _FRAGMENT_VALIDATOR_STEP_NAME in names, "fragment 体裁を検証する step が存在しない"
    assert names.index(_FRAGMENT_VALIDATOR_STEP_NAME) > names.index(_CHANGELOG_UPDATE_STEP_NAME), (
        "体裁検証は fragment 存在チェックの後に置く"
    )

    validator_step = steps[names.index(_FRAGMENT_VALIDATOR_STEP_NAME)]
    assert validator_step.get("run", "").strip() == _FRAGMENT_VALIDATOR_COMMAND
    # skip-changelog ラベルや path filter で握り潰さず、常に changelog.d/ 全件を検証する。
    assert "if" not in validator_step
    assert _FRAGMENT_VALIDATOR_PATH.is_file(), f"{_FRAGMENT_VALIDATOR_RELATIVE} が存在しない"


def test_fragment_rules_module_imports_without_third_party_dependencies() -> None:
    """changelog ゲートは nix / uv 無しで走るため、規則 module に third-party 依存を持たせない。"""
    code = (
        f"import sys; sys.path.insert(0, {str(_REPO_ROOT / 'src')!r}); "
        # 空振りしない保証: site-packages が本当に外れていることを import 前に確かめる。
        "assert not any('site-packages' in entry for entry in sys.path), sys.path; "
        f"import {_FRAGMENT_RULES_MODULE}"
    )

    # -S で site を無効化し、-E で devShell の PYTHONPATH も無視する。依存が増えれば ImportError で落ちる。
    result = subprocess.run([sys.executable, "-E", "-S", "-c", code], check=False, capture_output=True, text=True)

    assert result.returncode == 0, f"素の python で {_FRAGMENT_RULES_MODULE} を import できない: {result.stderr}"


def test_compile_and_ci_share_the_same_fragment_rules() -> None:
    """release prepare 側が規則を再実装せず、CI と同じ module を使うことを固定する。"""
    compile_source = _read_text(_REPO_ROOT / "src/youtube_automation/commands/system/changelog_compile.py")
    validator_source = _read_text(_FRAGMENT_VALIDATOR_PATH)

    assert f"from {_FRAGMENT_RULES_MODULE} import" in compile_source
    assert f"from {_FRAGMENT_RULES_MODULE} import" in validator_source


def test_changelog_fragment_validator_accepts_repository_fragments() -> None:
    """リポジトリの changelog.d/ 全件が release prepare と同じ規則を満たす（#4649 の回帰防止）。"""
    result = _run_fragment_validator(_FRAGMENTS_DIR)

    assert result.returncode == 0, f"changelog.d/ に体裁違反がある: {result.stdout}{result.stderr}"
    assert "changelog fragments are valid" in result.stdout


@pytest.mark.parametrize(
    ("fragment_name", "fragment_body", "expected_message"),
    [
        ("9-plain.fixed.md", "bullet ではない平文\n", "'- ' で始まる bullet で記述してください"),
        ("9-continuation.fixed.md", "- 先頭行\n継続行\n", "'- ' で始まる bullet で記述してください"),
        ("9-empty.fixed.md", "\n", "'- ' で始まる bullet で記述してください"),
        ("9-unknown.improved.md", "- 本文\n", "不正な changelog fragment ファイル名です"),
    ],
)
def test_changelog_fragment_validator_rejects_invalid_fragments(
    tmp_path: Path,
    fragment_name: str,
    fragment_body: str,
    expected_message: str,
) -> None:
    """type 文字列と bullet 体裁の違反を、いずれも PR 時点で fail させる。"""
    fragments_dir = _write_fragment_fixture(tmp_path, fragment_name, fragment_body)

    result = _run_fragment_validator(fragments_dir)

    assert result.returncode == 1, f"体裁違反が検出されなかった: stdout={result.stdout!r}"
    assert "::error::" in result.stdout, "GitHub Actions の error annotation で出力する"
    assert expected_message in result.stdout
    assert fragment_name in result.stdout, "違反ファイル名を出力に含める"


def test_changelog_fragment_validator_does_not_consume_fragments(tmp_path: Path) -> None:
    """検証は読み取りのみで、release prepare のように fragment を集約・削除しない。"""
    fragments_dir = _write_fragment_fixture(tmp_path, "9-valid.fixed.md", "- 正しい bullet\n")

    result = _run_fragment_validator(fragments_dir)

    assert result.returncode == 0, f"正しい fragment が拒否された: {result.stdout}{result.stderr}"
    assert (fragments_dir / "9-valid.fixed.md").read_text(encoding="utf-8") == "- 正しい bullet\n"


def test_changelog_fragments_readme_documents_ci_validation() -> None:
    """fragment の書き方の正本に、PR 時点で検証される旨を記載しておく。"""
    readme = _read_text(_FRAGMENTS_README_PATH)

    assert _FRAGMENT_VALIDATOR_RELATIVE in readme


def test_readme_example_passes_the_fragment_validator(tmp_path: Path) -> None:
    """README の記述例がそのまま validator を通る（#4668）。

    書式の正本に実例を置いても、それ自体が規則違反なら誤りを増やすだけになる。
    文字列一致ではなく実際に validator へ掛けることで、例が腐った時点で fail させる。
    """
    name, body = _readme_example()
    fragments_dir = _write_fragment_fixture(tmp_path, name, body)

    result = _run_fragment_validator(fragments_dir)

    assert result.returncode == 0, f"README の記述例が validator を通らない: {result.stdout}{result.stderr}"


def test_local_fragment_validation_command_is_documented() -> None:
    """CI と同一のコマンドで手元検証できる経路を、規則の到達点すべてに書いておく（#4668）。"""
    for path in _FRAGMENT_RULE_DOCS:
        assert _FRAGMENT_VALIDATOR_COMMAND in _read_text(path), (
            f"{path.relative_to(_REPO_ROOT)} にローカル検証コマンドの記載が無い"
        )


def test_claude_md_states_fragment_type_set_and_bullet_rule() -> None:
    """常時読み込まれる CLAUDE.md が、type 集合と bullet 体裁を実装と揃えて明示する（#4668）。"""
    claude = _read_text(_CLAUDE_PATH)

    assert _DOCUMENTED_TYPE_LIST in claude, (
        f"CLAUDE.md の type 一覧が SECTION_ORDER と一致しない: {_DOCUMENTED_TYPE_LIST}"
    )
    assert _DOCUMENTED_BULLET_RULE in claude, "CLAUDE.md に bullet 体裁の記載が無い"


def test_readme_lists_every_fragment_type() -> None:
    """書式の正本が、実装が受け付ける type を漏れなく列挙する（#4668）。"""
    readme = _read_text(_FRAGMENTS_README_PATH)

    for section in SECTION_ORDER:
        assert f"`{section}`" in readme, f"changelog.d/README.md に type `{section}` の記載が無い"
