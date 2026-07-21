"""所有チャンネル registry の読み取り専用 loader。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from youtube_automation.utils.exceptions import ChannelRegistryError

DEFAULT_CHANNEL_REGISTRY = Path.home() / ".config" / "tayk" / "channels.json"


def load_channel_registry(path: Path | None = None) -> list[Path]:
    """JSON 配列のチャンネル path を宣言順で返す。"""
    registry_path = path or DEFAULT_CHANNEL_REGISTRY
    try:
        values = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChannelRegistryError(
            f"channel registry がありません: {registry_path}。絶対 path の JSON 配列を作成してください"
        ) from exc
    except OSError as exc:
        raise ChannelRegistryError(f"channel registry を読めません: {registry_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ChannelRegistryError(f"channel registry が不正な JSON です: {registry_path}: {exc}") from exc

    if not isinstance(values, list):
        raise ChannelRegistryError(f"channel registry は絶対 path の JSON 配列でなければなりません: {registry_path}")

    channels: list[Path] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value:
            raise ChannelRegistryError(f"channel registry index {index} は空でない文字列でなければなりません")
        channel = Path(value)
        if not channel.is_absolute():
            raise ChannelRegistryError(f"channel registry index {index} は絶対 path でなければなりません: {value}")
        normalized = os.path.normcase(os.path.normpath(value))
        if normalized in seen:
            raise ChannelRegistryError(f"channel registry index {index} の path が重複しています: {value}")
        seen.add(normalized)
        channels.append(channel)
    return channels
