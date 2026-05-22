"""Issue #272: localizations サンプル / テンプレの high-CPM 言語固定を守る回帰テスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLE_LOCALIZATIONS = _REPO_ROOT / "examples" / "localizations.example.json"
_CHANNEL_SETUP_TEMPLATE = (
    _REPO_ROOT / ".claude" / "skills" / "channel-setup" / "references" / "localizations-template.json"
)

_EXPECTED_LANGUAGES = ["ja", "en", "de"]
_REMOVED_LANGUAGES = ["ko", "es", "pt", "zh-CN"]
_EXAMPLE_REQUIRED_DESCRIPTION_KEYS = [
    "opening_poem",
    "cta_subscribe",
    "tagline",
    "hashtags",
]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_non_empty_string(value: object, *, field_name: str) -> None:
    assert isinstance(value, str), f"{field_name} must be a string"
    assert value.strip(), f"{field_name} must not be empty"


def test_example_localizations_file_exists() -> None:
    assert _EXAMPLE_LOCALIZATIONS.is_file()


def test_channel_setup_localizations_template_exists() -> None:
    assert _CHANNEL_SETUP_TEMPLATE.is_file()


def test_example_localizations_supported_languages_are_high_cpm_tier_only() -> None:
    data = _read_json(_EXAMPLE_LOCALIZATIONS)

    assert data["supported_languages"] == _EXPECTED_LANGUAGES
    assert set(data["languages"]) == set(_EXPECTED_LANGUAGES)


def test_example_localizations_removes_low_cpm_languages() -> None:
    data = _read_json(_EXAMPLE_LOCALIZATIONS)

    for language in _REMOVED_LANGUAGES:
        assert language not in data["languages"]


@pytest.mark.parametrize("language", _EXPECTED_LANGUAGES, ids=_EXPECTED_LANGUAGES)
def test_example_localizations_languages_define_required_metadata_fields(language: str) -> None:
    data = _read_json(_EXAMPLE_LOCALIZATIONS)

    lang_data = data["languages"][language]
    _assert_non_empty_string(lang_data["title_template"], field_name=f"{language}.title_template")
    _assert_non_empty_string(lang_data["activities"], field_name=f"{language}.activities")

    description = lang_data["description"]
    for key in _EXAMPLE_REQUIRED_DESCRIPTION_KEYS:
        _assert_non_empty_string(description[key], field_name=f"{language}.description.{key}")


def test_channel_setup_template_supported_languages_are_high_cpm_tier_only() -> None:
    data = _read_json(_CHANNEL_SETUP_TEMPLATE)

    assert data["supported_languages"] == _EXPECTED_LANGUAGES
    assert set(data["languages"]) == set(_EXPECTED_LANGUAGES)


@pytest.mark.parametrize("language", _EXPECTED_LANGUAGES, ids=_EXPECTED_LANGUAGES)
def test_channel_setup_template_languages_define_minimum_fields(language: str) -> None:
    data = _read_json(_CHANNEL_SETUP_TEMPLATE)

    lang_data = data["languages"][language]
    _assert_non_empty_string(lang_data["title_template"], field_name=f"{language}.title_template")
    _assert_non_empty_string(lang_data["description_opening"], field_name=f"{language}.description_opening")
