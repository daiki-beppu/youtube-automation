from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.application.suno_download_handoff import SunoDownloadHandoff
from youtube_automation.core.errors import MediaStoreError, WorkflowStateError
from youtube_automation.domains.media_store import MediaKey, MediaObjectMetadata, MediaStore
from youtube_automation.domains.notifications import NotificationEventKind
from youtube_automation.infrastructure.media_store.local import LocalMediaStore


class RecordingStore:
    def __init__(self, delegate: MediaStore, *, fail_manifest_once: bool = False) -> None:
        self.delegate = delegate
        self.fail_manifest_once = fail_manifest_once
        self.pushes: list[str] = []

    def push(self, source: Path, key: MediaKey) -> MediaObjectMetadata:
        self.pushes.append(key.as_posix())
        if key.name == "manifest.json" and self.fail_manifest_once:
            self.fail_manifest_once = False
            raise MediaStoreError("fixture manifest interruption")
        return self.delegate.push(source, key)

    def pull(self, key: MediaKey, destination: Path) -> MediaObjectMetadata:
        return self.delegate.pull(key, destination)

    def exists(self, key: MediaKey) -> bool:
        return self.delegate.exists(key)

    def metadata(self, key: MediaKey) -> MediaObjectMetadata | None:
        return self.delegate.metadata(key)


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "20260816-clm-rainy-jazz-collection"
    music = collection / "02-Individual-music"
    music.mkdir(parents=True)
    (music / "01a-Rainy Jazz 夜.mp3").write_bytes(b"first")
    (music / "01b-Rainy Jazz 夜.mp3").write_bytes(b"second")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "prepared",
                "planning": {"music": {"engine": "suno"}},
                "assets": {"music_downloaded": True},
                "future": {"keep": True},
            }
        ),
        encoding="utf-8",
    )
    return collection


def test_complete_pushes_manifest_then_records_cloud_owner_and_emits_event(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    store = RecordingStore(LocalMediaStore(tmp_path / "remote"))
    events = []
    handoff = SunoDownloadHandoff(store=store, channel="002ch", on_event=events.append)

    result = handoff.complete(collection)

    assert store.pushes[-1] == result.manifest_key
    assert result.manifest_key == "002ch/20260816-clm-rainy-jazz-collection/suno-download/manifest.json"
    assert result.already_completed is False
    state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "cloud_owned"
    assert state["handoff"] == {
        "point": "suno_download",
        "owner": "cloud",
        "manifest_key": result.manifest_key,
        "root_sha256": result.root_sha256,
    }
    assert state["future"] == {"keep": True}
    assert len(events) == 1
    assert events[0].kind is NotificationEventKind.HANDOFF_COMPLETED
    assert result.manifest_key in events[0].detail


def test_complete_reuses_verified_manifest_without_pushing_or_emitting_twice(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    store = RecordingStore(LocalMediaStore(tmp_path / "remote"))
    events = []
    handoff = SunoDownloadHandoff(store=store, channel="002ch", on_event=events.append)
    first = handoff.complete(collection)
    pushes_after_first = tuple(store.pushes)

    second = handoff.complete(collection)

    assert second.manifest_key == first.manifest_key
    assert second.root_sha256 == first.root_sha256
    assert second.already_completed is True
    assert tuple(store.pushes) == pushes_after_first
    assert len(events) == 1


def test_manifest_failure_keeps_prepared_state_and_retry_skips_verified_audio_objects(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    store = RecordingStore(LocalMediaStore(tmp_path / "remote"), fail_manifest_once=True)
    events = []
    handoff = SunoDownloadHandoff(store=store, channel="002ch", on_event=events.append)

    with pytest.raises(MediaStoreError, match="fixture manifest interruption"):
        handoff.complete(collection)

    state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "prepared"
    first_attempt_pushes = tuple(store.pushes)
    assert not events

    result = handoff.complete(collection)

    assert result.already_completed is False
    audio_keys = [key for key in store.pushes if key != result.manifest_key]
    assert len(audio_keys) == 2
    assert len(first_attempt_pushes) == 3
    assert len(events) == 1


def test_complete_rejects_invalid_state_before_remote_write(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = "planning"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    store = RecordingStore(LocalMediaStore(tmp_path / "remote"))
    handoff = SunoDownloadHandoff(store=store, channel="002ch")

    with pytest.raises(WorkflowStateError, match="requires phase prepared"):
        handoff.complete(collection)

    assert store.pushes == []
