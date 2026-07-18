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


def test_default_publish_time_defaults_to_none(tmp_path, monkeypatch):
    sections = _minimal_sections()
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.youtube.api.default_publish_time is None
    assert config.youtube.api.default_publish_timezone == "Asia/Tokyo"


def test_default_publish_time_override(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["youtube.json"]["youtube"]["default_publish_time"] = "20:30"
    sections["youtube.json"]["youtube"]["default_publish_timezone"] = "Asia/Tokyo"
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.youtube.api.default_publish_time == "20:30"
    assert config.youtube.api.default_publish_timezone == "Asia/Tokyo"


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


def _full_distrokid_profile() -> dict:
    """#813 新 schema の distrokid.profile（実 DOM 検証に基づく再設計）.

    旧フラット 6 文字列（artist_name / apple_music_credit / track_type など）を撤廃し、
    songwriter を nested の {first,last,middle?} に、AI 開示を ai_disclosure に再設計した形。
    必須は language / main_genre のみ。sub_genre / songwriter / ai_disclosure は任意。
    """
    return {
        "artist": "ABYSS MI",
        "language": "ja",
        "main_genre": "Electronic",
        "sub_genre": "House",
        "songwriter": {"first": "Jane", "middle": "Q", "last": "Doe"},
        "ai_disclosure": {
            "enabled": True,
            "lyrics": True,
            "music": True,
            "recording_scope": "full",
            "partial_audio_type": None,
            "artist_persona": True,
            "apply_to_all": True,
        },
    }


def test_distrokid_section_missing_defaults_to_disabled(tmp_path, monkeypatch):
    """#813: distrokid.json を置かない場合、enabled=False（オプトイン）で profile は default。"""
    ch = _setup_channel(tmp_path, _minimal_sections())  # distrokid.json なし
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.distrokid.enabled is False
    assert config.distrokid.profile.artist == ""
    assert config.distrokid.profile.language == ""
    assert config.distrokid.profile.main_genre == ""
    assert config.distrokid.profile.sub_genre is None
    assert config.distrokid.profile.songwriter is None


def test_distrokid_profile_drops_legacy_flat_fields(tmp_path, monkeypatch):
    """#813: 旧フラットフィールドは schema から撤廃済み（属性として存在しない）。"""
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    profile = load_config().distrokid.profile

    assert not hasattr(profile, "artist_name")
    assert not hasattr(profile, "apple_music_credit")
    assert not hasattr(profile, "track_type")


def test_distrokid_profile_default_ai_disclosure(tmp_path, monkeypatch):
    """#877: ai_disclosure 省略時の default（はい + 歌詞/作曲 AI、full 録音、AI ペルソナ、apply-all）。"""
    from youtube_automation.utils.config.distrokid import AiDisclosure

    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    ai = load_config().distrokid.profile.ai_disclosure

    assert isinstance(ai, AiDisclosure)
    assert ai.enabled is True
    assert ai.lyrics is True
    assert ai.music is True
    assert ai.recording_scope == "full"
    assert ai.partial_audio_type is None
    assert ai.artist_persona is True
    assert ai.apply_to_all is True


def test_distrokid_section_empty_uses_defaults(tmp_path, monkeypatch):
    """#813: `distrokid: {}` のみのとき enabled=False の default。"""
    sections = _minimal_sections()
    sections["distrokid.json"] = {"distrokid": {}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.distrokid.enabled is False
    assert config.distrokid.profile.language == ""


def test_load_distrokid_section_enabled(tmp_path, monkeypatch):
    """#813: enabled=true + 新 schema の全 profile フィールドが nested dataclass まで届く。"""
    from youtube_automation.utils.config import Distrokid
    from youtube_automation.utils.config.distrokid import AiDisclosure, SongwriterName

    sections = _minimal_sections()
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": _full_distrokid_profile()}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()
    profile = config.distrokid.profile

    assert isinstance(config.distrokid, Distrokid)
    assert config.distrokid.enabled is True
    assert profile.artist == "ABYSS MI"
    assert profile.language == "ja"
    assert profile.main_genre == "Electronic"
    assert profile.sub_genre == "House"
    assert profile.songwriter == SongwriterName(first="Jane", middle="Q", last="Doe")
    assert profile.ai_disclosure == AiDisclosure(
        enabled=True,
        lyrics=True,
        music=True,
        recording_scope="full",
        partial_audio_type=None,
        artist_persona=True,
        apply_to_all=True,
    )


def test_distrokid_songwriter_without_middle(tmp_path, monkeypatch):
    """#813: songwriter.middle 省略時は None（任意フィールド）。"""
    sections = _minimal_sections()
    profile = _full_distrokid_profile()
    profile["songwriter"] = {"first": "Jane", "last": "Doe"}
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": profile}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    songwriter = load_config().distrokid.profile.songwriter

    assert songwriter.first == "Jane"
    assert songwriter.last == "Doe"
    assert songwriter.middle is None


def test_distrokid_enabled_minimal_required_only(tmp_path, monkeypatch):
    """#813: enabled=true は language / main_genre のみで成立（songwriter/ai_disclosure は任意）。"""
    sections = _minimal_sections()
    sections["distrokid.json"] = {
        "distrokid": {"enabled": True, "profile": {"language": "ja", "main_genre": "Electronic"}}
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    profile = load_config().distrokid.profile

    assert profile.language == "ja"
    assert profile.main_genre == "Electronic"
    assert profile.artist == ""
    assert profile.songwriter is None
    assert profile.sub_genre is None


@pytest.mark.parametrize("artist", [None, {"name": "ABYSS MI"}, ["ABYSS MI"]])
def test_distrokid_artist_non_string_raises(tmp_path, monkeypatch, artist):
    """distrokid.profile.artist は存在するなら string 必須。"""
    sections = _minimal_sections()
    profile = _full_distrokid_profile()
    profile["artist"] = artist
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": profile}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="artist"):
        load_config()


@pytest.mark.parametrize("artist", [None, {"name": "ABYSS MI"}, ["ABYSS MI"]])
def test_distrokid_disabled_artist_non_string_raises(tmp_path, monkeypatch, artist):
    """enabled=false でも現行 artist キーが存在するなら string 必須。"""
    sections = _minimal_sections()
    sections["distrokid.json"] = {"distrokid": {"enabled": False, "profile": {"artist": artist}}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="artist"):
        load_config()


def test_distrokid_enabled_without_profile_raises(tmp_path, monkeypatch):
    """#813: enabled=true で profile セクション欠落は ConfigError（条件付き必須）。"""
    sections = _minimal_sections()
    sections["distrokid.json"] = {"distrokid": {"enabled": True}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="distrokid"):
        load_config()


def test_distrokid_enabled_missing_language_raises(tmp_path, monkeypatch):
    """#813: enabled=true で language 欠落は ConfigError。"""
    sections = _minimal_sections()
    profile = _full_distrokid_profile()
    del profile["language"]
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": profile}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="language"):
        load_config()


def test_distrokid_enabled_missing_main_genre_raises(tmp_path, monkeypatch):
    """#813: enabled=true で main_genre 欠落は ConfigError。"""
    sections = _minimal_sections()
    profile = _full_distrokid_profile()
    del profile["main_genre"]
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": profile}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="main_genre"):
        load_config()


def test_distrokid_disabled_with_incomplete_profile_loads(tmp_path, monkeypatch):
    """#813: enabled=false なら profile が不完全でも条件付き検証は走らず load 成功。"""
    sections = _minimal_sections()
    sections["distrokid.json"] = {"distrokid": {"enabled": False, "profile": {"language": "ja"}}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.distrokid.enabled is False
    assert config.distrokid.profile.artist == ""
    assert config.distrokid.profile.language == "ja"


def test_distrokid_disabled_with_legacy_flat_profile_loads(tmp_path, monkeypatch):
    """enabled=false なら旧 flat profile の不要キーは無視して load できる。"""
    sections = _minimal_sections()
    sections["distrokid.json"] = {
        "distrokid": {
            "enabled": False,
            "profile": {
                "artist_name": "Legacy Artist",
                "language": "ja",
                "main_genre": "Electronic",
                "songwriter": "Jane Doe",
                "apple_music_credit": "Jane Doe",
                "track_type": "Instrumental",
            },
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.distrokid.enabled is False
    assert config.distrokid.profile.artist == ""
    assert config.distrokid.profile.language == "ja"
    assert config.distrokid.profile.main_genre == "Electronic"
    assert config.distrokid.profile.songwriter is None


def test_distrokid_ai_disclosure_partial_recording_scope(tmp_path, monkeypatch):
    """#877: recording_scope='partial' + partial_audio_type='vocals' が dataclass まで届く。"""
    from youtube_automation.utils.config.distrokid import AiDisclosure

    sections = _minimal_sections()
    profile = _full_distrokid_profile()
    profile["ai_disclosure"]["recording_scope"] = "partial"
    profile["ai_disclosure"]["partial_audio_type"] = "vocals"
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": profile}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    ai = load_config().distrokid.profile.ai_disclosure

    assert isinstance(ai, AiDisclosure)
    assert ai.recording_scope == "partial"
    assert ai.partial_audio_type == "vocals"


def test_distrokid_ai_disclosure_invalid_recording_scope_raises(tmp_path, monkeypatch):
    """#877: recording_scope が 'full'/'partial' 以外なら ConfigError。"""
    sections = _minimal_sections()
    profile = _full_distrokid_profile()
    profile["ai_disclosure"]["recording_scope"] = "all"
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": profile}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="recording_scope"):
        load_config()


def test_distrokid_ai_disclosure_invalid_partial_audio_type_raises(tmp_path, monkeypatch):
    """#877: partial_audio_type が 'vocals'/'instruments'/null 以外なら ConfigError。"""
    sections = _minimal_sections()
    profile = _full_distrokid_profile()
    profile["ai_disclosure"]["recording_scope"] = "partial"
    profile["ai_disclosure"]["partial_audio_type"] = "drums"
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": profile}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="partial_audio_type"):
        load_config()


def test_distrokid_ai_disclosure_partial_type_requires_partial_scope(tmp_path, monkeypatch):
    """#877: partial_audio_type は recording_scope='partial' 以外で指定すると ConfigError（クロスバリデーション）。"""
    sections = _minimal_sections()
    profile = _full_distrokid_profile()
    profile["ai_disclosure"]["recording_scope"] = "full"
    profile["ai_disclosure"]["partial_audio_type"] = "vocals"
    sections["distrokid.json"] = {"distrokid": {"enabled": True, "profile": profile}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="partial_audio_type"):
        load_config()


def test_distrokid_section_must_be_object(tmp_path, monkeypatch):
    """#813: distrokid セクションが object でないと ConfigError。"""
    sections = _minimal_sections()
    sections["distrokid.json"] = {"distrokid": ["not", "an", "object"]}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="distrokid"):
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
                "model": "gemini-3.5-flash",
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
    assert config.comments.rules == []
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


def test_workflow_wf_next_approval_gates_default(tmp_path, monkeypatch):
    """#508: `workflow.json` 未設定 or 空でも `approval_gates` は両方 `False`（全自動）.

    既存の `workflow.json = {"workflow": {}}` 運用や、`workflow.json` 自体が
    無いチャンネルでも、後方互換で従来通り全自動進行できることを保証する。
    """
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.approval_gates.audio is False
    assert config.workflow.wf_next.approval_gates.upload is False


def test_workflow_wf_next_approval_gates_explicit(tmp_path, monkeypatch):
    """#508: `workflow.wf_next.approval_gates.{audio,upload}` を明示できる."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "approval_gates": {"audio": True, "upload": True},
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.approval_gates.audio is True
    assert config.workflow.wf_next.approval_gates.upload is True


def test_workflow_wf_next_approval_gates_partial(tmp_path, monkeypatch):
    """#508: 片方のゲートだけ `true` も可。指定されないキーは default `False`."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "approval_gates": {"audio": True},
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.approval_gates.audio is True
    assert config.workflow.wf_next.approval_gates.upload is False


def test_workflow_wf_next_skip_approval_default(tmp_path, monkeypatch):
    """#1744: 未設定なら `skip_*_approval` は両方 `True`（従来既定 = 承認ゲートなし）."""
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.skip_audio_approval is True
    assert config.workflow.wf_next.skip_upload_approval is True
    assert config.workflow.wf_next.approval_gates.audio is False
    assert config.workflow.wf_next.approval_gates.upload is False


def test_workflow_wf_next_skip_approval_explicit(tmp_path, monkeypatch):
    """#1744: `skip_*_approval: false` で承認ゲートを有効化できる（true=省く の向き）."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "skip_audio_approval": False,
                "skip_upload_approval": False,
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.skip_audio_approval is False
    assert config.workflow.wf_next.skip_upload_approval is False
    # 互換ビュー approval_gates は常に skip_* の否定と整合する
    assert config.workflow.wf_next.approval_gates.audio is True
    assert config.workflow.wf_next.approval_gates.upload is True


def test_workflow_wf_next_legacy_approval_gates_alias_regression(tmp_path, monkeypatch):
    """#1744: 旧 `approval_gates.upload: false` のみの JSON は従来どおり承認なしで進む."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "approval_gates": {"upload": False},
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.skip_upload_approval is True
    assert config.workflow.wf_next.approval_gates.upload is False


def test_workflow_wf_next_legacy_approval_gates_maps_to_skip(tmp_path, monkeypatch):
    """#1744: 旧 `approval_gates.*: true` は `skip_*_approval = False` に写像される."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "approval_gates": {"audio": True, "upload": True},
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.skip_audio_approval is False
    assert config.workflow.wf_next.skip_upload_approval is False


@pytest.mark.parametrize(
    ("new_key", "legacy_key"),
    [("skip_audio_approval", "audio"), ("skip_upload_approval", "upload")],
)
def test_workflow_wf_next_skip_approval_conflicts_with_legacy(tmp_path, monkeypatch, new_key, legacy_key):
    """#1744: 同一ゲートへの新旧キー同時指定は値が一致していても ConfigError."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                new_key: True,
                "approval_gates": {legacy_key: False},
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    expected = f"workflow.wf_next.{new_key} と workflow.wf_next.approval_gates.{legacy_key} は"
    with pytest.raises(ConfigError, match=expected):
        load_config()


def test_workflow_wf_next_skip_approval_mixed_gates_are_independent(tmp_path, monkeypatch):
    """#1744: ゲートが異なれば新旧キーの混在は衝突しない（audio=旧 / upload=新）."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "skip_upload_approval": False,
                "approval_gates": {"audio": True},
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.skip_audio_approval is False
    assert config.workflow.wf_next.skip_upload_approval is False
    assert config.workflow.wf_next.approval_gates.audio is True
    assert config.workflow.wf_next.approval_gates.upload is True


@pytest.mark.parametrize("new_key", ["skip_audio_approval", "skip_upload_approval"])
@pytest.mark.parametrize("invalid", ["false", "true", 1, 0, None, {}, []])
def test_workflow_wf_next_skip_approval_must_be_boolean(tmp_path, monkeypatch, new_key, invalid):
    """#1744: `skip_*_approval` の非 boolean は ConfigError."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                new_key: invalid,
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match=f"workflow.wf_next.{new_key} は boolean"):
        load_config()


def test_workflow_wf_next_skip_manual_mastering_default(tmp_path, monkeypatch):
    """#1449: `skip_manual_mastering` 未設定なら `False`（従来通り最終マスター配置待ち）."""
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.skip_manual_mastering is False


def test_workflow_wf_next_skip_manual_mastering_explicit(tmp_path, monkeypatch):
    """#1449: `skip_manual_mastering: true` で raw=final 運用を宣言できる."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "skip_manual_mastering": True,
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.workflow.wf_next.skip_manual_mastering is True
    # approval_gates は独立した設定であり default を維持する
    assert config.workflow.wf_next.approval_gates.audio is False
    assert config.workflow.wf_next.approval_gates.upload is False


@pytest.mark.parametrize("invalid", ["false", "true", 1, 0, None, {}, []])
def test_workflow_wf_next_skip_manual_mastering_must_be_boolean(tmp_path, monkeypatch, invalid):
    """#1449: string/int/null/object は raw=final を誤作動させず ConfigError."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "skip_manual_mastering": invalid,
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="workflow.wf_next.skip_manual_mastering は boolean"):
        load_config()


@pytest.mark.parametrize("gate_key", ["audio", "upload"])
def test_workflow_wf_next_approval_gates_must_be_boolean(tmp_path, monkeypatch, gate_key):
    """#508/#1449: wf_next の boolean 契約を Python/TS で揃える."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {
            "wf_next": {
                "approval_gates": {gate_key: "false"},
            },
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match=f"workflow.wf_next.approval_gates.{gate_key} は boolean"):
        load_config()


@pytest.mark.parametrize(
    ("workflow_value", "message"),
    [
        ([], "workflow セクションは object"),
        ("", "workflow セクションは object"),
        (False, "workflow セクションは object"),
        (None, "workflow セクションは object"),
    ],
)
def test_workflow_section_falsy_non_objects_are_rejected(tmp_path, monkeypatch, workflow_value, message):
    """#1449: falsy な非 object を未設定扱いせず、TS schema と同じ契約で弾く."""
    sections = _minimal_sections()
    sections["workflow.json"] = {"workflow": workflow_value}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match=message):
        load_config()


@pytest.mark.parametrize(
    ("wf_next_value", "message"),
    [
        ([], "workflow.wf_next は object"),
        ("", "workflow.wf_next は object"),
        (False, "workflow.wf_next は object"),
        (None, "workflow.wf_next は object"),
    ],
)
def test_workflow_wf_next_falsy_non_objects_are_rejected(tmp_path, monkeypatch, wf_next_value, message):
    """#1449: wf_next の falsy 非 object も default に潰さない."""
    sections = _minimal_sections()
    sections["workflow.json"] = {"workflow": {"wf_next": wf_next_value}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match=message):
        load_config()


@pytest.mark.parametrize(
    ("gates_value", "message"),
    [
        ([], "workflow.wf_next.approval_gates は object"),
        ("", "workflow.wf_next.approval_gates は object"),
        (False, "workflow.wf_next.approval_gates は object"),
        (None, "workflow.wf_next.approval_gates は object"),
    ],
)
def test_workflow_approval_gates_falsy_non_objects_are_rejected(tmp_path, monkeypatch, gates_value, message):
    """#1449: approval_gates の falsy 非 object も default に潰さない."""
    sections = _minimal_sections()
    sections["workflow.json"] = {"workflow": {"wf_next": {"approval_gates": gates_value}}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match=message):
        load_config()


def test_workflow_section_must_be_object(tmp_path, monkeypatch):
    """#508: `workflow` セクションが object でないと ConfigError."""
    sections = _minimal_sections()
    sections["workflow.json"] = {"workflow": "not-an-object"}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="workflow セクションは object"):
        load_config()


def test_workflow_wf_next_must_be_object(tmp_path, monkeypatch):
    """#508: `workflow.wf_next` が object でないと ConfigError."""
    sections = _minimal_sections()
    sections["workflow.json"] = {"workflow": {"wf_next": ["bad"]}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="workflow.wf_next は object"):
        load_config()


def test_workflow_approval_gates_must_be_object(tmp_path, monkeypatch):
    """#508: `workflow.wf_next.approval_gates` が object でないと ConfigError."""
    sections = _minimal_sections()
    sections["workflow.json"] = {
        "workflow": {"wf_next": {"approval_gates": "bad"}},
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="workflow.wf_next.approval_gates は object"):
        load_config()


def test_comments_rule_without_name_is_ignored_by_loader(tmp_path, monkeypatch):
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [{"keywords": ["hi"]}],  # name 未指定
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.rules == []


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

    with pytest.raises(ConfigError, match="/channel-new の既存チャンネル取り込みモード"):
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


@pytest.mark.parametrize(
    "value,got_type",
    [
        (42, "int"),
        ([1, 2], "list"),
        (None, "NoneType"),
        (3.14, "float"),
        (True, "bool"),
    ],
)
def test_playlists_invalid_per_key_shape_raises_config_error(value, got_type):
    """playlists.<key> の値が string / object 以外（list / int / null 等）なら ConfigError.

    #419: silent pass-through すると Playlists.items: dict[str, dict] 型注釈と
    実態が乖離するため Fail Fast にする。エラーメッセージに got 型名を含める。
    """
    from youtube_automation.utils.config.loader import _build_playlists
    from youtube_automation.utils.exceptions import ConfigError

    merged = {"playlists": {"main": value}}

    with pytest.raises(ConfigError, match=rf"playlists\.main .*got {got_type}"):
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


def test_tags_for_collection_strips_quotes(tmp_path, monkeypatch):
    """#1096: content.json にクォート付きタグがあっても除去されること."""
    sections = _minimal_sections()
    sections["content.json"]["tags"]["base"] = ['"Paris Café Jazz"', "clean tag", '"French Café"']
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()
    tags = config.content.tags.for_collection("test-collection")

    assert "Paris Café Jazz" in tags
    assert "clean tag" in tags
    assert "French Café" in tags
    assert not any('"' in t for t in tags)


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
    assert channel_dir() != ch / "config" / "channel"


def test_channel_dir_ancestor_search(tmp_path, monkeypatch):
    ch = _setup_channel(tmp_path, _minimal_sections())
    sub = ch / "collections" / "foo"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    monkeypatch.delenv("CHANNEL_DIR", raising=False)

    assert channel_dir().resolve() == ch.resolve()
    assert channel_dir().resolve() != (ch / "config" / "channel").resolve()


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
            "model": "gemini-3.5-flash",
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
    assert gen.model == "gemini-3.5-flash"
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
            "model": "gemini-3.5-flash",
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


@pytest.mark.parametrize("comments_raw", [None, [], "", False, "legacy"])
def test_comments_section_non_object_raises(tmp_path, monkeypatch, comments_raw):
    """comments セクション自体は falsy 値でも object 以外を未設定扱いしない."""
    sections = _minimal_sections()
    sections["comments.json"] = {"comments": comments_raw}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments セクションは object"):
        load_config()


def test_comments_rule_invalid_provider_is_ignored_by_loader(tmp_path, monkeypatch):
    """comments.rules[] は legacy 互換で受けるが処理では無視する."""
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

    config = load_config()

    assert config.comments.rules == []


def test_comments_rule_gemini_without_generator_section_loads(tmp_path, monkeypatch):
    """rule provider='gemini' は互換入力として受けるが generator は global を使う."""
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
    assert config.comments.rules == []


def test_comments_rule_scope_defaults_to_any(tmp_path, monkeypatch):
    """#524: scope 未指定の legacy rule も無視してロードされる."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [{"name": "g", "keywords": ["hi"]}],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.rules == []


def test_comments_rule_scope_override_loads(tmp_path, monkeypatch):
    """#524: scope を指定した legacy rule も無視してロードされる."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [
                {"name": "top", "keywords": ["hi"], "scope": "top_level"},
                {"name": "rep", "keywords": ["bye"], "scope": "reply"},
            ],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.rules == []


