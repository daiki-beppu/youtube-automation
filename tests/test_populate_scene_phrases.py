"""yt-populate-scene-phrases CLI のユニットテスト."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from youtube_automation.agents._preflight import PreflightMixin
from youtube_automation.configuration import load_config, reset
from youtube_automation.domains.metadata import BAHMetadataGenerator
from youtube_automation.scripts import populate_scene_phrases
from youtube_automation.utils.exceptions import ConfigError, ValidationError


class _PreflightHarness(PreflightMixin):
    def __init__(self, collections_root: Path) -> None:
        self.collections_root = collections_root

    @staticmethod
    def _extract_md_section(text: str, header: str) -> str | None:
        pattern = rf"^## {re.escape(header)}\n```(?:\w+)?\n(.*?)\n```"
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        return match.group(1) if match else None


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


def _write_descriptions_md(collection_dir: Path) -> None:
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "descriptions.md").write_text(
        """## タイトル案
```
Late-night neon city, jazz between rain and streetlights | 3 Hours of Study
```

## Complete Collection 概要欄
```
A continuous BGM mix without chapter markers.
```
""",
        encoding="utf-8",
    )


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
        result = populate_scene_phrases.translate_phrase(
            "Hello",
            ["en", "ja", "ko"],
            translations_json='{"ja": "あ", "ko": "ㄱ"}',
        )

        assert result == {"ja": "あ", "ko": "ㄱ"}

    def test_strips_code_fence(self):
        result = populate_scene_phrases.translate_phrase(
            "Night",
            ["ja"],
            translations_json='```json\n{"ja": "夜"}\n```',
        )

        assert result == {"ja": "夜"}

    def test_missing_lang_raises_validation_error(self):
        with pytest.raises(ValidationError, match="翻訳欠落"):
            populate_scene_phrases.translate_phrase("Night", ["ja", "ko"], translations_json='{"ja": "夜"}')

    def test_invalid_json_raises_validation_error(self):
        with pytest.raises(ValidationError, match="JSON") as exc_info:
            populate_scene_phrases.translate_phrase("Night", ["ja"], translations_json="not json")
        assert "not json" not in str(exc_info.value)

    def test_non_object_json_raises_validation_error_without_raw_payload(self):
        with pytest.raises(ValidationError, match="object") as exc_info:
            populate_scene_phrases.translate_phrase("Night", ["ja"], translations_json='["secret"]')
        assert "secret" not in str(exc_info.value)

    @pytest.mark.parametrize("translations_json", ['{"ja": 123}', '{"ja": ""}', '{"ja": {"text": "夜"}}'])
    def test_rejects_non_string_or_empty_translation_values(self, translations_json):
        with pytest.raises(ValidationError, match="非空文字列"):
            populate_scene_phrases.translate_phrase("Night", ["ja"], translations_json=translations_json)

    def test_missing_language_error_does_not_include_raw_payload(self):
        with pytest.raises(ValidationError, match="翻訳欠落") as exc_info:
            populate_scene_phrases.translate_phrase(
                "Night",
                ["ja", "ko"],
                translations_json='{"ja": "夜", "credential": "SECRET"}',
            )
        message = str(exc_info.value)
        assert "credential" in message
        assert "SECRET" not in message

    def test_no_targets_skips_call(self):
        result = populate_scene_phrases.translate_phrase("x", ["en"], translations_json="")
        assert result == {}


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

    @pytest.mark.parametrize(
        "bad_name",
        [
            "",
            ".",
            "..",
            "/tmp/outside",
            "../outside",
            "planning/20260322-tc-city-collection",
            r"planning\20260322-tc-city-collection",
        ],
    )
    def test_rejects_collection_path_escape(self, tmp_path, monkeypatch, bad_name):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en"],
            workflow_state={"theme": "city"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        with pytest.raises(ConfigError, match="コレクション名が不正"):
            populate_scene_phrases._resolve_collection_path(bad_name)

    def test_single_language_populate_to_upload_metadata_path_passes(self, tmp_path, monkeypatch, capsys):
        """単一言語では populate no-op 後の upload 側経路も scene_phrases 無しで通る (#1470)."""
        collection_name = "20260322-tc-city-collection"
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en"],
            workflow_state={"theme": "city"},
            collection_name=collection_name,
        )
        collection_dir = ch / "collections" / "planning" / collection_name
        _write_descriptions_md(collection_dir)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main([collection_name])

        assert rc == 0
        assert "1 言語以下" in capsys.readouterr().out
        state = json.loads((collection_dir / "workflow-state.json").read_text(encoding="utf-8"))
        assert "scene_phrases" not in state

        _PreflightHarness(ch / "collections")._preflight_check(collection_dir)

        gen = object.__new__(BAHMetadataGenerator)
        gen.config = load_config()
        assert (
            gen.generate_localizations(
                "Late-night neon city, jazz between rain and streetlights | 3 Hours of Study",
                "00:00 Intro",
                {},
            )
            == {}
        )

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

        def fake_translate(en_phrase, langs, *, translations_json):
            return {"ja": "深夜のネオン街", "ko": "심야 네온"}

        monkeypatch.setattr(populate_scene_phrases, "translate_phrase", fake_translate)

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--translations-json", "{}"])
        assert rc == 0

        ws = json.loads(
            (ch / "collections" / "planning" / "20260322-tc-city-collection" / "workflow-state.json").read_text(
                encoding="utf-8"
            )
        )
        assert ws["scene_phrases"]["en"] == "Late-night neon city, jazz between rain and streetlights"
        assert ws["scene_phrases"]["ja"] == "深夜のネオン街"
        assert ws["scene_phrases"]["ko"] == "심야 네온"

    def test_writes_translated_phrases_from_file(self, tmp_path, monkeypatch):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city"},
        )
        translations_file = tmp_path / "phrases.json"
        translations_file.write_text('{"ja": "深夜のネオン街"}', encoding="utf-8")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--translations-file", str(translations_file)])

        assert rc == 0
        ws = json.loads(
            (ch / "collections" / "planning" / "20260322-tc-city-collection" / "workflow-state.json").read_text(
                encoding="utf-8"
            )
        )
        assert ws["scene_phrases"]["ja"] == "深夜のネオン街"

    def test_missing_translations_file_returns_error(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(
            ["20260322-tc-city-collection", "--translations-file", str(tmp_path / "missing.json")]
        )

        assert rc == 1
        assert "--translations-file" in capsys.readouterr().err

    def test_translations_json_and_file_are_rejected(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city"},
        )
        translations_file = tmp_path / "phrases.json"
        translations_file.write_text('{"ja": "深夜"}', encoding="utf-8")
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(
            [
                "20260322-tc-city-collection",
                "--translations-json",
                '{"ja": "夜"}',
                "--translations-file",
                str(translations_file),
            ]
        )

        assert rc == 1
        assert "同時指定" in capsys.readouterr().err

    def test_translations_file_directory_returns_controlled_error(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city"},
        )
        translations_dir = tmp_path / "translations-dir"
        translations_dir.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--translations-file", str(translations_dir)])

        assert rc == 1
        assert "通常ファイル" in capsys.readouterr().err

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

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--dry-run", "--translations-json", "{}"])
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

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--overwrite", "--translations-json", "{}"])
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

        rc = populate_scene_phrases.main(
            ["20260322-tc-city-collection", "--en", "Custom phrase", "--translations-json", "{}"]
        )
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

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--translations-json", "{}"])
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

        rc = populate_scene_phrases.main(["20260322-tc-city-collection", "--translations-json", "{}"])
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

    def test_missing_translations_json_returns_agent_instruction(self, tmp_path, monkeypatch, capsys):
        ch = _setup_channel(
            tmp_path,
            supported_languages=["en", "ja"],
            workflow_state={"theme": "city"},
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        rc = populate_scene_phrases.main(["20260322-tc-city-collection"])

        assert rc == 1
        err = capsys.readouterr().err
        assert "--translations-json" in err
        assert "Claude Agent" in err
