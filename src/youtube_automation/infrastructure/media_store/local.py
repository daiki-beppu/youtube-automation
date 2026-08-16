"""Filesystem を使う MediaStore adapter。"""

from __future__ import annotations

import shutil
from pathlib import Path

from youtube_automation.core.errors import MediaStoreError
from youtube_automation.domains.media_store import MediaKey, MediaObjectMetadata
from youtube_automation.infrastructure.media_store._files import (
    atomic_destination,
    reject_symlink_components,
    require_regular_source,
    sha256_file,
)


class LocalMediaStore:
    """ローカル root の内側だけへ streaming copy する store。"""

    def __init__(self, root: Path) -> None:
        if root.is_symlink():
            raise MediaStoreError("MediaStore root にシンボリックリンクは使えません")
        self._root = root.absolute()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: MediaKey) -> Path:
        destination = self._root.joinpath(*key.as_posix().split("/"))
        reject_symlink_components(destination, boundary=self._root)
        return destination

    def push(self, source: Path, key: MediaKey) -> MediaObjectMetadata:
        require_regular_source(source)
        size, checksum = sha256_file(source)
        destination = self._path(key)
        with atomic_destination(destination) as temporary:
            with source.open("rb") as input_file, temporary.open("wb") as output_file:
                shutil.copyfileobj(input_file, output_file)
        return MediaObjectMetadata(size=size, sha256=checksum)

    def pull(self, key: MediaKey, destination: Path) -> MediaObjectMetadata:
        source = self._path(key)
        if not source.is_file():
            raise MediaStoreError(f"MediaStore object が見つかりません: {key.as_posix()}")
        with atomic_destination(destination) as temporary:
            with source.open("rb") as input_file, temporary.open("wb") as output_file:
                shutil.copyfileobj(input_file, output_file)
            size, checksum = sha256_file(temporary)
        return MediaObjectMetadata(size=size, sha256=checksum)

    def exists(self, key: MediaKey) -> bool:
        return self.metadata(key) is not None

    def metadata(self, key: MediaKey) -> MediaObjectMetadata | None:
        path = self._path(key)
        if not path.exists():
            return None
        if not path.is_file():
            raise MediaStoreError(f"MediaStore object が通常ファイルではありません: {key.as_posix()}")
        size, checksum = sha256_file(path)
        return MediaObjectMetadata(size=size, sha256=checksum)
