"""段階開示後の wf-new 企画規則の所有契約。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "wf-new" / "references"
SKILL_MD = SKILL_DIR / "ideate.md"
PLANNING_RULES_MD = SKILL_DIR / "planning-rules.md"
PREVIEW_CONTRACT_MD = SKILL_DIR / "preview-contract.md"
PREVIEW_GENERATION_MD = SKILL_DIR / "preview-generation.md"
SELECTION_HANDOFF_MD = SKILL_DIR / "selection-handoff.md"

PLANNING_RULE_HEADINGS = {
    "現在のチャンネル規定",
    "ペルソナベース企画フレームワーク",
    "タイトルテンプレート",
    "差別化軸",
    "vote-log hook",
    "オブジェクトデザインルール",
    "オリジナリティ保証ルール",
    "第一ペルソナの企画バリエーション",
}
PREVIEW_CONTRACT_HEADINGS = {
    "Preview 設定",
    "候補 schema",
    "コスト計算契約",
    "セルフチェック契約",
}
PREVIEW_GENERATION_HEADINGS = {
    "Parallel 生成詳細",
    "Sequential 生成詳細",
    "出力検証と再生成",
    "Failure handling",
}
SELECTION_HANDOFF_HEADINGS = {
    "採用候補の保存",
    "Reference assignment",
    "Stock archive",
    "Cleanup と失敗時処理",
    "Handoff semantics",
}


def _headings(markdown: str) -> set[str]:
    headings: set[str] = set()
    for match in re.finditer(r"^#{2,4}\s+(.+?)\s*$", markdown, re.MULTILINE):
        heading = re.sub(r"\s*\([^)]*\)\s*$", "", match.group(1))
        headings.add(re.sub(r"\s*（[^）]*）\s*$", "", heading))
    return headings


def test_skill_dispatches_planning_rules_to_distributed_reference() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = PLANNING_RULES_MD.relative_to(SKILL_DIR).as_posix()

    assert f"]({relative_reference})" in skill
    assert PLANNING_RULES_MD.is_file()


def test_planning_rule_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(PLANNING_RULES_MD.read_text(encoding="utf-8"))

    assert PLANNING_RULE_HEADINGS <= reference_headings
    assert PLANNING_RULE_HEADINGS.isdisjoint(skill_headings)


def test_skill_keeps_phase_order_and_approval_boundary() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    dispatch = skill.index("](planning-rules.md)")
    phase_2 = skill.index("### Phase 2:")
    phase_3 = skill.index("### Phase 3:")
    phase_4 = skill.index("### Phase 4:")
    approval = skill.index("confirm_cost", phase_4)

    assert dispatch < phase_2 < phase_3 < phase_4 < approval


def test_wf_new_ideation_loads_current_channel_constraints_before_analysis() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    constraint_resolution = skill.index("固定制約の解決")
    phase_1_4 = skill.index("#### Phase 1-4:")
    planning_dispatch = skill.index("](planning-rules.md)")

    assert constraint_resolution < planning_dispatch < phase_1_4
    for path in (
        "config/channel/*.json",
        "docs/channel/channel-direction.json",
        "docs/channel/personas/persona-definition.json",
        "docs/plans/viewing-scene-matrix.json",
        "docs/channel/creative-constraints.json",
    ):
        assert path in skill
    assert "存在するファイルだけ" in skill
    assert "存在しない規定を推測" in skill


def test_planning_rules_fail_closed_on_current_channel_constraint_violation() -> None:
    rules = PLANNING_RULES_MD.read_text(encoding="utf-8")
    section = rules.split("## 現在のチャンネル規定（固定制約）", 1)[1].split("\n## ", 1)[0]

    for input_source in (
        "Analytics",
        "benchmark",
        "open insights",
        "ユーザー直接入力",
    ):
        assert input_source in section
    assert "候補ごと" in section
    assert "適用規定" in section
    assert "適合根拠" in section
    assert "FAIL" in section
    assert "preview.candidate_count" in section
    assert "警告付きで残さない" in section
    assert "ユーザー判断へ委ねない" in section
    assert "違反した規定" in section
    assert "再開条件" in section


def test_wf_new_accepts_only_verified_constraint_compliant_plans() -> None:
    skill_dir = REPO_ROOT / ".claude" / "skills" / "wf-new"
    wf_new = "\n".join(
        path.read_text(encoding="utf-8") for path in (skill_dir / "SKILL.md", skill_dir / "references" / "phase2.md")
    )
    delegation = wf_new.split("2. **Agent ツールで内部企画工程を委譲**", 1)[1].split("\n### Phase 2:", 1)[0]

    assert "固定制約" in delegation
    assert "候補ごとの適合結果" in delegation
    assert "未検証" in delegation
    assert "FAIL" in delegation
    assert "期待成果物欠落" in delegation
    assert "state を更新せず停止" in delegation


def test_skill_dispatches_preview_contract_before_preview_steps() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = PREVIEW_CONTRACT_MD.relative_to(SKILL_DIR).as_posix()

    dispatch = skill.index(f"]({relative_reference})")
    first_preview_step = skill.index("**4-1:")

    assert PREVIEW_CONTRACT_MD.is_file()
    assert dispatch < first_preview_step


def test_preview_contract_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(PREVIEW_CONTRACT_MD.read_text(encoding="utf-8"))

    assert PREVIEW_CONTRACT_HEADINGS <= reference_headings
    assert PREVIEW_CONTRACT_HEADINGS.isdisjoint(skill_headings)


def test_preview_contract_preserves_phase_4_1_prompt_semantics() -> None:
    contract = PREVIEW_CONTRACT_MD.read_text(encoding="utf-8")

    assert "英語 1 段落" in contract
    assert "誇張表現禁止" in contract
    assert "16:9 構図" in contract
    assert "テキスト除外" in contract


def test_preview_contract_dispatches_generation_mode_prompt_source() -> None:
    contract = PREVIEW_CONTRACT_MD.read_text(encoding="utf-8")

    single_step = contract.index("`generation_mode: single_step`")
    diff_template = contract.index("`diff_prompt_template`", single_step)
    other_modes = contract.index("それ以外の generation mode", diff_template)
    phase_4_1_prompt = contract.index("Phase 4-1 のプロンプト全文", other_modes)

    assert single_step < diff_template < other_modes < phase_4_1_prompt


def test_cost_approval_precedes_preview_side_effects() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    phase_4 = skill.index("### Phase 4:")

    approval = skill.index("confirm_cost", phase_4)
    session_creation = skill.index("mkdir -p", phase_4)
    image_generation = skill.index("yt-generate-image", phase_4)

    assert approval < session_creation < image_generation


def test_skill_dispatches_preview_generation_before_generation_steps() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = PREVIEW_GENERATION_MD.relative_to(SKILL_DIR).as_posix()

    dispatch = skill.index(f"]({relative_reference})")
    parallel_generation = skill.index("**4-4: プロンプト構築 + 一括生成（parallel デフォルト）**")

    assert PREVIEW_GENERATION_MD.is_file()
    assert dispatch < parallel_generation


def test_preview_generation_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(PREVIEW_GENERATION_MD.read_text(encoding="utf-8"))

    assert PREVIEW_GENERATION_HEADINGS <= reference_headings
    assert PREVIEW_GENERATION_HEADINGS.isdisjoint(skill_headings)


def test_skill_keeps_generation_routing_commands_and_hard_gates() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    phase_4 = skill.index("### Phase 4:")

    mode_decision = skill.index("`preview.thumbnail_mode`", phase_4)
    approval = skill.index("confirm_cost", phase_4)
    session_creation = skill.index("mkdir -p", phase_4)
    dispatch = skill.index("](preview-generation.md)", phase_4)
    parallel_generation = skill.index("**4-4: プロンプト構築 + 一括生成（parallel デフォルト）**")
    validation = skill.index("yt-thumbnail-check", parallel_generation)
    user_selection = skill.index("**4-5: 全枚を比較提示 → ユーザー選択**", validation)

    assert mode_decision < approval < session_creation < dispatch < parallel_generation < validation < user_selection
    for command in (
        "select-ttp-references.py",
        "codex-image.sh --require-reference",
        "yt-generate-image --ttp-strict-references",
        "yt-thumbnail-check",
    ):
        assert command in skill
    for hard_gate in (
        "参照不足なら生成せず停止",
        "生成成功が 0 枚",
        "不合格候補だけを再生成",
        "生成失敗",
    ):
        assert hard_gate in skill


def test_skill_dispatches_selection_handoff_after_user_selection() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = SELECTION_HANDOFF_MD.relative_to(SKILL_DIR).as_posix()

    user_selection = skill.index("**4-5: 全枚を比較提示 → ユーザー選択**")
    dispatch = skill.index(f"]({relative_reference})")
    report_save = skill.index("## 企画レポート保存", dispatch)

    assert SELECTION_HANDOFF_MD.is_file()
    assert user_selection < dispatch < report_save


def test_selection_handoff_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(SELECTION_HANDOFF_MD.read_text(encoding="utf-8"))

    assert SELECTION_HANDOFF_HEADINGS <= reference_headings
    assert SELECTION_HANDOFF_HEADINGS.isdisjoint(skill_headings)

    skill = SKILL_MD.read_text(encoding="utf-8")
    reference = SELECTION_HANDOFF_MD.read_text(encoding="utf-8")
    for detail in (
        "空ファイルや代替画像を作らない",
        "生成途中の候補、不採用候補、未生成候補",
        "7日以上経過したもの",
        "同じ段階から再開する",
    ):
        assert detail not in skill
        assert reference.count(detail) == 1


def test_skill_keeps_selection_commands_hard_gates_and_handoff_order() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    next_step = skill.index("## Next Step")

    report_save = skill.index("plan_proposals.md")
    planning_generated = skill.index("planning.generated = true", report_save)
    final_title = skill.index("planning.final_title", next_step)
    assignment = skill.index("record-ttp-reference-assignments.py", next_step)
    parallel = skill.index("### parallel モード（デフォルト）", assignment)
    adopted_copy = skill.index("cp collections/planning/_plan-previews", parallel)
    stock_archive = skill.index("uv run yt-stock-archive", adopted_copy)
    parallel_cleanup = skill.index("rm -rf collections/planning/_plan-previews", stock_archive)
    downstream_thumbnail = skill.index("`/thumbnail <theme>`", parallel_cleanup)
    downstream_suno = skill.index("`/music --prompt <theme>`", downstream_thumbnail)

    assert report_save < planning_generated < final_title < assignment
    assert assignment < adopted_copy < stock_archive < parallel_cleanup
    assert parallel_cleanup < downstream_thumbnail < downstream_suno
    for command in (
        "record-ttp-reference-assignments.py",
        "uv run yt-stock-archive",
        "cp collections/planning/_plan-previews",
        "rm -rf collections/planning/_plan-previews",
    ):
        assert command in skill
    for hard_gate in (
        "保存に失敗した場合は処理を継続せず",
        "`main.png` にはコピーしない",
        "`planning-preview.png` が未生成",
    ):
        assert hard_gate in skill


def test_skill_keeps_mode_specific_cleanup_order() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    sequential = skill.index("### sequential モード時の Next Step")
    no_image = skill.index("### コスト拒否 / 生成失敗で企画参照画像が無い場合", sequential)
    handoff = skill.index("企画選択後:", no_image)

    sequential_block = skill[sequential:no_image]
    assert sequential_block.index("cp collections/planning/_plan-previews") < sequential_block.index(
        "rm -rf collections/planning/_plan-previews"
    )
    assert "yt-stock-archive" not in sequential_block

    no_image_block = skill[no_image:handoff]
    assert "planning-preview.png コピーはスキップ" in no_image_block
    assert "rm -rf collections/planning/_plan-previews" in no_image_block
    assert "record-ttp-reference-assignments.py" not in no_image_block
