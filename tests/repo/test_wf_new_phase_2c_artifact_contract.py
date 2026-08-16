"""`/wf-new` Phase 2c の branch 単位成果物・再開契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "wf-new"
SKILL_MD = SKILL_DIR / "SKILL.md"
PHASE2_MD = SKILL_DIR / "references" / "phase2.md"
CONTRACT_MD = SKILL_DIR / "references" / "phase-2c-artifact-contract.md"
WORKFLOW_CHEATSHEET = REPO_ROOT / "docs" / "workflow-cheatsheet.md"


def _section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^##\s|\Z)",
        markdown,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def test_skill_dispatches_phase_2c_artifact_contract_before_result_handling() -> None:
    skill = "\n".join(path.read_text(encoding="utf-8") for path in (SKILL_MD, PHASE2_MD))
    relative_reference = CONTRACT_MD.relative_to(PHASE2_MD.parent).as_posix()

    phase_2c = skill.index("#### 2c. サムネイル確定 + 音楽素材生成")
    dispatch = skill.index(f"]({relative_reference})", phase_2c)
    thumbnail_step = skill.index("##### 2c-1.", dispatch)

    assert CONTRACT_MD.is_file()
    assert phase_2c < dispatch < thumbnail_step


def test_contract_requires_independent_real_artifact_validation() -> None:
    contract = CONTRACT_MD.read_text(encoding="utf-8")
    validation = _section(contract, "## Branch 検証")

    for thumbnail_evidence in (
        "`10-assets/thumbnail.jpg`",
        "`10-assets/main.png` または `10-assets/main.jpg`",
        "`/thumbnail --compare`",
    ):
        assert thumbnail_evidence in validation
    for suno_evidence in (
        "`20-documentation/suno-patterns.yaml`",
        "`20-documentation/suno-prompts.json`",
        "`uv run yt-suno-verify <collection-path>`",
        "semantic review",
    ):
        assert suno_evidence in validation
    assert "`20-documentation/lyria-prompt.json` / `.html` pair" in validation
    assert "subagent の完了報告" in validation
    assert "成功根拠にしない" in validation


def test_contract_commits_only_successful_branches_and_preserves_failures() -> None:
    contract = CONTRACT_MD.read_text(encoding="utf-8")
    result_application = _section(contract, "## State 適用")

    expected_rows = (
        "| 成功 | 成功 | `assets.thumbnail = true` と `assets.music_prompts = true` |",
        "| 失敗 | 成功 | `assets.music_prompts = true` だけ |",
        "| 成功 | 失敗 | `assets.thumbnail = true` だけ |",
        "| 失敗 | 失敗 | 変更しない |",
    )
    for row in expected_rows:
        assert row in result_application
    assert "メインエージェントだけ" in result_application
    assert "branch ごとに直列" in result_application
    assert "成功済み flag を `false` に戻さない" in result_application
    assert "失敗 branch の flag を `true` にしない" in result_application


def test_contract_fails_closed_on_state_artifact_mismatch() -> None:
    contract = CONTRACT_MD.read_text(encoding="utf-8")
    resume = _section(contract, "## 再開判定")

    assert "flag と実成果物を再検証" in resume
    assert "flag が `true`" in resume
    assert "欠落・破損" in resume
    assert "不整合" in resume
    assert "fail-closed" in resume
    assert "正常な別 branch の state と成果物は変更しない" in resume


def test_contract_resumes_only_the_failed_branch() -> None:
    contract = CONTRACT_MD.read_text(encoding="utf-8")
    resume = _section(contract, "## 再開判定")

    assert "検証成功済み branch は再生成・再承認しない" in resume
    assert "thumbnail branch だけ" in resume
    assert "`/music --prompt <theme>`" in resume
    assert "`/music --generate <theme>`" in resume
    assert "同じ collection" in resume
    assert "失敗理由" in resume


def test_workflow_docs_distinguish_phase_2c_partial_commit_from_other_failures() -> None:
    docs = WORKFLOW_CHEATSHEET.read_text(encoding="utf-8")

    assert "Phase 2c" in docs
    assert "成功した branch の `assets` flag だけ" in docs
    assert "失敗した branch だけ" in docs
    assert "Phase 2c 以外" in docs
    assert "state を更新しない" in docs
