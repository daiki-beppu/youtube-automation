from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

from youtube_automation.domains.suno import selection as suno_track_selection
from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.scripts import suno_select_tracks


def _make_collection(tmp_path: Path, prompts: object) -> Path:
    collection = tmp_path / "collections" / "planning" / "20260629-test-collection"
    (collection / "20-documentation").mkdir(parents=True)
    (collection / "02-Individual-music").mkdir()
    (collection / "01-master").mkdir()
    (collection / "20-documentation" / "suno-prompts.json").write_text(
        json.dumps(prompts),
        encoding="utf-8",
    )
    return collection


def _write_audio(collection: Path, name: str, content: bytes = b"audio") -> Path:
    path = collection / "02-Individual-music" / name
    path.write_bytes(content)
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
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    result = suno_track_selection.select_suno_tracks(collection, _cfg())

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
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    result = suno_track_selection.select_suno_tracks(collection, _cfg())

    music_files = sorted(p.name for p in (collection / "02-Individual-music").iterdir() if p.is_file())
    assert music_files == ["01a-Dawn Groove.mp3", "01b-Dawn Groove.mp3"]
    assert result.winners == []
    assert result.stocked == []
    assert result.mode_counts == {"vocal": 0, "instrumental": 1}


def test_prompt_response_envelope_keeps_track_selection_compatible(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        {
            "entries": [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello dawn"}],
            "duration_filter": {"min_sec": 60, "max_sec": 300},
        },
    )
    _write_audio(collection, "01a-Dawn Song.mp3")
    _write_audio(collection, "01b-Dawn Song.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    result = suno_track_selection.select_suno_tracks(collection, _cfg())

    music_files = sorted(p.name for p in (collection / "02-Individual-music").iterdir() if p.is_file())
    assert music_files == ["01-Dawn Song.mp3"]
    assert len(result.winners) == 1
    assert len(result.stocked) == 1


def test_duration_filter_stocks_too_short_and_keeps_survivor(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 120.0

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)

    result = suno_track_selection.select_suno_tracks(collection, _cfg())

    music_files = sorted(p.name for p in (collection / "02-Individual-music").iterdir() if p.is_file())
    assert music_files == [survivor.name]
    assert len(result.dropped) == 1
    assert len(result.stocked) == 1
    assert result.stocked[0].exists()
    assert "Dawn Groove" in result.dropped[0].title


def test_dry_run_reports_under_min_candidates_with_threshold(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3")

    def fake_probe(path: Path) -> float:
        return 44.5 if path == short else 120.0

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)

    result = suno_track_selection.select_suno_tracks(collection, _cfg(), dry_run=True)

    assert short.exists()
    assert survivor.exists()
    assert len(result.dropped) == 1
    assert not (collection / "01-master" / ".selection.log").exists()
    stdout = capsys.readouterr().out
    assert "[dropped_under_min]" in stdout
    assert "01 a Dawn Groove duration=44.50s min_song_sec=45.00s source=01a-Dawn Groove.mp3" in stdout
    assert "[dropped_duration]" in stdout
    assert "01 a Dawn Groove duration=44.50s source=01a-Dawn Groove.mp3" in stdout


def test_all_candidates_dropped_fails_loud(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    first = _write_audio(collection, "01a-Dawn Groove.mp3")
    second = _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 20.0)

    with pytest.raises(ValidationError, match="採用候補が 0 件"):
        suno_track_selection.select_suno_tracks(collection, _cfg())

    assert first.exists()
    assert second.exists()
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
    assert not (collection / "01-master" / ".selection.log").exists()


def test_all_candidates_over_max_without_recovery_fails_loud(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    second = _write_audio(collection, "01b-Red Pressure.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 479.4)

    with pytest.raises(ValidationError, match="採用候補が 0 件"):
        suno_track_selection.select_suno_tracks(collection, _cfg())

    assert first.exists()
    assert second.exists()
    assert not (collection / "workflow-state.json").exists()
    assert not (collection / "01-master" / ".selection.log").exists()


def test_all_candidates_over_max_can_keep_shortest_with_explicit_recovery(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    _write_audio(collection, "01b-Red Pressure.mp3")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "updated_at": "2000-01-01T00:00:00Z",
                "assets": {"raw_master": "master.mp3"},
            }
        ),
        encoding="utf-8",
    )

    def fake_probe(path: Path) -> float:
        return 479.4 if path == first else 481.2

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)

    result = suno_track_selection.select_suno_tracks(
        collection,
        _cfg(),
        allow_best_effort_over_max=True,
    )

    assert sorted(p.name for p in (collection / "02-Individual-music").iterdir() if p.is_file()) == [
        "01-Red Pressure.mp3"
    ]
    assert len(result.exceptions_over_limit) == 1
    assert result.exceptions_over_limit[0].candidate.path == first
    assert len(result.stocked) == 1

    log_text = (collection / "01-master" / ".selection.log").read_text(encoding="utf-8")
    assert "[exceptions_over_limit]" in log_text
    assert "01 a Red Pressure duration=479.40s max_song_sec=300.00s source=01a-Red Pressure.mp3" in log_text

    workflow_state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    assert workflow_state["assets"] == {"raw_master": "master.mp3"}
    selection_state = workflow_state["music_pair_selection"]
    assert workflow_state["updated_at"] != "2000-01-01T00:00:00Z"
    assert workflow_state["updated_at"] == selection_state["updated_at"]
    assert selection_state["exceptions_over_limit_count"] == 1
    exception_state = selection_state["exceptions_over_limit"][0]
    assert exception_state["title"] == "Red Pressure"
    assert exception_state["source"] == "01a-Red Pressure.mp3"
    assert exception_state["duration_sec"] == 479.4
    assert exception_state["max_song_sec"] == 300.0
    assert exception_state["reason"] == "all_candidates_over_max_song_sec; selected_shortest_over_limit"


def test_best_effort_over_max_requires_all_dropped_candidates_to_be_over_max(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    short = _write_audio(collection, "01a-Red Pressure.mp3")
    long = _write_audio(collection, "01b-Red Pressure.mp3")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 479.4

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)

    with pytest.raises(ValidationError, match="採用候補が 0 件"):
        suno_track_selection.select_suno_tracks(collection, _cfg(), allow_best_effort_over_max=True)

    assert short.exists()
    assert long.exists()
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
    assert not (collection / "workflow-state.json").exists()
    assert not (collection / "01-master" / ".selection.log").exists()


def test_best_effort_over_max_does_not_rescue_too_short_clips(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    first = _write_audio(collection, "01a-Dawn Groove.mp3")
    second = _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 20.0)

    with pytest.raises(ValidationError, match="採用候補が 0 件"):
        suno_track_selection.select_suno_tracks(collection, _cfg(), allow_best_effort_over_max=True)

    assert first.exists()
    assert second.exists()
    assert not (collection / "workflow-state.json").exists()


def test_best_effort_over_max_does_not_rescue_probe_failures(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    second = _write_audio(collection, "01b-Red Pressure.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: None)

    with pytest.raises(ValidationError, match="duration の probe に失敗"):
        suno_track_selection.select_suno_tracks(collection, _cfg(), allow_best_effort_over_max=True)

    assert first.exists()
    assert second.exists()
    assert not (collection / "workflow-state.json").exists()
    assert not (collection / "01-master" / ".selection.log").exists()


def test_invalid_workflow_state_fails_before_best_effort_side_effects(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    second = _write_audio(collection, "01b-Red Pressure.mp3")
    (collection / "workflow-state.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 479.4)
    cfg = _cfg(selection_log_path="new-log-dir/.selection.log")

    with pytest.raises(ValidationError, match="workflow-state.json を読み取れませんでした"):
        suno_track_selection.select_suno_tracks(collection, cfg, allow_best_effort_over_max=True)

    assert first.exists()
    assert second.exists()
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
    assert (collection / "workflow-state.json").read_text(encoding="utf-8") == "{broken"
    assert not (collection / "01-master" / ".selection.log").exists()
    assert not (collection / "new-log-dir").exists()


def test_non_object_workflow_state_fails_before_best_effort_side_effects(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    second = _write_audio(collection, "01b-Red Pressure.mp3")
    (collection / "workflow-state.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 479.4)

    with pytest.raises(ValidationError, match="workflow-state.json の root は object"):
        suno_track_selection.select_suno_tracks(collection, _cfg(), allow_best_effort_over_max=True)

    assert first.exists()
    assert second.exists()
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
    assert (collection / "workflow-state.json").read_text(encoding="utf-8") == "[]"
    assert not (collection / "01-master" / ".selection.log").exists()


def test_workflow_state_directory_fails_before_best_effort_side_effects(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    second = _write_audio(collection, "01b-Red Pressure.mp3")
    (collection / "workflow-state.json").mkdir()
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 479.4)
    cfg = _cfg(selection_log_path="new-log-dir/.selection.log")

    with pytest.raises(ValidationError, match="workflow-state.json は file"):
        suno_track_selection.select_suno_tracks(collection, cfg, allow_best_effort_over_max=True)

    assert first.exists()
    assert second.exists()
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
    assert (collection / "workflow-state.json").is_dir()
    assert not (collection / "new-log-dir").exists()
    assert not (collection / "01-master" / ".selection.log").exists()


def test_success_without_over_max_exception_does_not_read_or_modify_workflow_state(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello dawn"}],
    )
    _write_audio(collection, "01a-Dawn Song.mp3")
    _write_audio(collection, "01b-Dawn Song.mp3")
    stale_state = "{broken stale state"
    (collection / "workflow-state.json").write_text(stale_state, encoding="utf-8")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    result = suno_track_selection.select_suno_tracks(collection, _cfg())

    assert result.exceptions_over_limit == []
    assert (collection / "workflow-state.json").read_text(encoding="utf-8") == stale_state
    log_text = (collection / "01-master" / ".selection.log").read_text(encoding="utf-8")
    assert "exceptions_over_limit=0" in log_text


def test_best_effort_over_max_rejects_workflow_state_symlink_before_side_effects(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    second = _write_audio(collection, "01b-Red Pressure.mp3")
    external_state = tmp_path / "external-state.json"
    external_state.write_text(json.dumps({"assets": {"raw_master": "outside.mp3"}}), encoding="utf-8")
    (collection / "workflow-state.json").symlink_to(external_state)
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 479.4)

    with pytest.raises(ValidationError, match="workflow-state.json must not be a symlink"):
        suno_track_selection.select_suno_tracks(collection, _cfg(), allow_best_effort_over_max=True)

    assert first.exists()
    assert second.exists()
    assert (collection / "workflow-state.json").is_symlink()
    assert json.loads(external_state.read_text(encoding="utf-8")) == {"assets": {"raw_master": "outside.mp3"}}
    assert not (collection / "01-master" / ".selection.log").exists()


def test_best_effort_dry_run_reports_exception_without_side_effects(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    second = _write_audio(collection, "01b-Red Pressure.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 479.4)

    result = suno_track_selection.select_suno_tracks(
        collection,
        _cfg(),
        dry_run=True,
        allow_best_effort_over_max=True,
    )

    assert first.exists()
    assert second.exists()
    assert result.exceptions_over_limit[0].candidate.path == first
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
    assert not (collection / "workflow-state.json").exists()
    assert not (collection / "01-master" / ".selection.log").exists()
    stdout = capsys.readouterr().out
    assert "[exceptions_over_limit]" in stdout
    assert "source=01a-Red Pressure.mp3" in stdout
    assert "reason=all_candidates_over_max_song_sec; selected_shortest_over_limit" in stdout
    assert "min_song_sec=" not in stdout


def test_never_mode_skips_selection(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello"}],
    )
    _write_audio(collection, "01a-Dawn Song.mp3")
    _write_audio(collection, "01b-Dawn Song.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    result = suno_track_selection.select_suno_tracks(collection, _cfg(mode="never"))

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

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)

    result = suno_track_selection.select_suno_tracks(collection, _cfg(out_of_range_action="delete"))

    assert not short.exists()
    assert survivor.exists()
    assert result.deleted == [short]
    assert result.stocked == []


def test_best_effort_over_max_delete_keeps_winner_and_deletes_non_winner(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3")
    second = _write_audio(collection, "01b-Red Pressure.mp3")

    def fake_probe(path: Path) -> float:
        return 479.4 if path == first else 481.2

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)

    result = suno_track_selection.select_suno_tracks(
        collection,
        _cfg(out_of_range_action="delete"),
        allow_best_effort_over_max=True,
    )

    winner = collection / "02-Individual-music" / "01-Red Pressure.mp3"
    assert winner.exists()
    assert not first.exists()
    assert not second.exists()
    assert result.deleted == [second]
    assert result.stocked == []
    assert result.exceptions_over_limit[0].candidate.path == first

    log_text = (collection / "01-master" / ".selection.log").read_text(encoding="utf-8")
    assert "source=01a-Red Pressure.mp3" in log_text
    assert str(second) in log_text

    workflow_state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    exception_state = workflow_state["music_pair_selection"]["exceptions_over_limit"][0]
    assert exception_state["source"] == "01a-Red Pressure.mp3"
    assert exception_state["duration_sec"] == 479.4


def test_dry_run_does_not_move_delete_or_write_log(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello dawn"}],
    )
    first = _write_audio(collection, "01a-Dawn Song.mp3")
    second = _write_audio(collection, "01b-Dawn Song.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    result = suno_track_selection.select_suno_tracks(collection, _cfg(), dry_run=True)

    assert first.exists()
    assert second.exists()
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
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
    existing = (
        tmp_path
        / "assets"
        / "stock"
        / "music"
        / "b-side"
        / ("20260629-test-collection__01a-dawn-groove__dawn-groove.mp3")
    )
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 120.0

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)
    cfg = _cfg()
    cfg["stock"]["on_duplicate"] = "fail"

    with pytest.raises(ValidationError, match="stock destination already exists"):
        suno_track_selection.select_suno_tracks(collection, cfg)

    assert short.exists()
    assert survivor.exists()
    assert existing.read_bytes() == b"existing"


def test_stock_duplicate_skip_keeps_existing_stock_and_removes_source(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3", b"new")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3", b"survivor")
    existing = (
        tmp_path
        / "assets"
        / "stock"
        / "music"
        / "b-side"
        / ("20260629-test-collection__01a-dawn-groove__dawn-groove.mp3")
    )
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 120.0

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)

    result = suno_track_selection.select_suno_tracks(collection, _cfg())

    assert not short.exists()
    assert survivor.exists()
    assert existing.read_bytes() == b"existing"
    assert result.stocked == [existing]
    assert str(existing) in (collection / "01-master" / ".selection.log").read_text(encoding="utf-8")


def test_stock_duplicate_overwrite_replaces_existing_stock(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3", b"new")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3", b"survivor")
    existing = (
        tmp_path
        / "assets"
        / "stock"
        / "music"
        / "b-side"
        / ("20260629-test-collection__01a-dawn-groove__dawn-groove.mp3")
    )
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 120.0

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)
    cfg = _cfg()
    cfg["stock"]["on_duplicate"] = "overwrite"

    result = suno_track_selection.select_suno_tracks(collection, cfg)

    assert not short.exists()
    assert survivor.exists()
    assert existing.read_bytes() == b"new"
    assert result.stocked == [existing]
    assert str(existing) in (collection / "01-master" / ".selection.log").read_text(encoding="utf-8")


def test_stock_duplicate_overwrite_rollback_restores_existing_when_source_move_fails(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3", b"new")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3", b"survivor")
    existing = (
        tmp_path
        / "assets"
        / "stock"
        / "music"
        / "b-side"
        / ("20260629-test-collection__01a-dawn-groove__dawn-groove.mp3")
    )
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")

    def fake_probe(path: Path) -> float:
        return 20.0 if path == short else 120.0

    original_safe_move = suno_track_selection._safe_move

    def fail_source_to_stock(source: Path, destination: Path) -> None:
        if source == short and destination == existing:
            raise OSError("injected source move failure")
        original_safe_move(source, destination)

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)
    monkeypatch.setattr(suno_track_selection, "_safe_move", fail_source_to_stock)
    cfg = _cfg()
    cfg["stock"]["on_duplicate"] = "overwrite"

    with pytest.raises(OSError, match="injected source move failure"):
        suno_track_selection.select_suno_tracks(collection, cfg)

    assert short.exists()
    assert survivor.exists()
    assert existing.read_bytes() == b"existing"
    assert not (collection / "01-master" / ".selection.log").exists()


def test_same_plan_duplicate_stock_fail_preserves_all_sources(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [
            {"name": "夜明け — Same", "lyrics": "[Verse]\nhello"},
            {"name": "夜明け — Same", "lyrics": "[Verse]\nhello again"},
        ],
    )
    files = [
        _write_audio(collection, "01a-Same.mp3"),
        _write_audio(collection, "01b-Same.mp3"),
        _write_audio(collection, "02a-Same.mp3"),
        _write_audio(collection, "02b-Same.mp3"),
    ]
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)
    cfg = _cfg()
    cfg["stock"]["filename_template"] = "same.{ext}"
    cfg["stock"]["on_duplicate"] = "fail"

    with pytest.raises(ValidationError, match="duplicate stock destination"):
        suno_track_selection.select_suno_tracks(collection, cfg)

    assert all(path.exists() for path in files)
    assert not (tmp_path / "assets" / "stock").exists()
    assert not (collection / "01-master" / ".selection.log").exists()


def test_apply_rollback_restores_files_when_winner_rename_fails(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello dawn"}],
    )
    first = _write_audio(collection, "01a-Dawn Song.mp3")
    second = _write_audio(collection, "01b-Dawn Song.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)
    original_rename = Path.rename

    def fail_winner_rename(self: Path, target: Path) -> Path:
        if self.name == "01a-Dawn Song.mp3" and Path(target).name == "01-Dawn Song.mp3":
            raise OSError("injected rename failure")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_winner_rename)

    with pytest.raises(OSError, match="injected rename failure"):
        suno_track_selection.select_suno_tracks(collection, _cfg())

    assert first.exists()
    assert second.exists()
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
    assert not (collection / "01-master" / ".selection.log").exists()


def test_apply_rollback_restores_files_log_and_state_when_workflow_write_fails(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure rising"}],
    )
    first = _write_audio(collection, "01a-Red Pressure.mp3", b"first")
    second = _write_audio(collection, "01b-Red Pressure.mp3", b"second")
    workflow_state_path = collection / "workflow-state.json"
    original_state = {"assets": {"raw_master": "master.mp3"}}
    workflow_state_path.write_text(json.dumps(original_state), encoding="utf-8")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 479.4)

    def fail_atomic_json_write(target: Path, data: dict) -> None:
        raise OSError("injected workflow-state write failure")

    monkeypatch.setattr(suno_track_selection, "_atomic_json_write", fail_atomic_json_write)

    with pytest.raises(OSError, match="injected workflow-state write failure"):
        suno_track_selection.select_suno_tracks(collection, _cfg(), allow_best_effort_over_max=True)

    assert first.exists()
    assert second.exists()
    assert not (collection / "02-Individual-music" / "01-Red Pressure.mp3").exists()
    stock_root = tmp_path / "assets" / "stock"
    assert not stock_root.exists() or not any(path.is_file() for path in stock_root.rglob("*"))
    assert not (collection / "01-master" / ".selection.log").exists()
    assert json.loads(workflow_state_path.read_text(encoding="utf-8")) == original_state


def test_log_path_directory_fails_before_file_side_effects(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Song", "lyrics": "[Verse]\nhello dawn"}],
    )
    first = _write_audio(collection, "01a-Dawn Song.mp3")
    second = _write_audio(collection, "01b-Dawn Song.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    with pytest.raises(ValidationError, match="selection log path is a directory"):
        suno_track_selection.select_suno_tracks(collection, _cfg(selection_log_path="01-master"))

    assert first.exists()
    assert second.exists()
    assert not (tmp_path / "assets" / "stock").exists()


def test_missing_initial_second_clip_fails_before_duration_filter(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    source = _write_audio(collection, "01a-Dawn Groove.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    with pytest.raises(ValidationError, match="prompt ごとに 2 clip 必要"):
        suno_track_selection.select_suno_tracks(collection, _cfg())

    assert source.exists()
    assert not (collection / "01-master" / ".selection.log").exists()


def test_invalid_audio_filename_fails_loud(tmp_path, monkeypatch):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    invalid = _write_audio(collection, "loose-download.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)

    with pytest.raises(ValidationError, match="命名規則に合わない音源"):
        suno_track_selection.select_suno_tracks(collection, _cfg())

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
    _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)
    cfg = _cfg()
    cfg.update(override)

    with pytest.raises(ValidationError, match=match):
        suno_track_selection.select_suno_tracks(collection, cfg)


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
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)
    cfg = _cfg()
    cfg.update(override)

    with pytest.raises(ValidationError, match=match):
        suno_track_selection.select_suno_tracks(collection, cfg)


def test_main_uses_explicit_collection_and_reports_success(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    _write_audio(collection, "01a-Dawn Groove.mp3")
    _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)
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
    _write_audio(collection, "01b-Dawn Groove.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 120.0)
    monkeypatch.setattr(suno_select_tracks, "load_skill_config", lambda _: _cfg())
    monkeypatch.setattr(sys, "argv", ["yt-suno-select-tracks", "--dry-run"])
    monkeypatch.chdir(collection)

    assert suno_select_tracks.main() == 0
    assert source.exists()
    assert "dry_run=true" in capsys.readouterr().out


def test_main_dry_run_reports_under_min_summary_and_details(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Dawn Groove", "lyrics": ""}],
    )
    short = _write_audio(collection, "01a-Dawn Groove.mp3")
    survivor = _write_audio(collection, "01b-Dawn Groove.mp3")

    def fake_probe(path: Path) -> float:
        return 44.5 if path == short else 120.0

    monkeypatch.setattr(suno_track_selection, "probe_duration", fake_probe)
    monkeypatch.setattr(suno_select_tracks, "load_skill_config", lambda _: _cfg())
    monkeypatch.setattr(sys, "argv", ["yt-suno-select-tracks", "--dry-run", str(collection)])

    assert suno_select_tracks.main() == 0
    assert short.exists()
    assert survivor.exists()
    stdout = capsys.readouterr().out
    assert "dropped_under_min=1" in stdout
    assert "duration=44.50s min_song_sec=45.00s source=01a-Dawn Groove.mp3" in stdout


def test_main_passes_best_effort_over_max_flag(tmp_path, monkeypatch, capsys):
    collection = _make_collection(
        tmp_path,
        [{"name": "夜明け — Red Pressure", "lyrics": "[Verse]\npressure"}],
    )
    _write_audio(collection, "01a-Red Pressure.mp3")
    _write_audio(collection, "01b-Red Pressure.mp3")
    monkeypatch.setattr(suno_track_selection, "probe_duration", lambda _: 479.4)
    monkeypatch.setattr(suno_select_tracks, "load_skill_config", lambda _: _cfg())
    monkeypatch.setattr(
        sys,
        "argv",
        ["yt-suno-select-tracks", str(collection), "--allow-best-effort-over-max"],
    )

    assert suno_select_tracks.main() == 0
    assert "exceptions_over_limit=1" in capsys.readouterr().out


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
        == "youtube_automation.cli_entrypoints:yt_suno_select_tracks"
    )


def test_masterup_skill_documents_under_min_confirmation_gate():
    text = Path(".claude/skills/masterup/SKILL.md").read_text(encoding="utf-8")

    assert "uv run yt-suno-select-tracks --dry-run <collection-path>" in text
    assert "[dropped_under_min]" in text
    assert "source=<filename>" in text
    assert "duration=<sec>s" in text
    assert "min_song_sec=<sec>s" in text
    assert "続行する" in text
    assert "続行しない" in text
    assert "/suno-helper" in text
    assert "Step 5 へ進まない" in text
    assert "`pair_selection.max_song_sec` 超過だけの候補では、この確認プロンプトを出さない" in text
