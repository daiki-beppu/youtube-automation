"""collection-ideate skill と yt-generate-image help の ownership 境界。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "collection-ideate"
SKILL_TEXT = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
GENERATION_TEXT = (SKILL_DIR / "references" / "preview-generation.md").read_text(encoding="utf-8")


def _generate_image_invocations(markdown: str) -> list[str]:
    return re.findall(r"^\s*uv run yt-generate-image(?:\s|$)", markdown, flags=re.MULTILINE)


def test_skill_keeps_mode_commands_and_delegates_flag_help() -> None:
    skill_invocations = _generate_image_invocations(SKILL_TEXT)
    reference_invocations = _generate_image_invocations(GENERATION_TEXT)

    assert len(skill_invocations) == 2
    assert reference_invocations == []
    assert "`uv run yt-generate-image --help`" in SKILL_TEXT


def test_skill_prose_does_not_redefine_normal_generate_image_flags() -> None:
    distributed_text = f"{SKILL_TEXT}\n{GENERATION_TEXT}"
    prose = re.sub(r"```.*?```", "", distributed_text, flags=re.DOTALL)

    for option in ("prompt", "output", "model", "reference-index", "max-attempts", "yes"):
        assert re.search(rf"--{option}\b", prose) is None


def test_skill_keeps_mode_dispatch_and_generation_order() -> None:
    phase_4 = SKILL_TEXT.index("### Phase 4:")
    mode_dispatch = SKILL_TEXT.index("`preview.thumbnail_mode`", phase_4)
    cost_approval = SKILL_TEXT.index("confirm_cost", mode_dispatch)
    session_creation = SKILL_TEXT.index("mkdir -p", cost_approval)
    generation_dispatch = SKILL_TEXT.index("](references/preview-generation.md)", session_creation)
    parallel_command = SKILL_TEXT.index("uv run yt-generate-image", generation_dispatch)
    validation = SKILL_TEXT.index("yt-thumbnail-check", parallel_command)
    sequential = SKILL_TEXT.index("### Phase 4 補足: sequential", validation)
    sequential_command = SKILL_TEXT.index("uv run yt-generate-image", sequential)

    assert mode_dispatch < cost_approval < session_creation < generation_dispatch
    assert generation_dispatch < parallel_command < validation < sequential < sequential_command


def test_generation_reference_keeps_strict_references_and_failure_contracts() -> None:
    strict_reference_paragraph = next(
        paragraph for paragraph in GENERATION_TEXT.split("\n\n") if "TTP strict" in paragraph and "一意" in paragraph
    )

    assert "stock" in strict_reference_paragraph
    assert "生成前に停止" in GENERATION_TEXT
    assert "exit 0" in GENERATION_TEXT
    assert "exit 1" in GENERATION_TEXT
    assert "不合格候補だけを再生成" in GENERATION_TEXT
    assert "同じ4-4" in GENERATION_TEXT


def test_skill_keeps_output_and_cleanup_order() -> None:
    next_step = SKILL_TEXT.index("## Next Step")
    assignment = SKILL_TEXT.index("record-ttp-reference-assignments.py", next_step)
    adopted_copy = SKILL_TEXT.index("cp collections/planning/_plan-previews", assignment)
    stock_archive = SKILL_TEXT.index("uv run yt-stock-archive", adopted_copy)
    cleanup = SKILL_TEXT.index("rm -rf collections/planning/_plan-previews", stock_archive)

    assert assignment < adopted_copy < stock_archive < cleanup
