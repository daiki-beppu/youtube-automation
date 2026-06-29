from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.scripts import suno_select_tracks
from youtube_automation.utils.exceptions import ValidationError


def _make_collection(tmp_path: Path, prompts: list[dict]) -> Path:
    collection = tmp_path / "collections" / "planning" / "20260629-test-collection"
    (collection / "20-documentation").mkdir(parents=True)
    (collection / "02-Individual-music").mkdir()
    (collection / "01-master").mkdir()
    (collection / "20-documentation" / "suno-prompts.json").write_text(
        json.dumps(prompts),
        encoding="utf-8",
    )
    return collection


def _write_audio(collection: Path, name: str) -> Path:
    path = collection / "02-Individual-music" / name
    path.write_bytes(b"audio")
    return path


def _cfg(**pair_overrides):
    pair_selection = {
        "mode": "auto",
        "strategy": "random",
        "random_seed": 1,
        "min_song_sec": 45,
        "max_song_sec": 300,
        "out_of_range_action": "stock",
        "selection_log_path": "01-master/.selection.log",
    }
    pair_selection.update(pair_overrides)
    return {
        "pair_selection": pair_selection,
        "stock": {
            "dir": "assets/stock/music/b-side",
            "filename_template": "{collection_slug}__{song_id}__{title_slug}.{ext}",
            "on_duplicate": "skip",
        },
    }


def test_vocal_prompt_keeps_one_winner_and_stocks_loser(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello dawn"}],
    )
    _write_audio(collection, "01a-Dawn Song.mp3")
    _write_audio(collection, "01b-Dawn Song.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)

    result = suno_select_tracks.select_suno_tracks(collection, _cfg())

    music_files = sorted(p.name for p in (collection / "02-Individual-music").iterdir() if p.is_file())
    assert music_files == ["01-Dawn Song.mp3"]
    assert len(result.winners) == 1
    assert len(result.stocked) == 1
    assert result.mode_counts == {"vocal": 1, "instrumental": 0}
    assert (collection / "01-master" / ".selection.log").exists()


def test_instrumental_prompt_keeps_both_clips_after_duration_filter(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": "[Instrumental]\n[Extended Outro]"}],
    )
    _write_audio(collection, "01a-Dawn Groove.mp3")
    _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)

    result = suno_select_tracks.select_suno_tracks(collection, _cfg())

    music_files = sorted(p.name for p in (collection / "02-Individual-music").iterdir() if p.is_file())
    assert music_files == ["01a-Dawn Groove.mp3", "01b-Dawn Groove.mp3"]
    assert result.winners == []
    assert result.stocked == []
    assert result.mode_counts == {"vocal": 0, "instrumental": 1}


def test_duration_filter_stocks_too_short_and_keeps_survivor(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 120.0

    monkeypatch.setattr(suno_select_tracks, "probe_duration", fake_probe)

    result = suno_select_tracks.select_suno_tracks(collection, _cfg())

    music_files = sorted(p.name for p in (collection / "02-Individual-music").iterdir() if p.is_file())
    assert music_files == [survivor.name]
    assert len(result.dropped) == 1
    assert len(result.stocked) == 1
    assert result.stocked[0].exists()
    assert "Dawn Groove" in result.dropped[0].title


def test_all_candidates_dropped_fails_loud(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    _write_audio(collection, "01a-Dawn Groove.mp3")
    _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 20.0)

    with pytest.raises(ValidationError, match="採用候補が 0 件"):
        suno_select_tracks.select_suno_tracks(collection, _cfg())


def test_never_mode_skips_selection(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello"}],
    )
    _write_audio(collection, "01a-Dawn Song.mp3")
    _write_audio(collection, "01b-Dawn Song.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)

    result = suno_select_tracks.select_suno_tracks(collection, _cfg(mode="never"))

    music_files = sorted(p.name for p in (collection / "02-Individual-music").iterdir() if p.is_file())
    assert music_files == ["01a-Dawn Song.mp3", "01b-Dawn Song.mp3"]
    assert result.kept == []
