"""CLI 共通の target channel directory 解決."""

from __future__ import annotations

import os
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError


def resolve_existing_target_dir(target: str | None) -> Path:
    """対象ディレクトリを `--target` -> `CHANNEL_DIR` -> CWD の順に解決する."""
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
