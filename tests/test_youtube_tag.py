"""youtube_tag.youtube_tag_chars の挙動検証."""

from __future__ import annotations

from youtube_automation.utils.youtube_tag import youtube_tag_chars


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
