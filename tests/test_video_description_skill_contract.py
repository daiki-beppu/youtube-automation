from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VIDEO_DESCRIPTION_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "video-description" / "SKILL.md"


def test_video_description_skill_reads_benchmark_descriptions_before_template_fallback():
    text = _VIDEO_DESCRIPTION_SKILL_MD.read_text(encoding="utf-8")

    assert "### Benchmark 概要欄 TTP 参照" in text
    assert "docs/benchmarks/*.md" in text
    assert "概要欄TTPサンプル" in text
    assert "data/benchmark_*.json" in text
    assert "channels[].videos[].description" in text
    assert "冒頭文の構造" in text
    assert "Tracklist/目次書式" in text
    assert "CTA" in text
    assert "ハッシュタグ記法" in text
    assert "装飾量" in text
    assert "存在しない場合のみ" in text
    assert "Complete Collection テンプレートへフォールバック" in text
