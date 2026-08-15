"""Creative constraints consumer contract for generation and audit skills."""

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
SKILLS = {
    "music/references/prompt.md": ("## 音", "BPM", "Style"),
    "thumbnail/SKILL.md": ("## サムネ", "色温度", "被写体"),
    "loop-video/SKILL.md": ("## 映像", "動きの種類数上限", "禁止要素"),
    "alignment-check/SKILL.md": ("## 音", "## サムネ", "整合性マトリクス"),
}


def test_generation_and_audit_skills_consume_creative_constraints_non_blocking() -> None:
    for relative, required_terms in SKILLS.items():
        text = (ROOT / ".claude" / "skills" / relative).read_text(encoding="utf-8")
        if relative == "music/references/prompt.md":
            text = (ROOT / ".claude" / "skills" / "music" / "SKILL.md").read_text(encoding="utf-8") + text

        assert "`前工程`" in text
        assert "/channel-strategy --constraints" in text
        assert "CHANNEL_DIR/docs/channel/creative-constraints.md" in text
        assert "存在しなければ従来フローのまま続行" in text
        assert "不在だけを理由に" in text
        assert all(term in text for term in required_terms)
