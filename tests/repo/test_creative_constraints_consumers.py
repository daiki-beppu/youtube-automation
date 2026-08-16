"""Creative constraints consumer contract for generation and audit skills."""

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
SKILLS = {
    "music/references/prompt.md": ("「音」", "BPM", "Style"),
    "thumbnail/SKILL.md": ("サムネ向け", "色温度", "被写体"),
    "thumbnail/references/loop.md": ("「映像」", "動きの種類数上限", "禁止要素"),
    "audit/references/alignment.md": ("`audio`", "`thumbnail`", "整合性マトリクス"),
}


def test_generation_and_audit_skills_consume_creative_constraints_non_blocking() -> None:
    for relative, required_terms in SKILLS.items():
        text = (ROOT / ".claude" / "skills" / relative).read_text(encoding="utf-8")
        if relative == "music/references/prompt.md":
            text = (ROOT / ".claude" / "skills" / "music" / "SKILL.md").read_text(encoding="utf-8") + text
        if relative == "audit/references/alignment.md":
            text = (ROOT / ".claude" / "skills" / "audit" / "SKILL.md").read_text(encoding="utf-8") + text

        assert "`前工程`" in text
        assert "/channel-strategy --constraints" in text
        assert "CHANNEL_DIR/docs/channel/creative-constraints.json" in text
        assert "存在しなければ従来フローのまま続行" in text
        assert "不在だけを理由に" in text
        assert all(term in text for term in required_terms)
