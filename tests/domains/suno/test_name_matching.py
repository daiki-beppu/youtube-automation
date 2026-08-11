from __future__ import annotations

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.suno.name_matching import normalize_suno_name_for_lookup
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
