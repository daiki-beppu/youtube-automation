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
    # comments は optional セクション、欠如時は enabled=False のデフォルト
    assert config.comments.enabled is False
    assert config.comments.rules == []
    assert config.comments.generator.provider == "codex"
    assert config.comments.max_replies_per_run == 20
    # pinned_comment も optional、欠如時は enabled=False のデフォルト
    assert config.pinned_comment.enabled is False
    assert config.pinned_comment.templates == {}
    assert config.pinned_comment.history_file == "pinned_comment_history.json"
    assert config.pinned_comment.default_language == "en"


def test_synthetic_media_flags_default(tmp_path, monkeypatch):
    """#605: youtube.json 未設定時は現行の振る舞い（synthetic=True / made_for_kids=False）。"""
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.youtube.api.contains_synthetic_media is True
    assert config.youtube.api.self_declared_made_for_kids is False


def test_synthetic_media_flags_override(tmp_path, monkeypatch):
    """#605: youtube.json で AI 開示 / 子供向け申告を上書きできる。"""
    sections = _minimal_sections()
    sections["youtube.json"]["youtube"]["contains_synthetic_media"] = False
    sections["youtube.json"]["youtube"]["self_declared_made_for_kids"] = True
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.youtube.api.contains_synthetic_media is False
    assert config.youtube.api.self_declared_made_for_kids is True


