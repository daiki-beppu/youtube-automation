"""preflight_checks の各 check_* 関数の挙動検証."""

from __future__ import annotations

from pathlib import Path

from youtube_automation.utils.preflight_checks import (
    check_duration,
    check_tags_count,
    check_tags_yt_chars,
    extract_descriptions_md_tags,
)


class TestCheckTagsCount:
    def test_none_skips_check(self) -> None:
        assert check_tags_count(["a"], None) is None

    def test_under_min_returns_message(self) -> None:
        msg = check_tags_count(["a", "b"], 5)
        assert msg == "tags count: 2 (min 5)"

    def test_at_min_passes(self) -> None:
        assert check_tags_count(["a", "b", "c"], 3) is None

    def test_over_min_passes(self) -> None:
        assert check_tags_count(["a"] * 50, 10) is None


class TestCheckTagsYtChars:
    def test_below_limit_passes(self) -> None:
        assert check_tags_yt_chars(["short"]) is None

    def test_exactly_at_limit_passes(self) -> None:
        # 9 文字 × 50 + カンマ 49 = 499 → 500 制限内
        tags = ["123456789"] * 50
        assert check_tags_yt_chars(tags) is None

    def test_over_limit_returns_message(self) -> None:
        # スペース付き 11 文字 → quotation 込み 13、× 50 + カンマ 49 = 699
        tags = ["lofi  beats"] * 50
        msg = check_tags_yt_chars(tags)
        assert msg is not None
        assert msg.startswith("tags YT chars (quoted):")
        assert "/ 500" in msg

    def test_custom_limit(self) -> None:
        assert check_tags_yt_chars(["abc"], limit=2) == "tags YT chars (quoted): 3 / 2"


class TestCheckDuration:
    def test_both_none_skips(self) -> None:
        assert check_duration(123.0, None, None) is None

    def test_within_range_passes(self) -> None:
        # 2h30m
        assert check_duration(9000, 8520, 9240) is None

    def test_under_min_fails(self) -> None:
        # 1h17m vs target 2h22m〜2h34m
        msg = check_duration(4620, 8520, 9240)
        assert msg is not None
        assert "1h17m" in msg
        assert "2h22m〜2h34m" in msg

    def test_over_max_fails(self) -> None:
        # 2h46m vs target 2h22m〜2h34m
        msg = check_duration(9960, 8520, 9240)
        assert msg is not None
        assert "2h46m" in msg
        assert "2h22m〜2h34m" in msg

    def test_only_min_set(self) -> None:
        # min のみ。下回るときは fail、上回るときは pass
        assert check_duration(60, 100, None) is not None
        assert check_duration(200, 100, None) is None

    def test_only_max_set(self) -> None:
        assert check_duration(200, None, 100) is not None
        assert check_duration(50, None, 100) is None


class TestExtractDescriptionsMdTags:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert extract_descriptions_md_tags(tmp_path / "missing.md") is None

    def test_returns_none_when_section_missing(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text("## タイトル案\n```\nFoo\n```\n", encoding="utf-8")
        assert extract_descriptions_md_tags(p) is None

    def test_extracts_comma_separated_tags(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text(
            "## タグ（YouTube タグ欄）\n```\nlofi beats, jazz, study music\n```\n",
            encoding="utf-8",
        )
        assert extract_descriptions_md_tags(p) == ["lofi beats", "jazz", "study music"]

    def test_extracts_newline_separated_tags(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text(
            "## タグ（YouTube タグ欄）\n```\nlofi beats\njazz\nstudy\n```\n",
            encoding="utf-8",
        )
        assert extract_descriptions_md_tags(p) == ["lofi beats", "jazz", "study"]

    def test_returns_none_for_empty_section(self, tmp_path: Path) -> None:
        p = tmp_path / "descriptions.md"
        p.write_text("## タグ（YouTube タグ欄）\n```\n\n```\n", encoding="utf-8")
        assert extract_descriptions_md_tags(p) is None