def test_comments_rule_non_object_is_ignored_by_loader(tmp_path, monkeypatch):
    """comments.rules[] の要素 shape は処理で使わないため検証しない."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": ["legacy-string"],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.rules == []


@pytest.mark.parametrize("rules_raw", ["", {}, False])
def test_comments_rules_falsy_non_list_raises(tmp_path, monkeypatch, rules_raw):
    """comments.rules は falsy 値でも list 以外を暗黙に [] 扱いしない."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": rules_raw,
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match=r"comments\.rules は list"):
        load_config()


def test_comments_rule_invalid_scope_is_ignored_by_loader(tmp_path, monkeypatch):
    """comments.rules[i].scope は legacy 入力として受けるが処理では無視する."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "enabled": True,
            "rules": [{"name": "bad", "keywords": ["hi"], "scope": "thread"}],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.rules == []


def test_comments_language_loads(tmp_path, monkeypatch):
    """comments.language は返信言語ヒントとしてロードされる."""
    sections = _minimal_sections()
    sections["comments.json"] = {"comments": {"enabled": True, "language": "ja"}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.comments.language == "ja"


def test_comments_language_empty_raises(tmp_path, monkeypatch):
    """comments.language の空文字は ConfigError."""
    sections = _minimal_sections()
    sections["comments.json"] = {"comments": {"enabled": True, "language": ""}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.language"):
        load_config()


def test_comments_language_non_string_raises(tmp_path, monkeypatch):
    """comments.language が文字列でない場合は ConfigError."""
    sections = _minimal_sections()
    sections["comments.json"] = {"comments": {"enabled": True, "language": ["ja"]}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="comments.language"):
        load_config()


def test_comments_dataclass_defaults_to_codex_without_loader():
    """Comments dataclass を直接構築した場合でも codex 既定になる."""
    from youtube_automation.utils.config.comments import Comments

    comments = Comments(enabled=True)

    assert comments.generator.provider == "codex"
    assert comments.rules == []


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


def test_comments_legacy_template_key_is_ignored(tmp_path, monkeypatch):
    """旧 comments.rules[].template_key は後方互換で読み捨てる."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "rules": [{"name": "legacy", "keywords": ["hi"], "template_key": "default"}],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()
    assert config.comments.rules == []


