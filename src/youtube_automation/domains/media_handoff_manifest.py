"""境界メディア受け渡し manifest v1 の typed owner。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from youtube_automation.core.errors import MediaStoreError, ValidationError
from youtube_automation.domains.media_store import validate_media_relative_path, validate_media_segment

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_FIELDS = {"schema_version", "channel", "collection", "handoff", "files", "root_sha256"}
_FILE_FIELDS = {"path", "size", "sha256"}


def _manifest_error(detail: str) -> MediaStoreError:
    return MediaStoreError(f"受け渡し manifest v{MANIFEST_SCHEMA_VERSION} が不正です: {detail}")


def _validate_identifier(field: str, value: str) -> None:
    try:
        validate_media_segment(field, value)
    except ValidationError as exc:
        raise _manifest_error(field) from exc


def _validate_path(value: str) -> None:
    try:
        validate_media_relative_path("path", value)
    except ValidationError as exc:
        raise _manifest_error("path") from exc
    if value == MANIFEST_NAME:
        raise _manifest_error(f"path {MANIFEST_NAME!r} は completion marker 用に予約されています")


@dataclass(frozen=True)
class HandoffIdentity:
    channel: str
    collection: str
    handoff: str

    def __post_init__(self) -> None:
        for field in ("channel", "collection", "handoff"):
            _validate_identifier(field, getattr(self, field))


@dataclass(frozen=True)
class HandoffFile:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_path(self.path)
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise _manifest_error("size")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise _manifest_error("sha256")

    def to_json_value(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


def _root_sha256(files: tuple[HandoffFile, ...]) -> str:
    canonical = json.dumps(
        [entry.to_json_value() for entry in files],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class HandoffManifest:
    schema_version: int
    identity: HandoffIdentity
    files: tuple[HandoffFile, ...]
    root_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise _manifest_error("schema_version")
        if not self.files:
            raise _manifest_error("files は1件以上必要です")
        paths = [entry.path for entry in self.files]
        if len(paths) != len(set(paths)):
            raise _manifest_error("duplicate path")
        if paths != sorted(paths):
            raise _manifest_error("files は path 昇順の正準順序である必要があります")
        if not _SHA256_RE.fullmatch(self.root_sha256) or self.root_sha256 != _root_sha256(self.files):
            raise _manifest_error("root checksum")

    @classmethod
    def build(cls, identity: HandoffIdentity, files: tuple[HandoffFile, ...]) -> HandoffManifest:
        canonical_files = tuple(sorted(files, key=lambda entry: entry.path))
        return cls(
            schema_version=MANIFEST_SCHEMA_VERSION,
            identity=identity,
            files=canonical_files,
            root_sha256=_root_sha256(canonical_files),
        )

    def to_json_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "channel": self.identity.channel,
            "collection": self.identity.collection,
            "handoff": self.identity.handoff,
            "files": [entry.to_json_value() for entry in self.files],
            "root_sha256": self.root_sha256,
        }

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.to_json_value(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> HandoffManifest:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _manifest_error("JSON") from exc
        if not isinstance(value, dict) or set(value) != _MANIFEST_FIELDS:
            raise _manifest_error("top-level field")
        schema_version = value["schema_version"]
        if isinstance(schema_version, bool) or schema_version != MANIFEST_SCHEMA_VERSION:
            raise _manifest_error("schema_version")
        identity = _parse_identity(value)
        files = _parse_files(value["files"])
        root_sha256 = value["root_sha256"]
        if not isinstance(root_sha256, str):
            raise _manifest_error("root checksum")
        return cls(schema_version, identity, files, root_sha256)


def _parse_identity(value: dict[object, object]) -> HandoffIdentity:
    identifiers: dict[str, str] = {}
    for field in ("channel", "collection", "handoff"):
        item = value[field]
        if not isinstance(item, str):
            raise _manifest_error(field)
        identifiers[field] = item
    return HandoffIdentity(**identifiers)


def _parse_files(value: object) -> tuple[HandoffFile, ...]:
    if not isinstance(value, list):
        raise _manifest_error("files")
    files: list[HandoffFile] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != _FILE_FIELDS:
            raise _manifest_error("file field")
        path = item["path"]
        size = item["size"]
        sha256 = item["sha256"]
        if not isinstance(path, str):
            raise _manifest_error("path")
        if isinstance(size, bool) or not isinstance(size, int):
            raise _manifest_error("size")
        if not isinstance(sha256, str):
            raise _manifest_error("sha256")
        files.append(HandoffFile(path, size, sha256))
    return tuple(files)
