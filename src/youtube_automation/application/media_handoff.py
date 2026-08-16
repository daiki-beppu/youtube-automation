"""Manifest completion marker を使う境界メディア bundle 転送。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.core.errors import MediaHandoffNotFoundError, MediaStoreError, ValidationError
from youtube_automation.domains.media_handoff_manifest import (
    MANIFEST_NAME,
    HandoffFile,
    HandoffIdentity,
    HandoffManifest,
)
from youtube_automation.domains.media_store import (
    MediaKey,
    MediaObjectMetadata,
    MediaStore,
    validate_media_relative_path,
)
from youtube_automation.infrastructure.media_store import (
    publish_staged_files,
    require_regular_source,
    sha256_file,
)


@dataclass(frozen=True)
class HandoffSource:
    source: Path
    relative_path: str

    def __post_init__(self) -> None:
        try:
            validate_media_relative_path("relative_path", self.relative_path)
        except ValidationError as exc:
            raise MediaStoreError(f"受け渡し source path が不正です: {self.relative_path!r}") from exc
        if self.relative_path == MANIFEST_NAME:
            raise MediaStoreError(f"{MANIFEST_NAME!r} は completion marker 用に予約されています")


def _key(identity: HandoffIdentity, relative_path: str) -> MediaKey:
    return MediaKey(identity.channel, identity.collection, identity.handoff, relative_path)


def _assert_metadata(
    expected: HandoffFile | MediaObjectMetadata,
    actual: MediaObjectMetadata | None,
    *,
    object_path: str,
    operation: str,
) -> None:
    if actual is None or actual.size != expected.size or actual.sha256 != expected.sha256:
        raise MediaStoreError(
            f"受け渡し object {operation} metadata/checksum が manifest と一致しません: {object_path}"
        )


def _assert_file(expected: HandoffFile, path: Path, *, operation: str) -> None:
    size, checksum = sha256_file(path)
    if size != expected.size or checksum != expected.sha256:
        raise MediaStoreError(f"受け渡し object {operation} content checksum が一致しません: {expected.path}")


def _manifest_file(path: Path) -> MediaObjectMetadata:
    size, checksum = sha256_file(path)
    return MediaObjectMetadata(size, checksum)


def _build_manifest(identity: HandoffIdentity, sources: tuple[HandoffSource, ...]) -> HandoffManifest:
    files: list[HandoffFile] = []
    for source in sources:
        require_regular_source(source.source)
        size, checksum = sha256_file(source.source)
        files.append(HandoffFile(source.relative_path, size, checksum))
    return HandoffManifest.build(identity, tuple(files))


def push_handoff(
    store: MediaStore,
    identity: HandoffIdentity,
    sources: tuple[HandoffSource, ...],
) -> HandoffManifest:
    manifest = _build_manifest(identity, sources)
    sources_by_path = {source.relative_path: source.source for source in sources}
    with tempfile.TemporaryDirectory(prefix="yt-handoff-push-") as verification_directory:
        verification_root = Path(verification_directory)
        for entry in manifest.files:
            key = _key(identity, entry.path)
            pushed = store.push(sources_by_path[entry.path], key)
            _assert_metadata(entry, pushed, object_path=entry.path, operation="push")
            _assert_metadata(entry, store.metadata(key), object_path=entry.path, operation="remote")
            verification_path = verification_root.joinpath(*entry.path.split("/"))
            pulled = store.pull(key, verification_path)
            _assert_metadata(entry, pulled, object_path=entry.path, operation="verification pull")
            _assert_file(entry, verification_path, operation="verification")

        manifest_path = verification_root / MANIFEST_NAME
        manifest_path.write_bytes(manifest.to_json_bytes())
        expected_manifest = _manifest_file(manifest_path)
        manifest_key = _key(identity, MANIFEST_NAME)
        pushed_manifest = store.push(manifest_path, manifest_key)
        _assert_metadata(expected_manifest, pushed_manifest, object_path=MANIFEST_NAME, operation="manifest push")
        _assert_metadata(
            expected_manifest,
            store.metadata(manifest_key),
            object_path=MANIFEST_NAME,
            operation="manifest remote",
        )
        verification_manifest = verification_root / "verified-manifest.json"
        pulled_manifest = store.pull(manifest_key, verification_manifest)
        _assert_metadata(
            expected_manifest,
            pulled_manifest,
            object_path=MANIFEST_NAME,
            operation="manifest verification pull",
        )
        _assert_file(expected_manifest, verification_manifest, operation="manifest verification")
        if HandoffManifest.from_json_bytes(verification_manifest.read_bytes()) != manifest:
            raise MediaStoreError("受け渡し manifest の remote content が生成内容と一致しません")
    return manifest


def pull_handoff(store: MediaStore, identity: HandoffIdentity, destination: Path) -> HandoffManifest:
    manifest_key = _key(identity, MANIFEST_NAME)
    manifest_metadata = store.metadata(manifest_key)
    if manifest_metadata is None:
        raise MediaHandoffNotFoundError(
            f"受け渡し manifest が見つかりません: {identity.channel}/{identity.collection}/{identity.handoff}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yt-handoff-pull-", dir=destination.parent) as staging_directory:
        staging_root = Path(staging_directory)
        manifest_path = staging_root / MANIFEST_NAME
        pulled_manifest = store.pull(manifest_key, manifest_path)
        if pulled_manifest != manifest_metadata:
            raise MediaStoreError("受け渡し manifest metadata が読み取り中に変化しました")
        size, checksum = sha256_file(manifest_path)
        if size != manifest_metadata.size or checksum != manifest_metadata.sha256:
            raise MediaStoreError("受け渡し manifest content checksum が一致しません")
        manifest = HandoffManifest.from_json_bytes(manifest_path.read_bytes())
        if manifest.identity != identity:
            raise MediaStoreError("受け渡し manifest key と identity が一致しません")

        for entry in manifest.files:
            staging_path = staging_root.joinpath(*entry.path.split("/"))
            pulled = store.pull(_key(identity, entry.path), staging_path)
            _assert_metadata(entry, pulled, object_path=entry.path, operation="pull")
            _assert_file(entry, staging_path, operation="pull")

        publish_staged_files(staging_root, destination, tuple(entry.path for entry in manifest.files))
    return manifest
