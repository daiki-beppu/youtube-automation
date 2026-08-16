from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from youtube_automation.application import master_audio_review
from youtube_automation.core.errors import ReviewError
from youtube_automation.infrastructure.browser.selection_broker import BrokerSelection

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "001-rain-collection"
    master = collection / "01-master"
    master.mkdir(parents=True)
    (master / "raw.wav").write_bytes(b"raw-audio")
    (master / ".selection.log").write_text("selected: track-01.wav\n", encoding="utf-8")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "prepared",
                "assets": {"raw_master": "raw.wav", "master_audio": None},
                "future": {"keep": True},
            }
        ),
        encoding="utf-8",
    )
    return collection


def _state(collection: Path) -> dict[str, object]:
    return json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))


def test_raw_master_review_shows_player_metadata_and_adopts_after_web_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection = _collection(tmp_path)
    monkeypatch.setattr(master_audio_review, "probe_duration", lambda _path: 125.5)
    monkeypatch.setattr(master_audio_review, "open_local_file", lambda _path: True)

    class Broker:
        def __init__(self, manifest):
            self.manifest = manifest
            self.endpoint = f"http://127.0.0.1:43210/select/{manifest.token}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def wait(self, *, timeout: float):
            return BrokerSelection("worktree:raw.wav", self.manifest.artifact_digest)

    monkeypatch.setattr(master_audio_review, "SelectionBroker", Broker)

    result = master_audio_review.review_and_finalize_master_audio(
        collection,
        skip_manual_mastering=True,
        skip_audio_approval=False,
        transport="web",
        candidate_id=None,
        main_repo_root=None,
        now=NOW,
    )

    html = (collection / "tmp/reviews/master-audio.html").read_text(encoding="utf-8")
    assert result.status == "selected"
    assert '<audio src="file:' in html
    for value in ("worktree:raw.wav", "raw master直採用", "125.50秒", "selected: track-01.wav"):
        assert value in html
    state = _state(collection)
    assert state["phase"] == "mastered"
    assert state["assets"]["master_audio"] == "raw.wav"
    assert state["future"] == {"keep": True}


def test_same_name_candidates_keep_source_ids_and_copy_selected_main_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection = _collection(tmp_path)
    (collection / "01-master/final.wav").write_bytes(b"worktree-final")
    main_root = tmp_path / "main"
    main_master = main_root / "collections/planning" / collection.name / "01-master"
    main_master.mkdir(parents=True)
    (main_master / "final.wav").write_bytes(b"main-final")
    monkeypatch.setattr(master_audio_review, "probe_duration", lambda _path: 60.0)

    snapshot = master_audio_review.build_master_audio_review_snapshot(
        collection,
        skip_manual_mastering=False,
        main_repo_root=main_root,
        now=NOW,
    )

    assert tuple(candidate.candidate_id for candidate in snapshot.candidates) == (
        "worktree:final.wav",
        "main:final.wav",
    )
    master_audio_review.finalize_master_audio_selection(
        collection,
        skip_manual_mastering=False,
        candidate_id="main:final.wav",
        source="terminal",
        expected_artifact_digest=snapshot.manifest.artifact_digest,
        main_repo_root=main_root,
    )
    assert (collection / "01-master/final.wav").read_bytes() == b"main-final"
    assert _state(collection)["assets"]["master_audio"] == "final.wav"


def test_probe_failure_keeps_state_and_does_not_render_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _collection(tmp_path)
    before = (collection / "workflow-state.json").read_bytes()
    monkeypatch.setattr(master_audio_review, "probe_duration", lambda _path: None)
    monkeypatch.setattr(master_audio_review, "open_local_file", lambda _path: pytest.fail("must not open"))

    with pytest.raises(ReviewError, match="ffprobe"):
        master_audio_review.review_and_finalize_master_audio(
            collection,
            skip_manual_mastering=True,
            skip_audio_approval=False,
            transport="web",
            candidate_id=None,
            main_repo_root=None,
            now=NOW,
        )

    assert (collection / "workflow-state.json").read_bytes() == before
    assert not (collection / "tmp").exists()


def test_skip_audio_approval_adopts_single_candidate_without_html_or_broker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection = _collection(tmp_path)
    monkeypatch.setattr(master_audio_review, "probe_duration", lambda _path: 60.0)
    monkeypatch.setattr(master_audio_review, "open_local_file", lambda _path: pytest.fail("must not open"))
    monkeypatch.setattr(master_audio_review, "SelectionBroker", lambda *_args: pytest.fail("must not broker"))

    result = master_audio_review.review_and_finalize_master_audio(
        collection,
        skip_manual_mastering=True,
        skip_audio_approval=True,
        transport="web",
        candidate_id=None,
        main_repo_root=None,
        now=NOW,
    )

    assert result.status == "selected"
    assert not (collection / "tmp").exists()
    assert _state(collection)["assets"]["master_audio"] == "raw.wav"
