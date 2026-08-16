"""境界受け渡し用メディアストアの provider-neutral 契約。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from youtube_automation.core.errors import ValidationError

_KEY_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _validate_segment(field: str, value: str) -> None:
    if not _KEY_SEGMENT_RE.fullmatch(value) or value in {".", ".."}:
        raise ValidationError(f"MediaKey.{field} は安全な単一 path segment である必要があります: {value!r}")


@dataclass(frozen=True)
class MediaKey:
    """ADR-0024 の ``<channel>/<collection>/<handoff>/<name>`` キー。"""

    channel: str
    collection: str
    handoff: str
    name: str

    def __post_init__(self) -> None:
        for field in ("channel", "collection", "handoff", "name"):
            _validate_segment(field, getattr(self, field))

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
    """工程境界でのみ使う push / pull / 存在確認の最小 port。"""

    def push(self, source: Path, key: MediaKey) -> MediaObjectMetadata: ...

    def pull(self, key: MediaKey, destination: Path) -> MediaObjectMetadata: ...

    def exists(self, key: MediaKey) -> bool: ...

    def metadata(self, key: MediaKey) -> MediaObjectMetadata | None: ...
