"""Creative constraints consumer contract for generation and audit skills."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = {
    "suno": ("## 音", "BPM", "Style"),
    "thumbnail": ("## サムネ", "色温度", "被写体"),
    "loop-video": ("## 映像", "動きの種類数上限", "禁止要素"),
    "alignment-check": ("## 音", "## サムネ", "整合性マトリクス"),
}


def test_generation_and_audit_skills_consume_creative_constraints_non_blocking() -> None:
    for skill, required_terms in SKILLS.items():
        text = (ROOT / ".claude" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")

        assert "`前工程`" in text
        assert "/creative-constraints" in text
        assert "CHANNEL_DIR/docs/channel/creative-constraints.md" in text
        assert "存在しなければ従来フローのまま続行" in text
        assert "不在だけを理由に" in text
        assert all(term in text for term in required_terms)
