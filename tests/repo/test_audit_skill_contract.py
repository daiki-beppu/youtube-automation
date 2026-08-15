"""`/audit --alignment` の公開 skill 契約を検証する。"""

from __future__ import annotations

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
AUDIT_DIR = INVENTORY.skill_directory("audit")


def test_audit_exposes_alignment_as_an_exclusive_mode() -> None:
    skill_names = {path.name for path in INVENTORY.skill_directories()}
    frontmatter = INVENTORY.frontmatter("audit")
    mode = INVENTORY.section("audit", "## モード判定")

    assert "audit" in skill_names
    assert "alignment-check" not in skill_names
    assert isinstance(frontmatter, dict)
    assert frontmatter["name"] == "audit"
    assert frontmatter["purpose"] == "振り返る"
    assert "--alignment" in frontmatter["description"]
    assert "2 個以上" in mode
    assert "1 個なら" in mode
    assert "0 個なら" in mode
    assert "| `--alignment` | `references/alignment.md` |" in mode
    assert INVENTORY.reference_exists("audit", "references/alignment.md")


def test_alignment_mode_keeps_the_audit_inputs_and_external_read_only_boundary() -> None:
    skill = (AUDIT_DIR / "SKILL.md").read_text(encoding="utf-8")
    alignment = (AUDIT_DIR / "references" / "alignment.md").read_text(encoding="utf-8")
    handoff = INVENTORY.section("audit", "## 前後工程")
    boundary = _section(alignment, "## 読み取り専用境界")

    assert "/channel-strategy --constraints" in handoff
    assert "/thumbnail" in handoff
    assert "/music" in handoff
    assert "docs/plans/alignment-audit.md" in skill
    for input_path in (
        "collections/<id>/10-assets/thumbnail.jpg",
        "collections/<id>/20-documentation/suno-prompts.md",
        "collections/<id>/workflow-state.json",
    ):
        assert input_path in skill
    for dimension in ("音楽ムード", "サムネ", "タイトル"):
        assert dimension in alignment
    assert "外部サービスへの書き込みを行わない" in boundary
    assert "変更は候補提示まで" in boundary


def _section(text: str, heading: str) -> str:
    start = text.index(f"{heading}\n") + len(heading) + 1
    rest = text[start:]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def test_alignment_reference_contains_no_external_mutation_command() -> None:
    alignment_path = AUDIT_DIR / "references" / "alignment.md"
    alignment = alignment_path.read_text(encoding="utf-8")

    forbidden_commands = (
        "videos().update",
        "thumbnails().set",
        "channels().update",
        "playlists().insert",
        "playlistItems().insert",
    )
    assert all(command not in alignment for command in forbidden_commands)
