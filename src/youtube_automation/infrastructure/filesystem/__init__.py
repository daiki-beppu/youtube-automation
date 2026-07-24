"""Filesystem I/O boundary."""

import json
import os
from pathlib import Path
from typing import Any


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


def read_json(path: Path, *, encoding: str = "utf-8") -> Any:
    return json.loads(read_file_text(path, encoding=encoding))


def write_json(path: Path, value: Any, *, encoding: str = "utf-8") -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding=encoding)


def write_file_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.write_text(text, encoding=encoding)


def replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def current_working_directory() -> Path:
    return Path.cwd()
