from __future__ import annotations

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.suno.name_matching import normalize_suno_name_for_lookup, suno_prompt_lookup_candidates
from youtube_automation.domains.suno.playlist import verify_playlist_titles


def test_normalization_uses_one_unicode_category_policy_for_symbols_and_whitespace() -> None:
    assert normalize_suno_name_for_lookup(" Ｇｒｅｅｄ’ｓ\tRhythm — ☆ ") == "greedsrhythm"


@pytest.mark.parametrize("separator", ["—", "–", "―"])
def test_playlist_matching_treats_dash_family_like_removed_zip_separators(separator: str) -> None:
    result = verify_playlist_titles(
        [f"Midnight {separator} Echo"],
        ["Midnight Echo"],
        expected_clips_per_entry=1,
    )

    assert result.ok
    assert result.matched == {f"Midnight {separator} Echo": 1}


def test_playlist_matching_keeps_apostrophe_removed_regression() -> None:
    result = verify_playlist_titles(
        ["Greed's Rhythm"],
        ["Greeds Rhythm"],
        expected_clips_per_entry=1,
    )

    assert result.ok


def test_playlist_matching_rejects_names_that_collide_after_symbol_normalization() -> None:
    with pytest.raises(ValidationError, match="正規化後に衝突"):
        verify_playlist_titles(
            ["AB — C", "A — BC"],
            ["ABC"],
            expected_clips_per_entry=1,
        )


@pytest.mark.parametrize("title", [None, "", " \t\n", "夜景 — Echo", "Echo"])
def test_prompt_aliases_keep_name_priority_and_deduplicate_title(title):
    assert suno_prompt_lookup_candidates("Track 12 夜景 — Echo", title) == ("夜景 — Echo", "Echo")


def test_prompt_aliases_append_distinct_title_after_all_name_aliases():
    assert suno_prompt_lookup_candidates("Track 12 夜景 — Echo", "別名 — Dawn") == (
        "夜景 — Echo",
        "Echo",
        "別名 — Dawn",
        "Dawn",
    )


def test_prompt_aliases_retain_numeric_song_prefix():
    assert suno_prompt_lookup_candidates("3 AM", "夜明け") == ("3 AM", "AM", "夜明け")
