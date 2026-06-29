from __future__ import annotations

import json
import sys
import tomllib
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
    first = _write_audio(collection, "01a-Dawn Groove.mp3")
    second = _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 20.0)

    with pytest.raises(ValidationError, match="採用候補が 0 件"):
        suno_select_tracks.select_suno_tracks(collection, _cfg())

    assert first.exists()
    assert second.exists()
    assert not (tmp_path / "assets" / "stock").exists()
    assert not (collection / "01-master" / ".selection.log").exists()


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


def test_duration_filter_can_delete_too_short_clip(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 120.0

    monkeypatch.setattr(suno_select_tracks, "probe_duration", fake_probe)

    result = suno_select_tracks.select_suno_tracks(collection, _cfg(out_of_range_action="delete"))

    assert not short.exists()
    assert survivor.exists()
    assert result.deleted == [short]
    assert result.stocked == []


def test_dry_run_does_not_move_delete_or_write_log(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello dawn"}],
    )
    first = _write_audio(collection, "01a-Dawn Song.mp3")
    second = _write_audio(collection, "01b-Dawn Song.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)

    result = suno_select_tracks.select_suno_tracks(collection, _cfg(), dry_run=True)

    assert first.exists()
    assert second.exists()
    assert not (tmp_path / "assets" / "stock").exists()
    assert not (collection / "01-master" / ".selection.log").exists()
    assert len(result.stocked) == 1
    assert "dry_run=true" in capsys.readouterr().out


def test_stock_duplicate_fail_preserves_source_and_existing_stock(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3")
    existing = tmp_path / "assets" / "stock" / "music" / "b-side" / (
        "20260629-test-collection__01a-dawn-groove__dawn-groove.mp3"
    )
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 120.0

    monkeypatch.setattr(suno_select_tracks, "probe_duration", fake_probe)
    cfg = _cfg()
    cfg["stock"]["on_duplicate"] = "fail"

    with pytest.raises(ValidationError, match="stock destination already exists"):
        suno_select_tracks.select_suno_tracks(collection, cfg)

    assert short.exists()
    assert survivor.exists()
    assert existing.read_bytes() == b"existing"


def test_invalid_audio_filename_fails_loud(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    invalid = _write_audio(collection, "loose-download.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)

    with pytest.raises(ValidationError, match="命名規則に合わない音源"):
        suno_select_tracks.select_suno_tracks(collection, _cfg())

    assert invalid.exists()


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"pair_selection": []}, "pair_selection must be a mapping"),
        ({"pair_selection": {"min_song_sec": 300, "max_song_sec": 45}}, "min_song_sec は max_song_sec 未満"),
        ({"pair_selection": {"min_song_sec": -1}}, "min_song_sec は 0 以上"),
        ({"pair_selection": {"out_of_range_action": "archive"}}, "out_of_range_action は stock / delete"),
        ({"pair_selection": {"random_seed": True}}, "random_seed は整数または null"),
        ({"stock": []}, "stock must be a mapping"),
        ({"stock": {"on_duplicate": "merge"}}, "stock.on_duplicate は skip / overwrite / fail"),
    ],
)
def test_malformed_config_is_rejected(tmp_path, monkeypatch, override, match):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    _write_audio(collection, "01a-Dawn Groove.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)
    cfg = _cfg()
    cfg.update(override)

    with pytest.raises(ValidationError, match=match):
        suno_select_tracks.select_suno_tracks(collection, cfg)


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"pair_selection": {"selection_log_path": "../outside.log"}}, "selection_log_path"),
        ({"pair_selection": {"selection_log_path": "/tmp/outside.log"}}, "selection_log_path"),
        ({"stock": {"dir": "../outside"}}, "stock.dir"),
        ({"stock": {"dir": "tmp/stock"}}, "stock.dir must stay under"),
        ({"stock": {"filename_template": "../{song_id}.{ext}"}}, "basename"),
        ({"stock": {"filename_template": "{missing}.{ext}"}}, "unsupported placeholder"),
    ],
)
def test_path_and_template_config_is_rejected(tmp_path, monkeypatch, override, match):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": "[Verse]\nhello"}],
    )
    _write_audio(collection, "01a-Dawn Groove.mp3")
    _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)
    cfg = _cfg()
    cfg.update(override)

    with pytest.raises(ValidationError, match=match):
        suno_select_tracks.select_suno_tracks(collection, cfg)


def test_main_uses_explicit_collection_and_reports_success(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    _write_audio(collection, "01a-Dawn Groove.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)
    monkeypatch.setattr(suno_select_tracks, "load_skill_config", lambda _: _cfg())
    monkeypatch.setattr(sys, "argv", ["yt-suno-select-tracks", str(collection)])

    assert suno_select_tracks.main() == 0
    assert "[yt-suno-select-tracks]" in capsys.readouterr().out


def test_main_uses_cwd_and_dry_run(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    source = _write_audio(collection, "01a-Dawn Groove.mp3")
    monkeypatch.setattr(suno_select_tracks, "probe_duration", lambda _: 120.0)
    monkeypatch.setattr(suno_select_tracks, "load_skill_config", lambda _: _cfg())
    monkeypatch.setattr(sys, "argv", ["yt-suno-select-tracks", "--dry-run"])
    monkeypatch.chdir(collection)

    assert suno_select_tracks.main() == 0
    assert source.exists()
    assert "dry_run=true" in capsys.readouterr().out


def test_main_returns_1_and_stderr_on_validation_error(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    _write_audio(collection, "loose-download.mp3")
    monkeypatch.setattr(suno_select_tracks, "load_skill_config", lambda _: _cfg())
    monkeypatch.setattr(sys, "argv", ["yt-suno-select-tracks", str(collection)])

    assert suno_select_tracks.main() == 1
    assert "ERROR:" in capsys.readouterr().err


def test_project_scripts_registers_suno_select_tracks_entrypoint():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert (
        pyproject["project"]["scripts"]["yt-suno-select-tracks"]
        == "youtube_automation.scripts.suno_select_tracks:main"
    )
