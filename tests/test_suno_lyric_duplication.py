from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude/skills/suno-lyric/references/check_lyric_duplication.py"


def _write_lyrics(path: Path, entries: object) -> Path:
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return path


def _run(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )


def test_check_lyric_duplication_rejects_cross_song_target_section_duplicate(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {
                "name": "Song A",
                "lyrics": "[Intro]\nSame dawn line\n\n[Pre-Chorus]\nShared lift line\n\n[Verse 1]\nA",
                "style": None,
            },
            {
                "name": "Song B",
                "lyrics": "[Bridge]\n same   dawn line \n\n[Outro]\nShared lift line\n\n[Verse 1]\nB",
                "style": None,
            },
        ],
    )

    result = _run(path)

    assert result.returncode == 1
    assert "NG: 曲間でセクション本文が完全一致" in result.stdout
    assert "2 件" in result.stdout
    assert "[Bridge], [Intro]" in result.stdout
    assert "[Outro], [Pre-Chorus]" in result.stdout
    assert "text: same dawn line ..." in result.stdout
    assert "text: shared lift line ..." in result.stdout
    assert "Song A, Song B" in result.stdout


def test_check_lyric_duplication_rejects_extended_outro_and_outro_duplicate(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {"name": "Song A", "lyrics": "[Extended Outro]\nSame farewell line", "style": None},
            {"name": "Song B", "lyrics": "[Outro]\nSame farewell line", "style": None},
        ],
    )

    result = _run(path)

    assert result.returncode == 1
    assert "[Extended Outro], [Outro]" in result.stdout


def test_check_lyric_duplication_accepts_unique_target_sections(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {"name": "Song A", "lyrics": "[Intro]\nMorning light\n\n[Bridge]\nOpen road", "style": None},
            {"name": "Song B", "lyrics": "[Intro]\nEvening rain\n\n[Bridge]\nQuiet room", "style": None},
        ],
    )

    result = _run(path)

    assert result.returncode == 0
    assert "OK: 曲間のセクション重複なし" in result.stdout


def test_check_lyric_duplication_ignores_reviewer_context_fields(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {
                "name": "Song A",
                "lyrics": "[Intro]\nMorning light\n\n[Bridge]\nOpen road",
                "style": None,
                "review_context": {
                    "collection_theme": "quiet recovery",
                    "scene": "first light by a window",
                    "mood": "warm",
                    "persona_target": "tired adult listener",
                    "persona_vocabulary": ["ゆっくり"],
                    "quote_essence": "small courage matters",
                },
            }
        ],
    )

    result = _run(path)

    assert result.returncode == 0
    assert "OK: 曲間のセクション重複なし" in result.stdout


def test_check_lyric_duplication_ignores_same_song_repetition(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {
                "name": "Song A",
                "lyrics": "[Chorus]\nHold this line\n\n[Final Chorus]\nHold this line",
                "style": None,
            }
        ],
    )

    result = _run(path, "--sections", "Chorus,Final Chorus")

    assert result.returncode == 0


def test_check_lyric_duplication_sections_filter_limits_scope(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {"name": "Song A", "lyrics": "[Instrumental]\nSame riff\n\n[Bridge]\nBlue window", "style": None},
            {"name": "Song B", "lyrics": "[Instrumental]\nSame riff\n\n[Bridge]\nRed window", "style": None},
        ],
    )

    result = _run(path, "--sections", "Bridge")

    assert result.returncode == 0


def test_check_lyric_duplication_sections_filter_detects_selected_scope(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {"name": "Song A", "lyrics": "[Instrumental]\nSame riff\n\n[Bridge]\nShared bridge", "style": None},
            {"name": "Song B", "lyrics": "[Instrumental]\nSame riff\n\n[Bridge]\nShared bridge", "style": None},
        ],
    )

    result = _run(path, "--sections", "Bridge")

    assert result.returncode == 1
    assert "[Bridge]" in result.stdout
    assert "text: shared bridge ..." in result.stdout
    assert "[Instrumental]" not in result.stdout
    assert "same riff" not in result.stdout


