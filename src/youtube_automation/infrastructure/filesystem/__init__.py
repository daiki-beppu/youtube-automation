"""Filesystem I/O boundary."""

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeAlias

from youtube_automation.infrastructure.file_lock import file_lock as file_lock

JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


def path_exists(path: Path) -> bool:
    return path.exists()


def path_is_directory(path: Path) -> bool:
    return path.is_dir()


def path_is_file(path: Path) -> bool:
    return path.is_file()


def path_is_symlink(path: Path) -> bool:
    return path.is_symlink()


def list_directory(path: Path) -> list[Path]:
    return list(path.iterdir())


def glob_files(path: Path, pattern: str) -> list[Path]:
    return list(path.glob(pattern))


def make_directory(path: Path, *, parents: bool = False, exist_ok: bool = False) -> None:
    path.mkdir(parents=parents, exist_ok=exist_ok)


def rename_path(source: Path, destination: Path) -> None:
    source.rename(destination)


def file_size(path: Path) -> int:
    return path.stat().st_size


def remove_file(path: Path) -> None:
    path.unlink()


def read_file_text(path: Path, *, encoding: str = "utf-8") -> str:
    return path.read_text(encoding=encoding)


def read_json(path: Path, *, encoding: str = "utf-8") -> JSONValue:
    return json.loads(read_file_text(path, encoding=encoding))


def write_json(path: Path, value: JSONValue, *, encoding: str = "utf-8") -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding=encoding)


def write_file_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.write_text(text, encoding=encoding)


def replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _temporary_path(target: Path, *, suffix: str) -> tuple[int, Path]:
    descriptor, name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=suffix,
    )
    return descriptor, Path(name)


def _write_temporary_text(target: Path, text: str, *, encoding: str, newline: str | None = None) -> Path:
    descriptor, temporary = _temporary_path(target, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline=newline) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, UnicodeError):
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def write_file_text_atomically(
    path: Path,
    text: str,
    *,
    mode: int,
    encoding: str = "utf-8",
    newline: str | None = None,
    validate_staged: Callable[[Path], None] | None = None,
) -> None:
    """Replace one file after flushing its contents and setting the requested permissions."""
    temporary = _write_temporary_text(path, text, encoding=encoding, newline=newline)
    try:
        if validate_staged is not None:
            validate_staged(temporary)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _reserve_backup_path(target: Path) -> Path:
    descriptor, backup = _temporary_path(target, suffix=".backup")
    os.close(descriptor)
    return backup


def _rollback_files(
    targets: list[Path],
    original_targets: set[Path],
    backups: dict[Path, Path],
    backed_up_targets: set[Path],
) -> None:
    rollback_errors: list[OSError] = []
    for target in reversed(targets):
        try:
            if target in backed_up_targets:
                target.unlink(missing_ok=True)
                replace_file(backups[target], target)
            elif target not in original_targets:
                target.unlink(missing_ok=True)
        except OSError as exc:
            rollback_errors.append(exc)
    if rollback_errors:
        raise OSError("transactional file publish rollback failed") from rollback_errors[0]


def _cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _transaction_targets(contents: Mapping[Path, str]) -> list[Path]:
    """Validate the publication scope before creating temporary files or backups."""
    targets = list(contents)
    if not targets:
        raise ValueError("transactional file publish requires at least one target")
    if len({target.parent for target in targets}) != 1:
        raise ValueError("transactional file publish targets must share one directory")

    return targets


def _write_text_files_transactionally(
    contents: Mapping[Path, str],
    verifier: Callable[[], None] | None,
    *,
    encoding: str,
) -> None:
    """Publish text files as one rollback-capable transaction.

    Process termination and filesystem loss are outside this local transaction's
    guarantees. All temporary and backup files are created beside their targets.
    """
    targets = _transaction_targets(contents)

    temporaries: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    original_targets = {target for target in targets if target.exists()}
    backed_up_targets: set[Path] = set()
    try:
        for target in targets:
            temporaries[target] = _write_temporary_text(target, contents[target], encoding=encoding)
        for target in targets:
            if target not in original_targets:
                continue
            backup = _reserve_backup_path(target)
            backups[target] = backup
            replace_file(target, backup)
            backed_up_targets.add(target)
        for target in targets:
            replace_file(temporaries[target], target)
        if verifier is not None:
            verifier()
    except Exception as publish_error:
        try:
            _rollback_files(targets, original_targets, backups, backed_up_targets)
        except OSError as rollback_error:
            _cleanup_paths(list(temporaries.values()))
            raise rollback_error from publish_error
        _cleanup_paths([*temporaries.values(), *backups.values()])
        raise
    _cleanup_paths([*temporaries.values(), *backups.values()])


def write_text_files_transactionally(contents: Mapping[Path, str], *, encoding: str = "utf-8") -> None:
    """Publish text files as one rollback-capable transaction."""
    _write_text_files_transactionally(contents, None, encoding=encoding)


def write_verified_text_files_transactionally(
    contents: Mapping[Path, str],
    verifier: Callable[[], None],
    *,
    encoding: str = "utf-8",
) -> None:
    """Publish text files and roll all targets back when post-write verification fails."""
    _write_text_files_transactionally(contents, verifier, encoding=encoding)


def current_working_directory() -> Path:
    return Path.cwd()
