"""Process-local channel root resolution, independent of configuration loading."""

import os
from pathlib import Path

from youtube_automation.core.errors import ConfigError

_channel_dir: Path | None = None


def _find_channel_ancestor(start: Path) -> Path | None:
    current = start.expanduser().resolve()
    for parent in [current, *current.parents]:
        if (parent / "config" / "channel").is_dir():
            return parent
    return None


def _resolve_channel_dir() -> Path:
    """設定ルートを CHANNEL_DIR → cwd 祖先の優先順で解決する."""
    env_dir = os.environ.get("CHANNEL_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    cwd_channel = _find_channel_ancestor(Path.cwd())
    if cwd_channel is not None:
        return cwd_channel
    raise ConfigError("CHANNEL_DIR 環境変数を設定するか、config/channel/ を持つディレクトリ配下で実行してください")


def channel_dir() -> Path:
    """`config/channel/` を含むプロジェクトルートを返す（シングルトン解決）."""
    global _channel_dir
    if _channel_dir is None:
        _channel_dir = _resolve_channel_dir()
    return _channel_dir


def refresh_channel_dir() -> Path:
    """Refresh the root when beginning a new configuration load."""
    global _channel_dir
    _channel_dir = _resolve_channel_dir()
    return _channel_dir


def reset_channel_context() -> None:
    """Clear the cached root."""
    global _channel_dir
    _channel_dir = None
