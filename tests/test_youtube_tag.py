"""youtube_tag モジュールの挙動検証."""

from __future__ import annotations

from youtube_automation.utils.youtube_tag import normalize_youtube_tags, youtube_tag_chars

# ---------------------------------------------------------------------------
# normalize_youtube_tags
# ---------------------------------------------------------------------------


class TestNormalizeYoutubeTags:
    """normalize_youtube_tags がダブルクォートを正しく除去する."""

    def test_strips_surrounding_double_quotes(self) -> None:
        assert normalize_youtube_tags(['"lofi beats"', '"jazz"']) == ["lofi beats", "jazz"]

    def test_leaves_unquoted_tags_unchanged(self) -> None:
        assert normalize_youtube_tags(["chiptune", "8-bit"]) == ["chiptune", "8-bit"]

    def test_handles_mixed_quoted_and_unquoted(self) -> None:
        assert normalize_youtube_tags(['"lofi beats"', "jazz", '"study music"']) == [
            "lofi beats",
            "jazz",
            "study music",
        ]

    def test_empty_list_returns_empty(self) -> None:
        assert normalize_youtube_tags([]) == []

    def test_strips_only_leading_and_trailing_quotes(self) -> None:
        """内部のダブルクォートは除去しない."""
        assert normalize_youtube_tags(['"say "hello" world"']) == ['say "hello" world']


# ---------------------------------------------------------------------------
# youtube_tag_chars
# ---------------------------------------------------------------------------


def test_empty_list_is_zero() -> None:
    assert youtube_tag_chars([]) == 0


def test_no_space_tags_match_naive_join() -> None:
    tags = ["chiptune", "8bit", "rpg"]
    assert youtube_tag_chars(tags) == len(",".join(tags))


def test_space_tags_quoted_correctly() -> None:
    # `"lofi beats"` (12 chars) + `,` + `jazz` (4 chars) = 17
    assert youtube_tag_chars(["lofi beats", "jazz"]) == 17


def test_mixed_tags_compute_quoted_length() -> None:
    tags = ["a b c", "x", "y z"]
    # `"a b c"` (7) + `,` + `x` (1) + `,` + `"y z"` (5) = 15
    assert youtube_tag_chars(tags) == 15


def test_single_tag_with_space() -> None:
    assert youtube_tag_chars(["lofi beats"]) == len('"lofi beats"')
