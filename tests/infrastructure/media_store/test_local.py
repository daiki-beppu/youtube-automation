from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from youtube_automation.core.errors import MediaStoreError
from youtube_automation.domains.media_store import MediaKey
from youtube_automation.infrastructure.media_store.local import LocalMediaStore


def _key() -> MediaKey:
    return MediaKey("ambient-lab", "rain-night", "video-upload", "Master.mp4")


def test_push_pull_round_trip_preserves_checksum(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    payload = (b"streamed-media-payload" * 4096) + b"end"
    source.write_bytes(payload)
    store = LocalMediaStore(tmp_path / "store")

    pushed = store.push(source, _key())
    destination = tmp_path / "download" / "Master.mp4"
    pulled = store.pull(_key(), destination)

    expected_checksum = hashlib.sha256(payload).hexdigest()
    assert destination.read_bytes() == payload
    assert pushed.sha256 == pulled.sha256 == expected_checksum
    assert store.exists(_key()) is True
    assert store.metadata(_key()) == pushed


def test_missing_object_is_reported_without_creating_destination(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    destination = tmp_path / "download.bin"

    assert store.exists(_key()) is False
    assert store.metadata(_key()) is None
    with pytest.raises(MediaStoreError, match="見つかりません"):
        store.pull(_key(), destination)
    assert not destination.exists()


def test_push_rejects_a_symlink_source(tmp_path: Path) -> None:
    real_source = tmp_path / "real.bin"
    real_source.write_bytes(b"secret")
    linked_source = tmp_path / "linked.bin"
    linked_source.symlink_to(real_source)

    with pytest.raises(MediaStoreError, match="シンボリックリンク"):
        LocalMediaStore(tmp_path / "store").push(linked_source, _key())


def test_pull_rejects_a_symlink_in_the_destination_path(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = LocalMediaStore(tmp_path / "store")
    store.push(source, _key())
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(MediaStoreError, match="シンボリックリンク"):
        store.pull(_key(), linked_parent / "download.bin")
    assert not (outside / "download.bin").exists()


def test_push_rejects_a_symlink_below_the_store_root(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    root = tmp_path / "store"
    store = LocalMediaStore(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "ambient-lab").symlink_to(outside, target_is_directory=True)

    with pytest.raises(MediaStoreError, match="シンボリックリンク"):
        store.push(source, _key())
    assert list(outside.iterdir()) == []