def test_check_lyric_duplication_empty_sections_filter_is_format_error(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {"name": "Song A", "lyrics": "[Intro]\nSame line", "style": None},
            {"name": "Song B", "lyrics": "[Intro]\nSame line", "style": None},
        ],
    )

    for sections in ("", ",", "   "):
        result = _run(path, "--sections", sections)

        assert result.returncode == 2
        assert "1 件以上の section 名" in result.stderr


def test_check_lyric_duplication_default_scope_ignores_non_target_sections(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {"name": "Song A", "lyrics": "[Instrumental]\nSame riff", "style": None},
            {"name": "Song B", "lyrics": "[Instrumental]\nSame riff", "style": None},
        ],
    )

    result = _run(path)

    assert result.returncode == 0


def test_check_lyric_duplication_missing_file_is_format_error(tmp_path: Path) -> None:
    result = _run(tmp_path / "missing.json")

    assert result.returncode == 2
    assert "読み込めません" in result.stderr


def test_check_lyric_duplication_invalid_json_is_format_error(tmp_path: Path) -> None:
    path = tmp_path / "suno-lyrics.json"
    path.write_text("{", encoding="utf-8")

    result = _run(path)

    assert result.returncode == 2
    assert "invalid JSON" in result.stderr


def test_check_lyric_duplication_root_must_be_list(tmp_path: Path) -> None:
    path = _write_lyrics(tmp_path / "suno-lyrics.json", {"name": "Song A"})

    result = _run(path)

    assert result.returncode == 2
    assert "root must be a list" in result.stderr


def test_check_lyric_duplication_entry_must_be_object(tmp_path: Path) -> None:
    path = _write_lyrics(tmp_path / "suno-lyrics.json", ["not-object"])

    result = _run(path)

    assert result.returncode == 2
    assert "entry 1 must be an object" in result.stderr


def test_check_lyric_duplication_name_must_be_non_empty_string(tmp_path: Path) -> None:
    path = _write_lyrics(tmp_path / "suno-lyrics.json", [{"name": " ", "lyrics": "[Intro]\nA"}])

    result = _run(path)

    assert result.returncode == 2
    assert "entry 1.name must be a non-empty string" in result.stderr


def test_check_lyric_duplication_duplicate_name_is_format_error(tmp_path: Path) -> None:
    path = _write_lyrics(
        tmp_path / "suno-lyrics.json",
        [
            {"name": "Song A", "lyrics": "[Intro]\nSame line"},
            {"name": "Song A", "lyrics": "[Intro]\nSame line"},
        ],
    )

    result = _run(path)

    assert result.returncode == 2
    assert "duplicated lyrics entry names: Song A" in result.stderr


@pytest.mark.parametrize(
    ("entry", "expected_message"),
    [
        ({"lyrics": "[Intro]\nA"}, "entry 1.name must be a non-empty string"),
        ({"name": None, "lyrics": "[Intro]\nA"}, "entry 1.name must be a non-empty string"),
        ({"name": "Song A"}, "entry 1.lyrics must be a string"),
        ({"name": "Song A", "lyrics": None}, "entry 1.lyrics must be a string"),
    ],
)
def test_check_lyric_duplication_required_fields_must_be_present_and_non_null(
    tmp_path: Path, entry: dict[str, object], expected_message: str
) -> None:
    path = _write_lyrics(tmp_path / "suno-lyrics.json", [entry])

    result = _run(path)

    assert result.returncode == 2
    assert expected_message in result.stderr


def test_check_lyric_duplication_lyrics_must_be_string(tmp_path: Path) -> None:
    path = _write_lyrics(tmp_path / "suno-lyrics.json", [{"name": "Song A", "lyrics": 123}])

    result = _run(path)

    assert result.returncode == 2
    assert "entry 1.lyrics must be a string" in result.stderr
