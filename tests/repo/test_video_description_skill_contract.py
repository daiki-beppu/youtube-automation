from tests.helpers.paths import REPO_ROOT

_REPO_ROOT = REPO_ROOT
_VIDEO_DESCRIPTION_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "video" / "references" / "describe.md"


def test_video_describe_mode_reads_benchmark_descriptions_before_template_fallback():
    text = _VIDEO_DESCRIPTION_SKILL_MD.read_text(encoding="utf-8")

    assert "### Benchmark 概要欄 TTP" in text
    assert "docs/benchmarks/benchmark-report.json" in text
    assert "read_published_json_document" in text
    assert "data/benchmark_*.json" in text
    assert "channels[].videos[].description" in text
    assert "冒頭ハッシュタグの有無と位置" in text
    assert "段落構成と段落数" in text
    assert "CTA" in text
    assert "エンゲージメント質問の挿入位置と数" in text
    assert "Keywords セクションの有無と量" in text
    assert "存在しない場合のみ" in text
    assert "Complete Collection テンプレートへフォールバック" in text
    assert "テンプレ使い回し禁止" in text
