"""新 config API (utils.config) の単体テスト.

tmp_path ベースの自前 fixture を使い、tests/fixtures/sample_channel/ には依存しない。
sample_channel の新構造化は S3（コミット 3）で実施する予定。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.utils.config import (
    ChannelConfig,
    channel_dir,
    load_config,
    reset,
)
from youtube_automation.utils.exceptions import ConfigError

# ----- helpers -------------------------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _minimal_sections() -> dict[str, dict]:
    """meta / content / youtube の最小必須構成."""
    return {
        "meta.json": {
            "channel": {
                "name": "Test Channel",
                "short": "TC",
                "youtube_handle": "@testchannel",
                "url": "https://youtube.com/@testchannel",
                "tagline": "Test tagline",
            }
        },
        "content.json": {
            "genre": {"primary": "chiptune", "style": "8-bit", "context": "RPG"},
            "tags": {
                "base": ["chiptune music", "8-bit"],
                "themes": {
                    "battle": ["battle music", "boss battle"],
                    "village": ["village music"],
                },
            },
            "descriptions": {
                "opening": "{style} {primary} for {context}",
                "perfect_for": ["Studying", "Gaming"],
                "hashtags": ["#ChiptuneMusic"],
            },
            "title": {"template": "{theme} - {activity}"},
        },
        "youtube.json": {
            "youtube": {
                "category_id": "10",
                "privacy_status": "public",
                "language": "ja",
            }
        },
    }


def _setup_channel(
    tmp_path: Path,
    sections: dict[str, dict],
    *,
    localizations: dict | None = None,
) -> Path:
    ch = tmp_path / "channel"
    for filename, data in sections.items():
        _write_json(ch / "config" / "channel" / filename, data)
    if localizations is not None:
        _write_json(ch / "config" / "localizations.json", localizations)
    return ch


@pytest.fixture(autouse=True)
def _auto_reset(monkeypatch):
    """新 API のシングルトン state をテスト毎にリセットし、CHANNEL_DIR も初期化する.

    conftest.py の session-scope `set_channel_dir` fixture が sample_channel を
    指している前提を剥がし、各テストが tmp_path で独立できるようにする。
    """
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    reset()
    yield
    reset()


# ----- tests ---------------------------------------------------------------


def test_load_minimal_sections(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert isinstance(config, ChannelConfig)
    assert config.meta.channel_name == "Test Channel"
    assert config.meta.channel_short == "TC"
    assert config.meta.youtube_handle == "@testchannel"
    assert config.meta.channel_url == "https://youtube.com/@testchannel"
    assert config.meta.tagline == "Test tagline"
    assert config.content.genre.primary == "chiptune"
    assert config.content.tags.base == ["chiptune music", "8-bit"]
    assert config.youtube.api.language == "ja"
    assert config.youtube.music_engine == "suno"  # default
    assert config.youtube.content_model.type == "release"  # default
    assert config.youtube.content_model.languages == ["ja"]  # fallback to api.language
    assert config.localizations.exists is False
    assert config.localizations.supported_languages == ["ja"]
    assert config.audio.target_duration_min is None
    assert config.playlists.items == {}
    assert config.workflow.post_upload.short_publish_time == "08:00"


def test_load_all_sections(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["analytics.json"] = {
        "analytics": {"collection_filter_keywords": ["collection", "complete"]},
        "benchmark": {"channels": [{"name": "Rival", "id": "UC123"}]},
    }
    sections["playlists.json"] = {"playlists": {"main": "PLtest123"}}
    sections["workflow.json"] = {
        "workflow": {},
        "post_upload": {"short_publish_time": "09:30"},
        "short": {"foo": "bar"},
    }
    sections["audio.json"] = {"audio": {"target_duration_min": 120.0}}
    sections["meta.json"]["youtube_channel"] = {
        "description": "ch desc",
        "keywords": ["tag1"],
        "country": "JP",
        "default_language": "ja",
    }
    sections["youtube.json"]["content_model"] = {"type": "collection", "languages": ["ja"]}
    sections["youtube.json"]["music_engine"] = "lyria"

    localizations = {
        "supported_languages": ["ja", "en"],
        "default_language": "ja",
        "languages": {"ja": {"title_template": "x"}},
    }
    ch = _setup_channel(tmp_path, sections, localizations=localizations)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.analytics.collection_filter_keywords == ["collection", "complete"]
    assert config.analytics.benchmark.channels == [{"name": "Rival", "id": "UC123"}]
    assert config.playlists.items == {"main": "PLtest123"}
    assert config.workflow.post_upload.short_publish_time == "09:30"
    assert config.workflow.short.raw == {"foo": "bar"}
    assert config.audio.target_duration_min == 120.0
    assert config.meta.branding.description == "ch desc"
    assert config.youtube.content_model.type == "collection"
    assert config.youtube.content_model.languages == ["ja"]
    assert config.youtube.music_engine == "lyria"
    assert config.localizations.exists is True
    assert config.localizations.supported_languages == ["ja", "en"]
    assert config.localizations.default_language == "ja"


def test_missing_required_key(tmp_path, monkeypatch):
    sections = _minimal_sections()
    del sections["meta.json"]["channel"]["name"]
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="channel.name"):
        load_config()


def test_duplicate_top_level_key(tmp_path, monkeypatch):
    sections = _minimal_sections()
    # youtube キーが meta.json にも侵入している
    sections["meta.json"]["youtube"] = {"category_id": "20"}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="トップレベルキー 'youtube'"):
        load_config()


def test_no_section_files(tmp_path, monkeypatch):
    ch = tmp_path / "channel"
    (ch / "config" / "channel").mkdir(parents=True)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="JSON ファイルが 1 つもありません"):
        load_config()


def test_legacy_config_detection(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())
    _write_json(ch / "config" / "channel_config.json", {"legacy": True})
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="旧 channel_config.json が残っています"):
        load_config()


def test_cross_file_content_model_languages_subset(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["youtube.json"]["content_model"] = {"type": "collection", "languages": ["en"]}
    localizations = {"supported_languages": ["ja", "ko"], "languages": {}}
    ch = _setup_channel(tmp_path, sections, localizations=localizations)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="supported_languages"):
        load_config()


def test_cross_file_theme_scenes_subset(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["content.json"]["title"]["theme_scenes"] = {
        "unknown_theme": {"activities": "Study"},
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="theme_scenes"):
        load_config()


def test_optional_sections_default(tmp_path, monkeypatch):
    # 最小 3 ファイルのみ（analytics / playlists / workflow / audio なし）
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.analytics.collection_filter_keywords == []
    assert config.analytics.benchmark.channels == []
    assert config.playlists.items == {}
    assert config.workflow.post_upload.short_publish_time == "08:00"
    assert config.workflow.short.raw == {}
    assert config.audio.target_duration_min is None


def test_localizations_missing(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())  # localizations.json なし
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.localizations.exists is False
    assert config.localizations.data == {}
    assert config.localizations.supported_languages == [config.youtube.api.language]
    assert config.localizations.default_language == ""


def test_tags_default_includes_channel_name(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()
    tags = config.content.tags.default()

    assert tags == ["chiptune music", "8-bit", "test channel"]


def test_tags_for_collection_matches_theme(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["content.json"]["tags"]["channel_specific"] = ["ch-tag"]
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()
    tags = config.content.tags.for_collection("Epic Battle BGM")

    assert "ch-tag" in tags
    assert "battle music" in tags  # theme にマッチ
    assert "boss battle" in tags
    assert "village music" not in tags  # 別テーマ
    assert "test channel" in tags  # default tags に channel_name.lower() が入る
    assert len(tags) <= 50


def test_title_activity_for_theme_fallback(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["content.json"]["title"]["default_activity"] = "Chill"
    sections["content.json"]["title"]["theme_activities"] = {"battle": "Gaming"}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.content.title.activity_for_theme("Epic Battle Scene") == "Gaming"
    assert config.content.title.activity_for_theme("Ocean Waves") == "Chill"


def test_descriptions_render_opening(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()
    rendered = config.content.descriptions.render_opening()

    # "{style} {primary} for {context}" + style.title() → "8-Bit chiptune for RPG"
    assert rendered == "8-Bit chiptune for RPG"


def test_branding_as_api_dict(tmp_path, monkeypatch):
    # 1) youtube_channel なし → as_api_dict() は空 dict
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))
    config = load_config()
    assert config.meta.branding.as_api_dict() == {}

    # 2) youtube_channel に値あり
    reset()
    sections = _minimal_sections()
    sections["meta.json"]["youtube_channel"] = {
        "description": "desc",
        "keywords": ["a", "b"],
        "made_for_kids": False,
    }
    ch2 = _setup_channel(tmp_path / "v2", sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch2))
    config2 = load_config()
    api_dict = config2.meta.branding.as_api_dict()
    assert api_dict == {
        "description": "desc",
        "keywords": ["a", "b"],
        "made_for_kids": False,
    }


def test_singleton(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    first = load_config()
    second = load_config()
    assert first is second

    # ファイルを変更してもキャッシュが残っている
    sections = _minimal_sections()
    sections["meta.json"]["channel"]["name"] = "Changed"
    _write_json(ch / "config" / "channel" / "meta.json", sections["meta.json"])
    assert load_config() is first

    reset()
    third = load_config()
    assert third is not first
    assert third.meta.channel_name == "Changed"


def test_channel_dir_from_env(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    assert channel_dir() == ch


def test_channel_dir_ancestor_search(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())
    sub = ch / "collections" / "foo"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    monkeypatch.delenv("CHANNEL_DIR", raising=False)

    assert channel_dir().resolve() == ch.resolve()
