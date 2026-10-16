from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.music_prompt import write_suno_prompt_pair
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.suno.prompts import read_suno_duration_filter, validate_suno_prompt_entry_identity


def _documentation(tmp_path: Path, duration_filter: object | None) -> Path:
    documentation = tmp_path / "20-documentation"
    documentation.mkdir()
    write_suno_prompt_pair(
        documentation,
        [{"name": "Rain"}],
        duration_filter=duration_filter,
    )
    return tmp_path


def test_duration_filter_reader_returns_validated_yield_guard(tmp_path: Path) -> None:
    collection = _documentation(tmp_path, {"min_sec": 60, "max_sec": 300})

    result = read_suno_duration_filter(collection)

    assert result.minimum_seconds == 60.0
    assert result.maximum_seconds == 300.0


def test_duration_filter_reader_rejects_missing_guard(tmp_path: Path) -> None:
    collection = _documentation(tmp_path, None)

    with pytest.raises(ValueError, match="duration_filter"):
        read_suno_duration_filter(collection)


def test_duration_filter_reader_rejects_inverted_guard(tmp_path: Path) -> None:
    collection = _documentation(tmp_path, {"min_sec": 300, "max_sec": 60})

    with pytest.raises(ValueError, match="duration_filter range"):
        read_suno_duration_filter(collection)


def test_entry_identity_returns_name_and_optional_title() -> None:
    assert validate_suno_prompt_entry_identity(1, {"name": "Rain", "title": "Rain Song"}) == ("Rain", "Rain Song")
    assert validate_suno_prompt_entry_identity(1, {"name": "Rain"}) == ("Rain", None)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("not object", "suno-prompts.json: entry 2 must be an object"),
        ({"title": "Rain"}, "suno-prompts.json: entry 2.name must be a non-empty string"),
        ({"name": "  ", "title": ["Rain"]}, "suno-prompts.json: entry 2.name must be a non-empty string"),
        ({"name": "Rain", "title": ["Rain"]}, "suno-prompts.json: entry 2.title must be a string"),
    ],
)
def test_entry_identity_rejects_invalid_entry(entry: object, message: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate_suno_prompt_entry_identity(2, entry)

    assert str(exc_info.value) == message
