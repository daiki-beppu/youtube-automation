"""setup が所有する最小ディレクトリ生成契約."""

from __future__ import annotations

from pathlib import Path

from youtube_automation.infrastructure.errors import ConfigError

GITKEEP_NAME = ".gitkeep"

SETUP_DIRECTORIES: tuple[str, ...] = (
    "auth",
    "branding",
    "collections",
    "data",
    "docs/channel/personas",
    "docs/benchmarks",
    "research",
)


def validate_existing_setup_directories(target: Path) -> None:
    """存在している setup-owned directory component だけを検証する."""
    for rel in SETUP_DIRECTORIES:
        if _has_existing_component(target, rel):
            validate_setup_directory_target(target, rel)


def validate_setup_directory_target(target: Path, rel: str) -> None:
    """setup directory の生成先が target 配下の通常ディレクトリ契約を満たすか検証する."""
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ConfigError(f"{rel} は target 配下の相対ディレクトリである必要があります")

    path = target / rel_path
    try:
        path.resolve(strict=False).relative_to(target)
    except ValueError as e:
        raise ConfigError(f"{rel} は target 配下に解決される必要があります: {path}") from e

    current = target
    for part in rel_path.parts:
        current = current / part
        current_rel = current.relative_to(target).as_posix()
        if current.is_symlink():
            raise ConfigError(f"{current_rel} は symlink ではなくディレクトリである必要があります: {current}")
        if current.exists() and not current.is_dir():
            if current == path:
                raise ConfigError(f"{rel} はディレクトリである必要があります: {current}")
            raise ConfigError(f"{rel} の親ディレクトリ {current_rel} はディレクトリである必要があります: {current}")

    gitkeep = path / GITKEEP_NAME
    if gitkeep.is_symlink() or (gitkeep.exists() and not gitkeep.is_file()):
        raise ConfigError(f"{rel}/{GITKEEP_NAME} は通常ファイルである必要があります: {gitkeep}")


def _has_existing_component(target: Path, rel: str) -> bool:
    current = target
    for part in Path(rel).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            return True
    return False
