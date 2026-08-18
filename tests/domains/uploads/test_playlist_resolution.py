"""プレイリスト解決の純関数テスト (#4346).

theme slug の部分一致だけに依存していた頃の事故（新テーマを作るたびに
auto_add_themes が未登録で、黙って auto_add プレイリストだけに入る）が
再発しないことを固定する。
"""

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.uploads.playlist_resolution import (
    categorizing_playlist_keys,
    check_playlist_assignment,
    resolve_playlist_keys,
    validate_playlist_keys,
)

PLAYLISTS = {
    "all": {"title": "All", "auto_add": True, "playlist_id": "PL_ALL"},
    "rain": {"title": "Rain", "auto_add_themes": ["rain", "neon"], "playlist_id": "PL_RAIN"},
    "rooms": {"title": "Rooms", "auto_add_activities": ["Focus"], "playlist_id": "PL_ROOMS"},
}
AUTO_ADD_ONLY = {"all": {"title": "All", "auto_add": True, "playlist_id": "PL_ALL"}}


class TestCategorizingPlaylistKeys:
    def test_excludes_auto_add(self):
        assert categorizing_playlist_keys(PLAYLISTS) == ["rain", "rooms"]

    def test_empty_when_only_auto_add(self):
        assert categorizing_playlist_keys(AUTO_ADD_ONLY) == []


class TestValidatePlaylistKeys:
    def test_accepts_known_keys(self):
        validate_playlist_keys(PLAYLISTS, ["rain", "all"], source="--playlist")

    def test_rejects_unknown_key(self):
        with pytest.raises(ValidationError) as exc:
            validate_playlist_keys(PLAYLISTS, ["rain", "typo"], source="--playlist")
        assert "typo" in str(exc.value)
        assert "--playlist" in str(exc.value)


class TestResolveExplicit:
    def test_explicit_wins_over_keyword_match(self):
        """明示指定があれば theme キーワードは一切参照しない."""
        result = resolve_playlist_keys(PLAYLISTS, "rain-city", activity="Focus", explicit=["rooms"])
        assert result == ["all", "rooms"]

    def test_auto_add_always_included(self):
        result = resolve_playlist_keys(PLAYLISTS, "anything", activity="", explicit=["rain"])
        assert "all" in result

    def test_empty_explicit_means_auto_add_only(self):
        result = resolve_playlist_keys(PLAYLISTS, "rain-city", activity="Focus", explicit=[])
        assert result == ["all"]

    def test_result_follows_config_order(self):
        result = resolve_playlist_keys(PLAYLISTS, "x", activity="", explicit=["rooms", "rain"])
        assert result == ["all", "rain", "rooms"]

    def test_unknown_explicit_key_fails_loud(self):
        with pytest.raises(ValidationError):
            resolve_playlist_keys(PLAYLISTS, "x", activity="", explicit=["nope"])


class TestResolveLegacyFallback:
    def test_theme_keyword_still_matches(self):
        result = resolve_playlist_keys(PLAYLISTS, "Neon Rain Crossing", activity="Study", explicit=None)
        assert result == ["all", "rain"]

    def test_activity_still_matches(self):
        result = resolve_playlist_keys(PLAYLISTS, "unknown", activity="Focus", explicit=None)
        assert result == ["all", "rooms"]

    @pytest.mark.parametrize("separator", ["·", ","])
    def test_activity_separators(self, separator):
        activity = separator.join(["Study", "Focus"])
        assert "rooms" in resolve_playlist_keys(PLAYLISTS, "unknown", activity=activity, explicit=None)

    def test_new_theme_falls_through_to_auto_add_only(self):
        """回帰の再現: carriage-six / the-long-way-home はどのキーワードにも当たらない."""
        for theme in ("carriage-six", "the-long-way-home"):
            assert resolve_playlist_keys(PLAYLISTS, theme, activity="Study", explicit=None) == ["all"]


class TestCheckPlaylistAssignment:
    def test_flags_auto_add_only_result(self):
        issue = check_playlist_assignment(PLAYLISTS, ["all"], theme="carriage-six", explicit=None)
        assert issue is not None
        assert "carriage-six" in issue
        assert "set-planning playlists" in issue

    def test_silent_when_categorizing_playlist_matched(self):
        assert check_playlist_assignment(PLAYLISTS, ["all", "rain"], theme="rain-city", explicit=None) is None

    def test_silent_when_channel_has_no_categorizing_playlist(self):
        assert check_playlist_assignment(AUTO_ADD_ONLY, ["all"], theme="anything", explicit=None) is None

    def test_explicit_empty_is_an_accepted_operator_decision(self):
        assert check_playlist_assignment(PLAYLISTS, ["all"], theme="anything", explicit=[]) is None

    def test_explicit_auto_add_key_does_not_claim_a_categorizing_assignment(self):
        issue = check_playlist_assignment(PLAYLISTS, ["all"], theme="anything", explicit=["all"])

        assert issue is not None
        assert "分類プレイリスト" in issue

    def test_flags_categorizing_playlist_without_youtube_id(self):
        playlists = {
            **PLAYLISTS,
            "rain": {"title": "Rain", "auto_add_themes": ["rain"]},
        }

        issue = check_playlist_assignment(playlists, ["all", "rain"], theme="rain", explicit=["rain"])

        assert issue is not None
        assert "playlist_id 未設定" in issue
        assert "rain" in issue
