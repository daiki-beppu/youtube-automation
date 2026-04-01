"""
ChannelConfig シングルトンクラスのテスト
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.channel_config import ChannelConfig

# ─── テスト用設定データ ──────────────────────────────

SAMPLE_CONFIG = {
    "channel": {
        "name": "Test Channel",
        "short": "TC",
        "youtube_handle": "@testchannel",
        "url": "https://youtube.com/@testchannel",
        "core_message": "Test core message",
        "cta_subscribe": "Subscribe now!",
        "tagline": "Test tagline",
    },
    "genre": {
        "primary": "Test Music",
        "style": "ambient",
        "context": "relaxation",
    },
    "youtube": {
        "category_id": "10",
        "privacy_status": "public",
        "language": "en",
    },
    "tags": {
        "base": ["test", "music", "ambient"],
        "themes": {
            "forest": ["forest", "nature"],
            "battle": ["battle", "epic"],
        },
    },
    "descriptions": {
        "opening": "{style} {primary} for {context}",
        "sub_opening": "Sub opening text",
        "perfect_for": ["studying", "sleeping"],
        "hashtags": ["#test", "#music"],
    },
    "analytics": {
        "collection_filter_keywords": ["collection", "complete"],
    },
    "audio": {
        "crossfade_duration": 2.5,
    },
    "suno": {
        "workspace_name": "Test Workspace",
        "genre_line": "ambient, chill",
        "exclude_styles": "rock, metal",
    },
    "title": {
        "template": "{name} | {activity}",
        "default_activity": "Study",
        "theme_activities": {
            "battle": "Gaming",
            "forest": "Relaxation",
        },
    },
    "benchmark": {
        "channels": [{"name": "Rival", "id": "UC123"}],
    },
    "playlists": {
        "main": "PLtest123",
    },
}


# ─── Fixtures ────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """各テスト前後でシングルトンをリセット"""
    ChannelConfig.reset()
    yield
    ChannelConfig.reset()


@pytest.fixture
def config_file(tmp_path):
    """一時ディレクトリに channel_config.json を作成"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "channel_config.json"
    config_path.write_text(json.dumps(SAMPLE_CONFIG), encoding="utf-8")
    return config_path


@pytest.fixture
def channel_dir_with_config(tmp_path):
    """config/channel_config.json を持つチャンネルディレクトリ"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "channel_config.json").write_text(
        json.dumps(SAMPLE_CONFIG), encoding="utf-8"
    )
    return tmp_path


# ─── Singleton behavior ─────────────────────────────

class TestSingletonBehavior:
    def test_load_returns_same_instance(self, config_file):
        inst1 = ChannelConfig.load(config_path=str(config_file))
        inst2 = ChannelConfig.load(config_path=str(config_file))
        assert inst1 is inst2

    def test_reset_clears_singleton(self, config_file):
        inst1 = ChannelConfig.load(config_path=str(config_file))
        ChannelConfig.reset()
        inst2 = ChannelConfig.load(config_path=str(config_file))
        assert inst1 is not inst2

    def test_constructor_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="ChannelConfig.load"):
            ChannelConfig()


# ─── Channel directory resolution ───────────────────

class TestChannelDirResolution:
    def test_channel_dir_caches_result(self, monkeypatch, channel_dir_with_config):
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir_with_config))
        dir1 = ChannelConfig.channel_dir()
        dir2 = ChannelConfig.channel_dir()
        assert dir1 == dir2

    def test_resolve_with_env_var(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
        result = ChannelConfig._resolve_channel_dir()
        assert result == tmp_path

    def test_resolve_with_cwd(self, monkeypatch, channel_dir_with_config):
        monkeypatch.delenv("CHANNEL_DIR", raising=False)
        monkeypatch.chdir(channel_dir_with_config)
        result = ChannelConfig._resolve_channel_dir()
        assert result == channel_dir_with_config

    def test_resolve_with_cwd_subdirectory(self, monkeypatch, channel_dir_with_config):
        """CWD がチャンネルディレクトリの子ディレクトリの場合でも解決できる"""
        monkeypatch.delenv("CHANNEL_DIR", raising=False)
        sub = channel_dir_with_config / "collections" / "planning"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        result = ChannelConfig._resolve_channel_dir()
        assert result == channel_dir_with_config

    def test_resolve_raises_when_no_config(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CHANNEL_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        from utils.exceptions import ConfigError
        with pytest.raises(ConfigError):
            ChannelConfig._resolve_channel_dir()


# ─── Properties ──────────────────────────────────────

class TestProperties:
    @pytest.fixture(autouse=True)
    def _load_config(self, config_file):
        self.cfg = ChannelConfig.load(config_path=str(config_file))

    def test_channel_name(self):
        assert self.cfg.channel_name == "Test Channel"

    def test_channel_short(self):
        assert self.cfg.channel_short == "TC"

    def test_base_tags(self):
        assert self.cfg.base_tags == ["test", "music", "ambient"]

    def test_base_tags_returns_copy(self):
        tags1 = self.cfg.base_tags
        tags1.append("extra")
        assert "extra" not in self.cfg.base_tags

    def test_raw_returns_full_dict(self):
        assert self.cfg.raw == SAMPLE_CONFIG

    def test_genre_style(self):
        assert self.cfg.genre_style == "ambient"

    def test_description_opening_formatted(self):
        assert self.cfg.description_opening == "Ambient Test Music for relaxation"

    def test_hashtag_line(self):
        assert self.cfg.hashtag_line == "#test #music"

    def test_crossfade_duration(self):
        assert self.cfg.crossfade_duration == 2.5

    def test_default_tags_includes_channel_name(self):
        tags = self.cfg.default_tags
        assert "test channel" in tags

    def test_get_tags_for_collection(self):
        tags = self.cfg.get_tags_for_collection("Dark Forest Adventure")
        assert "forest" in tags
        assert "nature" in tags

    def test_get_tags_for_collection_max_50(self):
        tags = self.cfg.get_tags_for_collection("forest")
        assert len(tags) <= 50

    def test_get_activity_for_theme_match(self):
        assert self.cfg.get_activity_for_theme("Battle Arena") == "Gaming"

    def test_get_activity_for_theme_default(self):
        assert self.cfg.get_activity_for_theme("Unknown") == "Study"


# ─── Config loading ─────────────────────────────────

class TestConfigLoading:
    def test_load_reads_json(self, config_file):
        cfg = ChannelConfig.load(config_path=str(config_file))
        assert cfg.channel_name == "Test Channel"

    def test_load_with_explicit_path(self, tmp_path):
        custom = tmp_path / "custom_config.json"
        custom.write_text(json.dumps(SAMPLE_CONFIG), encoding="utf-8")
        cfg = ChannelConfig.load(config_path=str(custom))
        assert cfg.channel_name == "Test Channel"

    def test_load_with_channel_dir_env(self, monkeypatch, channel_dir_with_config):
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir_with_config))
        cfg = ChannelConfig.load()
        assert cfg.channel_name == "Test Channel"

    def test_load_calls_dotenv(self, monkeypatch, config_file):
        """load() が dotenv を呼び出すことを確認（エラーなく完了すればOK）"""
        cfg = ChannelConfig.load(config_path=str(config_file))
        assert cfg is not None

    def test_crossfade_duration_default(self, tmp_path):
        """audio セクションがない場合のデフォルト値"""
        data = dict(SAMPLE_CONFIG)
        data = json.loads(json.dumps(SAMPLE_CONFIG))
        del data["audio"]
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(data), encoding="utf-8")
        cfg = ChannelConfig.load(config_path=str(config_path))
        assert cfg.crossfade_duration == 1.0