def test_comments_legacy_rule_generator_key_is_ignored(tmp_path, monkeypatch):
    """旧 comments.rules[].generator は後方互換で読み捨てる."""
    sections = _minimal_sections()
    sections["comments.json"] = {
        "comments": {
            "rules": [{"name": "legacy", "keywords": ["hi"], "generator": "gemini"}],
        }
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()
    assert config.comments.rules == []


# ----- overlays (#511) -----------------------------------------------------


def test_overlays_section_missing_defaults_to_disabled(tmp_path, monkeypatch):
    """#511: youtube.json に `overlays` キーが無いとき、既定で `enabled=False` 相当として返る."""
    ch = _setup_channel(tmp_path, _minimal_sections())
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.youtube.overlays.enabled is False
    # ネスト dataclass も既定値で組み立てられている（generate_videos.sh は enabled=false で
    # 完全に無視するためフィールド値は使われないが、属性アクセスは安全であること）
    assert config.youtube.overlays.audio_visualizer.enabled is False
    assert config.youtube.overlays.subscribe_popup.enabled is False
    assert config.youtube.overlays.encoder.codec == "libx264"
    assert config.youtube.overlays.encoder.framerate == 24


def test_overlays_section_full_override(tmp_path, monkeypatch):
    """#511: `overlays.enabled: true` + 全フィールド指定で値が dataclass まで届く."""
    sections = _minimal_sections()
    sections["youtube.json"]["overlays"] = {
        "enabled": True,
        "audio_visualizer": {
            "enabled": True,
            "style": "ring-line",
            "bars": 24,
            "mode": "bar",
            "size": "1920x240",
            "rate": "30",
            "fscale": "log",
            "win_size": 4096,
            "win_func": "hann",
            "colors": "0xff66ccff",
            "fill": {"type": "gradient", "top": "0xFF8800", "bottom": "0x4400AA"},
            "mirror_center": True,
            "symmetric_vertical": True,
            "rounding": {"blur": 2.3, "contrast": 3.2},
            "position": "(W-w)/2:H-h-80",
            "opacity": 0.9,
            "glow_enabled": True,
            "glow_sigma": 14.0,
            "glow_opacity": 0.5,
            "ring": {"inner_r": 90, "length": 70, "arc_deg": [30, 330]},
            "glow": {"enabled": False, "sigma": 6.0, "opacity": 0.4},
        },
        "subscribe_popup": {
            "enabled": True,
            "image": "popup.png",
            "start_sec": 8.5,
            "duration_sec": 10.0,
            "fade_sec": 0.8,
            "position": "W-w-32:32",
            "opacity": 0.95,
        },
        "encoder": {
            "codec": "libx264",
            "preset": "slow",
            "crf": 18,
            "pix_fmt": "yuv420p",
            "maxrate": "6M",
            "bufsize": "12M",
            "profile": "high",
            "framerate": 30,
        },
    }
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    ov = config.youtube.overlays
    assert ov.enabled is True

    assert ov.audio_visualizer.enabled is True
    assert ov.audio_visualizer.style == "ring-line"
    assert ov.audio_visualizer.bars == 24
    assert ov.audio_visualizer.size == "1920x240"
    assert ov.audio_visualizer.rate == "30"
    assert ov.audio_visualizer.win_size == 4096
    assert ov.audio_visualizer.colors == "0xff66ccff"
    assert ov.audio_visualizer.position == "(W-w)/2:H-h-80"
    assert ov.audio_visualizer.glow_sigma == 14.0
    assert ov.audio_visualizer.glow_opacity == 0.5
    assert ov.audio_visualizer.ring.inner_r == 90
    assert ov.audio_visualizer.ring.length == 70
    assert ov.audio_visualizer.ring.arc_deg == (30.0, 330.0)
    assert ov.audio_visualizer.fill is not None
    assert ov.audio_visualizer.fill.type == "gradient"
    assert ov.audio_visualizer.fill.bottom == "0x4400AA"
    assert ov.audio_visualizer.mirror_center is True
    assert ov.audio_visualizer.symmetric_vertical is True
    assert ov.audio_visualizer.rounding is not None
    assert ov.audio_visualizer.rounding.blur == 2.3
    assert ov.audio_visualizer.glow is not None
    assert ov.audio_visualizer.glow.enabled is False
    assert ov.audio_visualizer.glow.sigma == 6.0

    assert ov.subscribe_popup.enabled is True
    assert ov.subscribe_popup.image == "popup.png"
    assert ov.subscribe_popup.start_sec == 8.5
    assert ov.subscribe_popup.duration_sec == 10.0
    assert ov.subscribe_popup.fade_sec == 0.8
    assert ov.subscribe_popup.position == "W-w-32:32"
    assert ov.subscribe_popup.opacity == 0.95

    assert ov.encoder.preset == "slow"
    assert ov.encoder.crf == 18
    assert ov.encoder.maxrate == "6M"
    assert ov.encoder.bufsize == "12M"
    assert ov.encoder.framerate == 30


def test_overlays_empty_object_uses_defaults(tmp_path, monkeypatch):
    """#511: `overlays: {}` は `enabled=False` の既定相当として扱う（後方互換）."""
    sections = _minimal_sections()
    sections["youtube.json"]["overlays"] = {}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    config = load_config()

    assert config.youtube.overlays.enabled is False
    assert config.youtube.overlays.audio_visualizer.enabled is False
    assert config.youtube.overlays.subscribe_popup.enabled is False


def test_overlays_section_non_object_raises(tmp_path, monkeypatch):
    """#511: `overlays` が object でないときは ConfigError."""
    sections = _minimal_sections()
    sections["youtube.json"]["overlays"] = ["enabled", "true"]
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="overlays セクションは object"):
        load_config()