def test_load_pinned_comment_section(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["pinned-comment.json"] = {
        "pinned_comment": {
            "enabled": True,
            "history_file": "pins.json",
            "delay_between_posts_sec": 1.5,
            "default_language": "ja",
            "templates": {"ja": "{scene_phrase} {scene_emoji}", "en": "{scene_phrase}"},
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.pinned_comment.enabled is True
    assert config.pinned_comment.history_file == "pins.json"
    assert config.pinned_comment.delay_between_posts_sec == 1.5
    assert config.pinned_comment.default_language == "ja"
    assert config.pinned_comment.templates["ja"] == "{scene_phrase} {scene_emoji}"


def test_pinned_comment_templates_must_be_object(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["pinned-comment.json"] = {"pinned_comment": {"templates": ["not", "an", "object"]}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="pinned_comment.templates"):
        load_config()


def test_load_all_sections(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["analytics.json"] = {
        "analytics": {"collection_filter_keywords": ["collection", "complete"]},
        "benchmark": {"channels": [{"name": "Rival", "id": "UC123"}]},
    }
    sections["playlists.json"] = {"playlists": {"main": "PLtest123"}}
    # `config/channel/shorts.json` がチャンネル運用設定を保持する。
    # ChannelConfig.shorts に正しく組み立てられるかを positive assert で守る。
    sections["shorts.json"] = {
        "shorts": {
            "enabled": True,
            "publish_time": "09:30",
            "min_hours_between_shorts_per_collection": 12,
            "mode": "collection",
            "collection": {"default_count": 5, "chapter_offset_sec": 45},
            "release": {"languages": ["jp"], "start_sec": 20, "duration_sec": 30},
        }
    }
    sections["audio.json"] = {"audio": {"target_duration_min": 120.0}}
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "max_replies_per_run": 5,
            "delay_between_replies_sec": 1.0,
            "rules": [
                {
                    "name": "greet_ja",
                    "keywords": ["こんにちは"],
                    "language": "ja",
                    "priority": 10,
                    "provider": "gemini",
                }
            ],
            "generator": {
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "fallback_on_error": "retry",
            },
            "ng_words": ["spam"],
        }
    }
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
    assert config.playlists.items == {"main": {"playlist_id": "PLtest123", "auto_add": True, "title": None}}
    assert config.audio.target_duration_min == 120.0
    assert config.meta.branding.description == "ch desc"
    assert config.youtube.content_model.type == "collection"
    assert config.youtube.content_model.languages == ["ja"]
    assert config.youtube.music_engine == "lyria"
    assert config.localizations.exists is True
    assert config.localizations.supported_languages == ["ja", "en"]
    assert config.localizations.default_language == "ja"
    assert config.comments.enabled is True
    assert config.comments.max_replies_per_run == 5
    assert config.comments.delay_between_replies_sec == 1.0
    assert len(config.comments.rules) == 1
    assert config.comments.rules[0].name == "greet_ja"
    assert config.comments.rules[0].keywords == ["こんにちは"]
    assert config.comments.rules[0].provider == "gemini"
    assert config.comments.generator.provider == "gemini"
    assert config.comments.generator.fallback_on_error == "retry"
    assert config.comments.ng_words == ["spam"]
    # shorts セクションが全フィールド組み立てられている
    assert config.shorts.enabled is True
    assert config.shorts.publish_time == "09:30"
    assert config.shorts.min_hours_between_shorts_per_collection == 12
    assert config.shorts.mode == "collection"
    assert config.shorts.collection.default_count == 5
    assert config.shorts.collection.chapter_offset_sec == 45
    assert config.shorts.release.languages == ("jp",)
    assert config.shorts.release.start_sec == 20
    assert config.shorts.release.duration_sec == 30


def test_shorts_section_missing_defaults_to_disabled(tmp_path, monkeypatch):
    """shorts.json を 1 ファイルも置かない場合、enabled=False（オプトイン）で全 default が返る."""
    ch = _setup_channel(tmp_path, _minimal_sections())  # shorts.json なし
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.shorts.enabled is False
    assert config.shorts.publish_time == "08:00"
    assert config.shorts.min_hours_between_shorts_per_collection == 24
    assert config.shorts.mode == "auto"
    assert config.shorts.collection.default_count == 3
    assert config.shorts.release.languages == ("jp", "en")


def test_shorts_section_empty_uses_defaults(tmp_path, monkeypatch):
    """`shorts.json` に `shorts: {}` のみのとき、すべて default で返る."""
    sections = _minimal_sections()
    sections["shorts.json"] = {"shorts": {}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.shorts.enabled is False
    assert config.shorts.publish_time == "08:00"


def test_workflow_legacy_post_upload_silently_ignored(tmp_path, monkeypatch):
    """旧 `workflow.post_upload.short_publish_time` キーは silently ignore.

    v5.5 から Shorts スケジュール公開時刻は `config.shorts.publish_time` に移動した。
    downstream の `workflow.json` に旧キーが残っていても ConfigError を投げず、
    新構造 `shorts` の default `"08:00"` が採用される。
    """
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {"post_upload": {"short_publish_time": "09:30"}},
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    # 旧 workflow.post_upload キーは無視され、shorts.publish_time の default "08:00" が採用される
    assert config.shorts.publish_time == "08:00"


def test_comments_rule_name_required(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [{"keywords": ["hi"]}],  # name 未指定
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.rules\\[0\\].name"):
        load_config()


def test_comments_templates_must_be_object(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["comments.json"] = {"comments": {"templates": ["not", "an", "object"]}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.templates"):
        load_config()


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


# ----- boundary-validation: playlists top-level shape ---------------------


def test_playlists_list_shape_raises_config_error(tmp_path, monkeypatch):
    """playlists セクションが [] のとき ConfigError を投げる（truthy な空 list を黙認しない）."""
    sections = _minimal_sections()
    sections["playlists.json"] = {"playlists": []}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="playlists セクションは object でなければなりません"):
        load_config()


def test_playlists_list_with_items_raises_config_error(tmp_path, monkeypatch):
    """playlists セクションが [1] のとき AttributeError ではなく ConfigError を投げる."""
    sections = _minimal_sections()
    sections["playlists.json"] = {"playlists": [1]}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="playlists セクションは object でなければなりません"):
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
    assert config.audio.target_duration_min is None
    # chapter_max のデフォルト = 100（YouTube 実用上限近く、per-track 14〜28 を許容）
    assert config.audio.chapter_max == 100


def test_audio_chapter_max_override(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["audio.json"] = {"audio": {"chapter_max": 50}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.audio.chapter_max == 50


def test_playlists_string_value_normalized_to_dict(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["playlists.json"] = {"playlists": {"main": "PL_X"}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.playlists.items == {"main": {"playlist_id": "PL_X", "auto_add": True, "title": None}}


def test_playlists_dict_value_preserved_as_is(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["playlists.json"] = {
        "playlists": {
            "battle": {
                "playlist_id": "PL_B",
                "title": "Battle Music",
                "auto_add_themes": ["fight"],
            }
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    entry = config.playlists.items["battle"]
    assert entry["playlist_id"] == "PL_B"
    assert entry["title"] == "Battle Music"
    assert entry["auto_add_themes"] == ["fight"]


def test_playlists_mixed_string_and_dict_entries(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["playlists.json"] = {
        "playlists": {
            "main": "PL_MAIN",
            "battle": {
                "playlist_id": "PL_B",
                "title": "Battle Music",
                "auto_add_themes": ["fight"],
            },
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.playlists.items["main"] == {
        "playlist_id": "PL_MAIN",
        "auto_add": True,
        "title": None,
    }
    assert config.playlists.items["battle"]["playlist_id"] == "PL_B"
    assert config.playlists.items["battle"]["auto_add_themes"] == ["fight"]


def test_playlists_dict_entry_is_shallow_copied():
    from youtube_automation.utils.config.loader import _build_playlists

    raw_entry = {"playlist_id": "PL_B", "auto_add_themes": ["fight"]}
    merged = {"playlists": {"battle": raw_entry}}

    playlists = _build_playlists(merged)

    assert playlists.items["battle"] is not raw_entry
    assert playlists.items["battle"] == raw_entry


def test_playlists_invalid_shape_raises_config_error():
    from youtube_automation.utils.config.loader import _build_playlists
    from youtube_automation.utils.exceptions import ConfigError

    merged = {"playlists": {"main": 42}}

    with pytest.raises(ConfigError, match="playlists.main"):
        _build_playlists(merged)


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


def test_title_activity_for_theme_scenes_exact_match_preferred(tmp_path, monkeypatch):
    """#80 回帰: 短いキーが先に登録されていても完全一致が優先される."""
    sections = _minimal_sections()
    sections["content.json"]["tags"]["themes"] = {
        "cafe": ["cafe music"],
        "campus-cafe": ["campus cafe music"],
    }
    sections["content.json"]["title"]["default_activity"] = "Study"
    sections["content.json"]["title"]["theme_scenes"] = {
        "cafe": {"scene": "Cafe", "activities": "Study · Work · Reading"},
        "campus-cafe": {"scene": "Campus Cafe", "activities": "Study · Work · Late Night"},
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    # exact match は dict 挿入順に関係なく優先される
    assert config.content.title.activity_for_theme("campus-cafe") == "Study · Work · Late Night"
    # substring だけの時は longest-match: campus-cafe が cafe より先に match する
    assert config.content.title.activity_for_theme("nice-campus-cafe-mix") == "Study · Work · Late Night"
    # 短いキーのみマッチするテーマは従来どおり cafe を拾う
    assert config.content.title.activity_for_theme("after-midnight-cafe") == "Study · Work · Reading"


def test_title_activity_for_theme_activities_exact_match_preferred(tmp_path, monkeypatch):
    """#80 回帰: レガシー theme_activities 経路でも exact match が優先される."""
    sections = _minimal_sections()
    sections["content.json"]["title"]["default_activity"] = "Study"
    sections["content.json"]["title"]["theme_activities"] = {
        "cafe": "Study · Work · Reading",
        "campus-cafe": "Study · Work · Late Night",
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.content.title.activity_for_theme("campus-cafe") == "Study · Work · Late Night"
    assert config.content.title.activity_for_theme("nice-campus-cafe-mix") == "Study · Work · Late Night"
    assert config.content.title.activity_for_theme("after-midnight-cafe") == "Study · Work · Reading"


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


# ----- comments.generator section -------------------------------------------


def _comments_with_generator(generator_raw: dict) -> dict:
    return {
        "comments": {
            "enabled": True,
            "rules": [
                {
                    "name": "catch_all",
                    "pattern": ".+",
                    "priority": 0,
                    "provider": "gemini",
                }
            ],
            "generator": generator_raw,
        }
    }


def test_comments_generator_gemini_loads_correctly(tmp_path, monkeypatch):
    """comments.generator.provider='gemini' の全フィールドが GeneratorConfig に正しく組み立てられる."""
    sections = _minimal_sections()
    sections["comments.json"] = _comments_with_generator(
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "channel_persona": "Warm lo-fi jazz host",
            "max_length": 300,
            "fallback_on_error": "skip",
            "requests_per_minute": 10,
        }
    )
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    gen = config.comments.generator
    assert gen is not None
    assert gen.provider == "gemini"
    assert gen.model == "gemini-2.5-flash"
    assert gen.channel_persona == "Warm lo-fi jazz host"
    assert gen.max_length == 300
    assert gen.fallback_on_error == "skip"
    assert gen.requests_per_minute == 10


def test_comments_generator_codex_provider_loads_correctly(tmp_path, monkeypatch):
    """comments.generator.provider='codex' は model=None でも有効."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [],
            "generator": {"provider": "codex"},
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    gen = config.comments.generator
    assert gen is not None
    assert gen.provider == "codex"
    assert gen.model is None
    assert gen.fallback_on_error == "skip"  # default
    assert gen.max_length == 280  # default
    assert gen.requests_per_minute == 30  # default


def test_comments_generator_absent_defaults_to_codex(tmp_path, monkeypatch):
    """comments.generator セクションが省略されたとき codex provider になる."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.generator.provider == "codex"
    assert config.comments.generator.fallback_on_error == "skip"


def test_comments_generator_invalid_provider_raises(tmp_path, monkeypatch):
    """comments.generator.provider が無効な値のとき ConfigError を送出する."""
    sections = _minimal_sections()
    sections["comments.json"] = _comments_with_generator({"provider": "openai"})
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.generator.provider"):
        load_config()


def test_comments_generator_provider_missing_defaults_to_codex(tmp_path, monkeypatch):
    """comments.generator.provider が省略されたとき codex provider になる."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [{"name": "catch_all", "pattern": ".+"}],
            "generator": {"max_length": 120},
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.generator.provider == "codex"
    assert config.comments.generator.max_length == 120


def test_comments_generator_gemini_without_model_raises(tmp_path, monkeypatch):
    """comments.generator.provider='gemini' で model が省略されたとき ConfigError を送出する."""
    sections = _minimal_sections()
    sections["comments.json"] = _comments_with_generator({"provider": "gemini"})
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="model は必須"):
        load_config()


def test_comments_generator_invalid_fallback_raises(tmp_path, monkeypatch):
    """comments.generator.fallback_on_error が無効な値のとき ConfigError を送出する."""
    sections = _minimal_sections()
    sections["comments.json"] = _comments_with_generator(
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "fallback_on_error": "template",
        }
    )
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="fallback_on_error"):
        load_config()


def test_comments_generator_not_object_raises(tmp_path, monkeypatch):
    """comments.generator が object でないとき ConfigError を送出する."""
    sections = _minimal_sections()
    sections["comments.json"] = {"comments": {"generator": "gemini"}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.generator は object"):
        load_config()


def test_comments_rule_invalid_provider_raises(tmp_path, monkeypatch):
    """comments.rules[i].provider が無効な値のとき ConfigError を送出する."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [
                {
                    "name": "bad_rule",
                    "keywords": ["hi"],
                    "provider": "openai",
                }
            ],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.rules\\[0\\].provider"):
        load_config()


def test_comments_rule_gemini_without_generator_section_loads(tmp_path, monkeypatch):
    """rule provider='gemini' は rule 単位の override として有効."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [
                {
                    "name": "ai_rule",
                    "pattern": ".+",
                    "provider": "gemini",
                }
            ],
            "generator": {"provider": "codex"},
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.generator.provider == "codex"
    assert config.comments.rules[0].provider == "gemini"


def test_comments_dataclass_defaults_to_codex_without_loader():
    """Comments dataclass を直接構築した場合でも codex 既定になる."""
    from youtube_automation.utils.config.comments import CommentRule, Comments

    comments = Comments(enabled=True, rules=[CommentRule(name="ok", keywords=["hi"], provider="gemini")])

    assert comments.generator.provider == "codex"
    assert comments.rules[0].provider == "gemini"


def test_comments_dataclass_rejects_invalid_rule_provider():
    """Comments dataclass を直接構築した場合も rule provider を検証する."""
    from youtube_automation.utils.config.comments import (
        CommentRule,
        Comments,
    )

    with pytest.raises(ConfigError, match="provider"):
        Comments(
            enabled=True,
            rules=[CommentRule(name="bad", keywords=["hi"], provider="openai")],
        )


def test_comments_legacy_type_key_raises(tmp_path, monkeypatch):
    """旧 comments.generator.type は互換変換せず ConfigError にする."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "generator": {"type": "template"},
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.generator.type"):
        load_config()


def test_comments_legacy_templates_key_raises(tmp_path, monkeypatch):
    """旧 comments.templates は互換変換せず ConfigError にする."""
    sections = _minimal_sections()
    sections["comments.json"] = {"comments": {"templates": {"ja": {"default": "hello"}}}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.templates"):
        load_config()


def test_comments_legacy_template_key_raises(tmp_path, monkeypatch):
    """旧 comments.rules[].template_key は互換変換せず ConfigError にする."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "rules": [{"name": "legacy", "keywords": ["hi"], "template_key": "default"}],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.rules\\[0\\].template_key"):
        load_config()


def test_comments_legacy_rule_generator_key_raises(tmp_path, monkeypatch):
    """旧 comments.rules[].generator は互換変換せず ConfigError にする."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "rules": [{"name": "legacy", "keywords": ["hi"], "generator": "gemini"}],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.rules\\[0\\].generator"):
        load_config()
