"""yt-populate-scene-phrases CLI のユニットテスト."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_automation.scripts import populate_scene_phrases
from youtube_automation.utils.config import reset
from youtube_automation.utils.exceptions import ValidationError


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _sections_with_theme_scenes() -> dict[str, dict]:
    """multi-language テスト用の最小 channel 構成."""
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
            "genre": {"primary": "jazz", "style": "rainy", "context": "city"},
            "tags": {
                "base": ["jazz", "lofi"],
                "themes": {"city": ["city jazz"], "cafe": ["cafe jazz"]},
            },
            "descriptions": {
                "opening": "{style} {primary} for {context}",
                "perfect_for": ["Study"],
                "hashtags": ["#Jazz"],
            },
            "title": {
                "template": "{scene_phrase} | RPG BGM ({activities})",
                "theme_scenes": {
                    "city": {
                        "scene": "Late-night neon city, jazz between rain and streetlights",
                        "activities": "Study",
                        "scene_emoji": "🌃",
                    },
                    "cafe": {
                        "scene": "Rainy night cafe, jazz between pages and coffee steam",
                        "activities": "Read",
                        "scene_emoji": "☕",
                    },
                },
            },
        },
        "youtube.json": {
            "youtube": {
                "category_id": "10",
                "privacy_status": "public",
                "language": "en",
            }
        },
    }


def _setup_channel(
    tmp_path: Path,
    *,
    supported_languages: list[str] | None = None,
    workflow_state: dict | None = None,
    collection_stage: str = "planning",
    collection_name: str = "20260322-tc-city-collection",
) -> Path:
    ch = tmp_path / "channel"
    for filename, data in _sections_with_theme_scenes().items():
        _write_json(ch / "config" / "channel" / filename, data)
    if supported_languages is not None:
        _write_json(
            ch / "config" / "localizations.json",
            {
                "default_language": "en",
                "supported_languages": supported_languages,
                "languages": {
                    lang: {"title_template": "{scene_phrase}", "activities": "x"}
                    for lang in supported_languages
                    if lang != "en"
                },
            },
        )
    if workflow_state is not None:
        _write_json(
            ch / "collections" / collection_stage / collection_name / "workflow-state.json",
            workflow_state,
        )
    return ch


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    """各テスト前後で CHANNEL_DIR / config singleton をリセット."""
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    reset()
    yield
    reset()


# --- translate_phrase --------------------------------------------------------


class TestTranslatePhrase:
    def test_excludes_en_from_targets(self):
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text='{"ja": "あ", "ko": "ㄱ"}')

        result = populate_scene_phrases.translate_phrase("Hello", ["en", "ja", "ko"], client=client)

        assert result == {"ja": "あ", "ko": "ㄱ"}
        # en は target に含めない（en は別途追加されるため）
        prompt_arg = client.models.generate_content.call_args.kwargs["contents"][0]
        assert "ja, ko" in prompt_arg
        assert "en, ja" not in prompt_arg

    def test_strips_code_fence(self):
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text='```json\n{"ja": "夜"}\n```')

        result = populate_scene_phrases.translate_phrase("Night", ["ja"], client=client)

        assert result == {"ja": "夜"}

    def test_missing_lang_raises_validation_error(self):
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text='{"ja": "夜"}')

        with pytest.raises(ValidationError, match="翻訳欠落"):
            populate_scene_phrases.translate_phrase("Night", ["ja", "ko"], client=client)

    def test_invalid_json_raises_validation_error(self):
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text="not json")

        with pytest.raises(ValidationError, match="JSON"):
            populate_scene_phrases.translate_phrase("Night", ["ja"], client=client)

    def test_no_targets_skips_call(self):
        client = MagicMock()
        result = populate_scene_phrases.translate_phrase("x", ["en"], client=client)
        assert result == {}
        client.models.generate_content.assert_not_called()


# --- main (CLI) --------------------------------------------------------------


class TestMainCLI:
    def test_skips_single_language_channel(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en"],
            workflow_state={"theme": "city"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(["20260322-tc-city-collection"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "1 言語以下" in out

    def test_skips_when_no_localizations_file(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=None,  # no localizations.json
            workflow_state={"theme": "city"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(["20260322-tc-city-collection"])

        # supported_languages 未定義時は youtube.api.language が単一フォールバック
        assert rc == 0
        assert "1 言語以下" in capsys.readouterr().out

    def test_skips_when_already_populated(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja", "ko"],
            workflow_state={"theme": "city", "scene_phrases": {"en": "x"}},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(["20260322-tc-city-collection"])

        assert rc == 0
        assert "既に存在" in capsys.readouterr().out

    def test_writes_translated_phrases(self, tmp_path, monkeypatch):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja", "ko"],
            workflow_state={"theme": "city"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        def fake_translate(en_phrase, langs, *, client=None, model=None):
            return {"ja": "深夜のネオン街", "ko": "심야 네온"}

        monkeypatch.setattr(populate_scene_phrases, "translate_phrase", fake_translate)

        rc = populate_scene_phrases.main(["20260322-tc-city-collection"])
        assert rc == 0

        ws = json.loads(
            (ch / "collections" / "planning" / "20260322-tc-city-collection" / "workflow-state.json").read_text(
                encoding="utf-8"
            )
        )
        assert ws["scene_phrases"]["en"] == "Late-night neon city, jazz between rain and streetlights"
        assert ws["scene_phrases"]["ja"] == "深夜のネオン街"
        assert ws["scene_phrases"]["ko"] == "심야 네온"

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        monkeypatch.setattr(
            populate_scene_phrases,
            "translate_phrase",
            lambda *a, **kw: {"ja": "深夜"},
        )

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--dry-run"])
        assert rc == 0

        ws = json.loads(
            (ch / "collections" / "planning" / "20260322-tc-city-collection" / "workflow-state.json").read_text(
                encoding="utf-8"
            )
        )
        assert "scene_phrases" not in ws
        assert "--dry-run" in capsys.readouterr().out

    def test_overwrite_replaces_existing(self, tmp_path, monkeypatch):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city", "scene_phrases": {"en": "old"}},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        monkeypatch.setattr(
            populate_scene_phrases,
            "translate_phrase",
            lambda *a, **kw: {"ja": "新しい"},
        )

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--overwrite"])
        assert rc == 0

        ws = json.loads(
            (ch / "collections" / "planning" / "20260322-tc-city-collection" / "workflow-state.json").read_text(
                encoding="utf-8"
            )
        )
        assert ws["scene_phrases"]["en"].startswith("Late-night neon")  # not "old"
        assert ws["scene_phrases"]["ja"] == "新しい"

    def test_uses_en_argument_over_theme_scenes(self, tmp_path, monkeypatch):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "unknown-theme"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        monkeypatch.setattr(
            populate_scene_phrases,
            "translate_phrase",
            lambda en, langs, **kw: {"ja": f"翻訳:{en}"},
        )

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--en", "Custom phrase"])
        assert rc == 0

        ws = json.loads(
            (ch / "collections" / "planning" / "20260322-tc-city-collection" / "workflow-state.json").read_text(
                encoding="utf-8"
            )
        )
        assert ws["scene_phrases"]["en"] == "Custom phrase"
        assert ws["scene_phrases"]["ja"] == "翻訳:Custom phrase"

    def test_missing_theme_and_en_returns_error(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "unknown-theme"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(["20260322-tc-city-collection"])
        assert rc == 1
        assert "英語フレーズを解決できません" in capsys.readouterr().err

    def test_resolves_collection_from_live_dir(self, tmp_path, monkeypatch):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city"},
            collection_stage="live",
            collection_name="20260322-tc-city-collection",
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        monkeypatch.setattr(
            populate_scene_phrases,
            "translate_phrase",
            lambda *a, **kw: {"ja": "深夜"},
        )

        rc = populate_scene_phrases.main(["20260322-tc-city-collection"])
        assert rc == 0

        ws = json.loads(
            (ch / "collections" / "live" / "20260322-tc-city-collection" / "workflow-state.json").read_text(
                encoding="utf-8"
            )
        )
        assert ws["scene_phrases"]["ja"] == "深夜"

    def test_missing_collection_returns_error(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(["nonexistent-collection"])
        assert rc == 1
        assert "見つかりません" in capsys.readouterr().err
