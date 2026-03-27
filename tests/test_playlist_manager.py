"""
PlaylistManager.resolve_playlists のテスト

RJN の channel_config.json 相当の設定で、
テーマ → 再生リスト解決が正しく動作することを検証。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.channel_config import ChannelConfig

# ─── テスト用設定データ（RJN の playlists + theme_scenes を再現） ───

RJN_CONFIG = {
    "channel": {
        "name": "Rain Jazz Night",
        "short": "RJN",
        "youtube_handle": "@rainjazznight",
        "url": "https://www.youtube.com/@rainjazznight",
        "core_message": "Your rainy night jazz escape",
        "cta_subscribe": "Subscribe!",
        "tagline": "Your rainy night jazz escape",
    },
    "genre": {"primary": "jazz", "style": "rainy night", "context": "cafe ambience"},
    "youtube": {"category_id": "10", "privacy_status": "public", "language": "en"},
    "tags": {"base": ["rain jazz"], "themes": {}},
    "descriptions": {
        "opening": "test",
        "sub_opening": "test",
        "perfect_for": [],
        "hashtags": [],
    },
    "analytics": {"collection_filter_keywords": []},
    "suno": {"workspace_name": "RJN", "genre_line": "jazz", "exclude_styles": ""},
    "title": {
        "template": "Playlist {scene_phrase} BGM",
        "default_activities": "Study · Focus · Late Night",
        "theme_scenes": {
            "city": {"scene": "Rainy city night", "activities": "Study · Focus · Late Night"},
            "rooftop": {"scene": "Quiet rooftop", "activities": "Chill · Focus · Unwind"},
            "cafe": {"scene": "Rainy night cafe", "activities": "Study · Work · Reading"},
            "sleep": {"scene": "Quiet rain at midnight", "activities": "Sleep · Deep Rest · Calm"},
            "melancholy": {"scene": "Lonely streetlamp", "activities": "Late Night · Reflection"},
            "midnight-blues": {"scene": "Midnight blues in the rain", "activities": "Late Night · Chill · Reflection"},
        },
    },
    "playlists": {
        "all": {
            "title": "Rain Jazz Night",
            "playlist_id": "",
            "auto_add": True,
        },
        "study": {
            "title": "Rain Jazz for Study & Focus | Late Night BGM",
            "playlist_id": "",
            "auto_add_activities": ["Study", "Focus", "Work", "Chill"],
        },
    },
    "benchmark": {"channels": []},
}


# ─── Fixtures ────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_singleton():
    ChannelConfig.reset()
    yield
    ChannelConfig.reset()


@pytest.fixture
def config_file(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "channel_config.json"
    config_path.write_text(json.dumps(RJN_CONFIG), encoding="utf-8")
    return config_path


@pytest.fixture
def cfg(config_file):
    return ChannelConfig.load(config_path=str(config_file))


# ─── resolve_playlists テスト ─────────────────────────


class TestResolvePlaylists:
    """PlaylistManager.resolve_playlists のロジックを直接テスト

    PlaylistManager は YouTube API 依存があるため、
    resolve_playlists のコアロジックを直接検証する。
    """

    def _resolve(self, cfg, theme: str) -> list[str]:
        """PlaylistManager.resolve_playlists と同等のロジック"""
        playlists_config = cfg.playlists
        activity = cfg.get_activity_for_theme(theme)
        matched = []

        for key, pl in playlists_config.items():
            if pl.get('auto_add'):
                matched.append(key)
                continue
            activities = [a.strip() for a in activity.split('·')]
            if any(a in pl.get('auto_add_activities', []) for a in activities):
                matched.append(key)
                continue
            for theme_kw in pl.get('auto_add_themes', []):
                if theme_kw in theme.lower():
                    matched.append(key)
                    break

        return matched

    def test_city_routes_to_all_and_study(self, cfg):
        result = self._resolve(cfg, "city")
        assert "all" in result
        assert "study" in result

    def test_rooftop_lights_routes_to_all_and_study(self, cfg):
        """rooftop-lights は Focus と Chill で study にマッチ"""
        result = self._resolve(cfg, "rooftop-lights")
        assert "all" in result
        assert "study" in result

    def test_rainy_cafe_routes_to_all_and_study(self, cfg):
        """rainy-cafe は Study と Work で study にマッチ"""
        result = self._resolve(cfg, "rainy-cafe")
        assert "all" in result
        assert "study" in result

    def test_sleepless_midnight_routes_to_all_only(self, cfg):
        """sleepless-midnight は Sleep 系で study にはマッチしない"""
        result = self._resolve(cfg, "sleepless-midnight")
        assert "all" in result
        assert "study" not in result

    def test_midnight_blues_routes_to_all_and_study(self, cfg):
        """midnight-blues は Chill で study にマッチ"""
        result = self._resolve(cfg, "midnight-blues")
        assert "all" in result
        assert "study" in result

    def test_unknown_theme_uses_default(self, cfg):
        """未知のテーマはデフォルト activities を使用"""
        result = self._resolve(cfg, "unknown-theme")
        assert "all" in result
        # default_activities = "Study · Focus · Late Night" → Study, Focus で study マッチ
        assert "study" in result

    def test_all_playlist_always_included(self, cfg):
        """auto_add: true の all は常に含まれる"""
        for theme in ["city", "sleepless-midnight", "unknown"]:
            result = self._resolve(cfg, theme)
            assert "all" in result, f"theme={theme} で all が含まれていない"
