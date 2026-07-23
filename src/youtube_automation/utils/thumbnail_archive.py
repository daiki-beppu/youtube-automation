"""承認済みサムネイルをチャンネルのギャラリーへ保存する。"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.configuration import channel_dir
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config

_GALLERY_RELATIVE_PATH = Path("assets/thumbnail-gallery")
_THUMBNAIL_SUFFIXES = (".jpg", ".png")


@dataclass(frozen=True)
class ThumbnailArchiveUpdate:
    """適用済みアーカイブ更新と、呼び出し側トランザクション用の復元情報。"""

    target: Path
    _original_files: dict[Path, bytes | None]
    _gallery_existed: bool
    _assets_existed: bool

    def rollback(self) -> None:
        """この更新前のギャラリー状態を復元する。"""
        errors: list[str] = []
        for path, original in self._original_files.items():
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                elif not path.is_file() or path.read_bytes() != original:
                    _replace_bytes(path, original)
            except OSError as exc:
                errors.append(f"{path}: {exc}")

        if not self._gallery_existed:
            gallery = self.target.parent
            try:
                if gallery.is_dir() and not any(gallery.iterdir()):
                    gallery.rmdir()
            except OSError as exc:
                errors.append(f"{gallery}: {exc}")

            if not self._assets_existed:
                assets = gallery.parent
                try:
                    if assets.is_dir() and not any(assets.iterdir()):
                        assets.rmdir()
                except OSError as exc:
                    errors.append(f"{assets}: {exc}")

        if errors:
            raise ValidationError(f"サムネイルアーカイブを復元できません: {'; '.join(errors)}")


def _archive_enabled(config: Mapping[str, object]) -> bool:
    raw_archive = config.get("archive", {})
    if not isinstance(raw_archive, Mapping):
        raise ConfigError(f"thumbnail.archive は mapping である必要があります: {raw_archive!r}")
    enabled = raw_archive.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError(f"thumbnail.archive.enabled は boolean である必要があります: {enabled!r}")
    return enabled


def _validate_destination(channel_root: Path, collection_root: Path, source: Path) -> tuple[Path, Path]:
    resolved_channel = channel_root.resolve()
    try:
        collection_root.relative_to(resolved_channel)
    except ValueError as exc:
        raise ValidationError(f"コレクションは CHANNEL_DIR 配下にある必要があります: {collection_root}") from exc

    if source.parent.is_symlink():
        raise ValidationError(f"10-assets にシンボリックリンクは指定できません: {source.parent}")
    if source.is_symlink():
        raise ValidationError(f"確定済みサムネイルにシンボリックリンクは指定できません: {source}")
    if not source.is_file():
        raise ValidationError(f"確定済みサムネイルが見つかりません: {source}")

    assets_root = resolved_channel / "assets"
    gallery = resolved_channel / _GALLERY_RELATIVE_PATH
    if assets_root.is_symlink():
        raise ValidationError(f"assets にシンボリックリンクは指定できません: {assets_root}")
    if gallery.is_symlink():
        raise ValidationError(f"thumbnail-gallery にシンボリックリンクは指定できません: {gallery}")
    if gallery.exists() and not gallery.is_dir():
        raise ValidationError(f"thumbnail-gallery と同名のファイルがあります: {gallery}")

    target = gallery / f"{collection_root.name}{source.suffix.lower()}"
    if target.is_symlink():
        raise ValidationError(f"アーカイブ先にシンボリックリンクは指定できません: {target}")
    return gallery, target


def _replace_bytes(target: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}-rollback-", suffix=target.suffix, dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _capture_original_files(paths: tuple[Path, ...]) -> dict[Path, bytes | None]:
    try:
        return {
            path: path.read_bytes() if path.is_file() else None for path in paths if not path.exists() or path.is_file()
        }
    except OSError as exc:
        raise ValidationError(f"サムネイルアーカイブのバックアップを読み込めません: {exc}") from exc


def archive_approved_thumbnail_transaction(collection: Path) -> ThumbnailArchiveUpdate | None:
    """設定が有効なら承認済み thumbnail を更新し、復元可能な結果を返す。"""
    config = load_skill_config("thumbnail")
    if not _archive_enabled(config):
        return None

    paths = CollectionPaths(collection)
    source = paths.find_thumbnail()
    if source is None:
        raise ValidationError(f"確定済みサムネイルが見つかりません: {paths.assets_dir}")

    gallery, target = _validate_destination(channel_dir(), paths.root, source)
    alternate_targets = [
        gallery / f"{paths.root.name}{suffix}" for suffix in _THUMBNAIL_SUFFIXES if suffix != source.suffix.lower()
    ]
    for alternate in alternate_targets:
        if alternate.is_symlink():
            raise ValidationError(f"既存アーカイブにシンボリックリンクは指定できません: {alternate}")

    gallery_existed = gallery.exists()
    assets_existed = gallery.parent.exists()
    original_files = _capture_original_files((target, *alternate_targets))
    update = ThumbnailArchiveUpdate(target, original_files, gallery_existed, assets_existed)
    temporary: Path | None = None
    try:
        gallery.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{paths.root.name}-", suffix=source.suffix.lower(), dir=gallery
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        shutil.copyfile(source, temporary)
        for alternate in alternate_targets:
            alternate.unlink(missing_ok=True)
        os.replace(temporary, target)
        temporary = None
    except OSError as exc:
        cleanup_error = None
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as temporary_cleanup_exc:
                cleanup_error = temporary_cleanup_exc
        try:
            update.rollback()
        except ValidationError as rollback_exc:
            cleanup_detail = f"; {cleanup_error}" if cleanup_error is not None else ""
            raise ValidationError(
                f"承認済みサムネイルをアーカイブできず、元の状態も復元できません: "
                f"{source} -> {target}: {exc}{cleanup_detail}; {rollback_exc}"
            ) from rollback_exc
        if cleanup_error is not None:
            raise ValidationError(
                f"承認済みサムネイルをアーカイブできず、一時ファイルも削除できません: "
                f"{source} -> {target}: {exc}; {cleanup_error}"
            ) from cleanup_error
        raise ValidationError(f"承認済みサムネイルをアーカイブできません: {source} -> {target}: {exc}") from exc
    return update


def archive_approved_thumbnail(collection: Path) -> Path | None:
    """設定が有効なら承認済み thumbnail を原子的にコピーする。"""
    update = archive_approved_thumbnail_transaction(collection)
    return update.target if update is not None else None
