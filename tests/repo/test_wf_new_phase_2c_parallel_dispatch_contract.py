"""`/wf-new` Phase 2c の exactly-two 同時 dispatch 契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_MD = REPO_ROOT / ".claude" / "skills" / "wf-new" / "SKILL.md"
PHASE2_MD = REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "phase2.md"
WORKFLOW_CHEATSHEET = REPO_ROOT / "docs" / "workflow-cheatsheet.md"


def _skill_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in (SKILL_MD, PHASE2_MD))


def _between(markdown: str, start: str, end: str) -> str:
    try:
        return markdown.split(start, 1)[1].split(end, 1)[0]
    except IndexError as error:
        raise AssertionError(f"section boundary missing: {start!r} -> {end!r}") from error


def test_phase_2c_is_the_only_parallel_subagent_exception() -> None:
    skill = _skill_text()
    hard_gates = _between(skill, "## Hard Gates", "### Preselected batch plan entry")
    call_rules = _between(skill, "### 呼び出しルール", "### 実行シーケンス")

    for section in (hard_gates, call_rules):
        assert "Phase 2c" in section
        assert "thumbnail" in section
        assert "music" in section
        assert "同時" in section
        assert "それ以外" in section
        assert "一作業ずつ" in section


def test_phase_2c_freezes_shared_inputs_before_one_exactly_two_call_dispatch() -> None:
    skill = _skill_text()
    initial_dispatch = _between(skill, "##### 2c-1.", "##### 2c-2.")

    fixed_inputs = (
        "対象 collection の絶対 path",
        "確定企画",
        "theme",
        "planning.music.engine",
        "auto-selection",
        "textless",
    )
    dispatch_index = initial_dispatch.index("1 回の Agent tool dispatch")
    for fixed_input in fixed_inputs:
        assert initial_dispatch.index(fixed_input) < dispatch_index
    assert "独立した 2 call" in initial_dispatch
    assert "同じ message で同時起動" in initial_dispatch
    assert len(re.findall(r"^\s*- Agent [12]:", initial_dispatch, flags=re.MULTILINE)) == 2


def test_thumbnail_call_handles_finalized_and_missing_without_owning_approval() -> None:
    skill = _skill_text()
    initial_dispatch = _between(skill, "##### 2c-1.", "##### 2c-2.")

    assert "`status: FINALIZED`" in initial_dispatch
    assert "AI 生成を行わない" in initial_dispatch
    assert "既存 preview" in initial_dispatch
    assert "`status: MISSING`" in initial_dispatch
    assert "`/thumbnail <theme>`" in initial_dispatch
    assert "候補生成" in initial_dispatch
    assert "承認、確定コピー、state 更新" in initial_dispatch


def test_music_call_selects_suno_or_prompt_only_lyria() -> None:
    skill = _skill_text()
    initial_dispatch = _between(skill, "##### 2c-1.", "##### 2c-2.")

    assert "`music_engine: suno`" in initial_dispatch
    assert "`/music --prompt <theme>`" in initial_dispatch
    assert "`music_engine: lyria`" in initial_dispatch
    assert "`/music --generate <theme>`" in initial_dispatch
    assert "プロンプト設計だけ" in initial_dispatch
    assert "Lyria 3 API" in initial_dispatch
    assert "実行しない" in initial_dispatch


def test_both_calls_receive_concrete_contract_and_cannot_mutate_state() -> None:
    skill = _skill_text()
    initial_dispatch = _between(skill, "##### 2c-1.", "##### 2c-2.")

    for contract in (
        "対象 collection の絶対 path",
        "具体的な入力",
        "期待成果物の絶対 path",
        "完了報告形式",
        "`workflow-state.json` を更新しない",
        "AskUserQuestion を実行しない",
    ):
        assert contract in initial_dispatch


def test_join_keeps_main_owned_quality_state_and_partial_resume_contracts() -> None:
    skill = _skill_text()
    join = _between(skill, "##### 2c-2.", "#### 2e.")

    assert "両 Agent" in join
    assert "完了を待つ" in join
    assert "メイン" in join
    for gate in ("承認", "auto-selection", "textless", "`/thumbnail --compare`"):
        assert gate in join
    assert "Phase 2c 成果物・再開契約" in join
    assert "branch ごとに直列" in join
    assert "成功側" in join
    assert "失敗側だけ" in join
    assert "再生成しない" in join


def test_workflow_docs_explain_parallel_exception_and_state_owner() -> None:
    docs = WORKFLOW_CHEATSHEET.read_text(encoding="utf-8")

    assert "Phase 2c" in docs
    assert "2 Agent" in docs
    assert "同時" in docs
    assert "メイン" in docs
    assert "state" in docs
    assert "Phase 2c 以外" in docs
    assert "一作業ずつ" in docs
