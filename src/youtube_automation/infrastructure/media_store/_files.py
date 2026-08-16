"""MediaStore adapter 間で共有する fail-closed filesystem helper。"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from youtube_automation.core.errors import MediaStoreError

_COPY_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(_COPY_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def require_regular_source(path: Path) -> None:
    if path.is_symlink():
        raise MediaStoreError(f"転送元にシンボリックリンクは使えません: {path.name}")
    if not path.is_file():
        raise MediaStoreError(f"転送元ファイルが見つかりません: {path.name}")


def reject_symlink_components(path: Path, *, boundary: Path | None = None) -> None:
    if boundary is None:
        current = path
        while not current.exists() and current != current.parent:
            current = current.parent
        if current.is_symlink():
            raise MediaStoreError(f"出力先にシンボリックリンクは使えません: {current.name}")
        return

    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise MediaStoreError("出力先が MediaStore root の境界外です") from exc
    current = boundary
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise MediaStoreError(f"出力先にシンボリックリンクは使えません: {component}")


@contextmanager
def atomic_destination(destination: Path) -> Iterator[Path]:
    reject_symlink_components(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_components(destination.parent)
    descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(raw_temporary)
    try:
        yield temporary
        reject_symlink_components(destination)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
