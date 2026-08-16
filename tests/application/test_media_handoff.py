from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.application.media_handoff import HandoffSource, pull_handoff, push_handoff
from youtube_automation.core.errors import MediaHandoffNotFoundError, MediaStoreError
from youtube_automation.domains.media_handoff_manifest import (
    MANIFEST_NAME,
    HandoffFile,
    HandoffIdentity,
    HandoffManifest,
)
from youtube_automation.domains.media_store import MediaKey, MediaObjectMetadata, MediaStore
from youtube_automation.infrastructure.media_store.local import LocalMediaStore


class RecordingStore:
    def __init__(self, delegate: MediaStore) -> None:
        self.delegate = delegate
        self.pushes: list[str] = []
        self.pulls: list[str] = []

    def push(self, source: Path, key: MediaKey) -> MediaObjectMetadata:
        self.pushes.append(key.name)
        return self.delegate.push(source, key)

    def pull(self, key: MediaKey, destination: Path) -> MediaObjectMetadata:
        self.pulls.append(key.name)
        return self.delegate.pull(key, destination)

    def exists(self, key: MediaKey) -> bool:
        return self.delegate.exists(key)

    def metadata(self, key: MediaKey) -> MediaObjectMetadata | None:
        return self.delegate.metadata(key)


def _identity() -> HandoffIdentity:
    return HandoffIdentity("ambient-lab", "rain-night", "video-upload")


def _sources(tmp_path: Path) -> tuple[HandoffSource, ...]:
    video = tmp_path / "Master.mp4"
    audio = tmp_path / "master.wav"
    video.write_bytes(b"video-payload")
    audio.write_bytes(b"audio-payload")
    return (
        HandoffSource(video, "video/Master.mp4"),
        HandoffSource(audio, "audio/master.wav"),
    )


def _manifest_key() -> MediaKey:
    identity = _identity()
    return MediaKey(identity.channel, identity.collection, identity.handoff, MANIFEST_NAME)


def test_push_verifies_every_object_then_puts_manifest_as_the_last_completion_marker(tmp_path: Path) -> None:
    # R2 の read-after-write 強整合により、この最後の PUT が bundle 完了の観測点になる。
    store = RecordingStore(LocalMediaStore(tmp_path / "store"))

    manifest = push_handoff(store, _identity(), _sources(tmp_path))

    assert store.pushes == ["audio/master.wav", "video/Master.mp4", MANIFEST_NAME]
    assert store.pulls == ["audio/master.wav", "video/Master.mp4", MANIFEST_NAME]
    assert store.metadata(_manifest_key()) is not None
    assert HandoffManifest.from_json_bytes((tmp_path / "store" / _manifest_key().as_posix()).read_bytes()) == manifest


def test_failed_object_content_verification_never_publishes_the_manifest(tmp_path: Path) -> None:
    class CorruptingStore(RecordingStore):
        def pull(self, key: MediaKey, destination: Path) -> MediaObjectMetadata:
            metadata = super().pull(key, destination)
            if key.name != MANIFEST_NAME:
                destination.write_bytes(b"corrupt")
            return metadata

    store = CorruptingStore(LocalMediaStore(tmp_path / "store"))

    with pytest.raises(MediaStoreError, match="content"):
        push_handoff(store, _identity(), _sources(tmp_path))
    assert store.metadata(_manifest_key()) is None


def test_pull_treats_objects_without_a_manifest_as_not_found_and_keeps_local_files(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    source = tmp_path / "remote.mp4"
    source.write_bytes(b"partial-upload")
    identity = _identity()
    store.push(source, MediaKey(identity.channel, identity.collection, identity.handoff, "video/Master.mp4"))
    destination = tmp_path / "destination"
    destination.mkdir()
    existing = destination / "existing.txt"
    existing.write_text("keep", encoding="utf-8")

    with pytest.raises(MediaHandoffNotFoundError):
        pull_handoff(store, identity, destination)
    assert existing.read_text(encoding="utf-8") == "keep"
    assert not (destination / "video" / "Master.mp4").exists()


def test_pull_uses_only_manifest_entries_and_reconstructs_nested_files(tmp_path: Path) -> None:
    store = RecordingStore(LocalMediaStore(tmp_path / "store"))
    manifest = push_handoff(store, _identity(), _sources(tmp_path))
    store.pulls.clear()
    destination = tmp_path / "destination"

    pulled = pull_handoff(store, _identity(), destination)

    assert pulled == manifest
    assert store.pulls == [MANIFEST_NAME, "audio/master.wav", "video/Master.mp4"]
    assert (destination / "audio" / "master.wav").read_bytes() == b"audio-payload"
    assert (destination / "video" / "Master.mp4").read_bytes() == b"video-payload"


def test_pull_rejects_a_manifest_stored_under_a_different_identity_key(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    wrong_manifest = HandoffManifest.build(
        HandoffIdentity("other-channel", "rain-night", "video-upload"),
        (HandoffFile("video/Master.mp4", 1, "a" * 64),),
    )
    manifest_source = tmp_path / MANIFEST_NAME
    manifest_source.write_bytes(wrong_manifest.to_json_bytes())
    store.push(manifest_source, _manifest_key())
    destination = tmp_path / "destination"

    with pytest.raises(MediaStoreError, match="identity"):
        pull_handoff(store, _identity(), destination)
    assert not destination.exists()


def test_pull_checksum_mismatch_fails_closed_and_preserves_existing_outputs(tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    store = LocalMediaStore(store_root)
    push_handoff(store, _identity(), _sources(tmp_path))
    remote_video = store_root / _identity().channel / _identity().collection / _identity().handoff / "video/Master.mp4"
    remote_video.write_bytes(b"tampered")
    destination = tmp_path / "destination"
    existing_video = destination / "video" / "Master.mp4"
    existing_video.parent.mkdir(parents=True)
    existing_video.write_bytes(b"existing-local-video")
    unrelated = destination / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")

    with pytest.raises(MediaStoreError, match="checksum"):
        pull_handoff(store, _identity(), destination)
    assert existing_video.read_bytes() == b"existing-local-video"
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_pull_publish_failure_rolls_back_files_already_replaced(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    push_handoff(store, _identity(), _sources(tmp_path))
    destination = tmp_path / "destination"
    existing_audio = destination / "audio" / "master.wav"
    existing_audio.parent.mkdir(parents=True)
    existing_audio.write_bytes(b"existing-local-audio")
    invalid_video_target = destination / "video" / "Master.mp4"
    invalid_video_target.mkdir(parents=True)

    with pytest.raises(MediaStoreError, match="通常ファイル"):
        pull_handoff(store, _identity(), destination)
    assert existing_audio.read_bytes() == b"existing-local-audio"
    assert invalid_video_target.is_dir()
