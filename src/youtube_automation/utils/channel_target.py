"""Shared channel target directory resolution."""

from __future__ import annotations

import os
from pathlib import Path

from youtube_automation.infrastructure.errors import ConfigError


def resolve_existing_target_dir(target: str | None) -> Path:
    """Resolve a target directory from the explicit option or environment."""
    if target:
        path = Path(target).resolve()
        if not path.is_dir():
            raise ConfigError(f"--target で指定されたディレクトリが存在しません: {path}")
        return path

    env = os.environ.get("CHANNEL_DIR")
    if env:
        path = Path(env).resolve()
        if not path.is_dir():
            raise ConfigError(f"CHANNEL_DIR で指定されたディレクトリが存在しません: {path}")
        return path

    return Path.cwd().resolve()
