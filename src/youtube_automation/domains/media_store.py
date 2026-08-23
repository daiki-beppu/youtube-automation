"""境界受け渡し用メディアストアの provider-neutral 契約。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from youtube_automation.core.errors import ValidationError

_KEY_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")


def validate_media_segment(field: str, value: str) -> None:
    if not _KEY_SEGMENT_RE.fullmatch(value) or value in {".", ".."}:
        raise ValidationError(f"MediaKey.{field} は安全な単一 path segment である必要があります: {value!r}")


def validate_media_relative_path(field: str, value: str) -> None:
    if not value or value.startswith("/") or "\\" in value:
        raise ValidationError(f"MediaKey.{field} は安全な相対 POSIX path である必要があります: {value!r}")
    path = PurePosixPath(value)
    if path.as_posix() != value:
        raise ValidationError(f"MediaKey.{field} は正規化済み path である必要があります: {value!r}")
    for segment in path.parts:
        if segment in {"", ".", ".."} or _CONTROL_CHARACTER_RE.search(segment):
            raise ValidationError(f"MediaKey.{field} は安全な相対 POSIX path である必要があります: {value!r}")


@dataclass(frozen=True)
class MediaKey:
    """ADR-0024 の ``<channel>/<collection>/<handoff>/<name>`` キー。"""

    channel: str
    collection: str
    handoff: str
    name: str

    def __post_init__(self) -> None:
        for field in ("channel", "collection", "handoff"):
            validate_media_segment(field, getattr(self, field))
        validate_media_relative_path("name", self.name)

    def as_posix(self) -> str:
        return "/".join((self.channel, self.collection, self.handoff, self.name))


@dataclass(frozen=True)
class MediaObjectMetadata:
    """provider に依存しない転送済みオブジェクトの検証情報。"""

    size: int
    sha256: str
    etag: str | None = None


@runtime_checkable
class MediaStore(Protocol):
    """工程境界でのみ使う push / pull / 存在確認 / metadata 参照 / 保持容量観測の最小 port。"""

    def push(self, source: Path, key: MediaKey) -> MediaObjectMetadata: ...

    def pull(self, key: MediaKey, destination: Path) -> MediaObjectMetadata: ...

    def exists(self, key: MediaKey) -> bool: ...

    def metadata(self, key: MediaKey) -> MediaObjectMetadata | None: ...

    def retained_bytes(self) -> int: ...