def test_overlays_audio_visualizer_non_object_raises(tmp_path, monkeypatch):
    """#511: `overlays.audio_visualizer` が object でないときは ConfigError."""
    sections = _minimal_sections()
    sections["youtube.json"]["overlays"] = {"audio_visualizer": "bar"}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="overlays.audio_visualizer"):
        load_config()


def test_overlays_audio_visualizer_invalid_style_raises(tmp_path, monkeypatch):
    """#1684: style は公開済み 4 preset 以外を fail-loud に拒否する."""
    sections = _minimal_sections()
    sections["youtube.json"]["overlays"] = {"audio_visualizer": {"style": "heart"}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="bar, mirror-mountain, ring, ring-line"):
        load_config()


@pytest.mark.parametrize(
    "ring",
    [
        {"inner_r": -1},
        {"length": 0},
        {"arc_deg": [330, 30]},
        {"arc_deg": [0]},
    ],
)
def test_overlays_audio_visualizer_invalid_ring_raises(tmp_path, monkeypatch, ring):
    """#1684: ring geometry の不正値は loader 境界で拒否する."""
    sections = _minimal_sections()
    sections["youtube.json"]["overlays"] = {"audio_visualizer": {"style": "ring", "ring": ring}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match="overlays.audio_visualizer.ring"):
        load_config()


@pytest.mark.parametrize(
    ("fill", "message"),
    [
        ({"type": "plasma"}, "fill.type"),
        ({"type": "solid", "color": "not-a-color"}, "色指定"),
        ({"type": "gradient", "top": "sunset", "bottom": "0x000000"}, "色指定"),
    ],
)
def test_audio_visualizer_invalid_fill_raises(tmp_path, monkeypatch, fill, message):
    sections = _minimal_sections()
    sections["youtube.json"]["overlays"] = {"audio_visualizer": {"fill": fill}}
    ch = _setup_channel(tmp_path, sections)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))

    with pytest.raises(ConfigError, match=message):
        load_config()
