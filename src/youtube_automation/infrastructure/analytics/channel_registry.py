"""所有チャンネル registry の loader と原子的 writer。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.core.errors import ChannelRegistryError

DEFAULT_CHANNEL_REGISTRY = Path.home() / ".config" / "tayk" / "channels.json"


@dataclass(frozen=True)
class ChannelRegistryUpdate:
    path: Path
    channels: tuple[Path, ...]
    action: str
    index: int

    def as_json(self) -> str:
        """registry へ書き込む JSON 本文（末尾改行なし）を返す。"""
        return json.dumps([str(channel) for channel in self.channels], ensure_ascii=False, indent=2)

    def write(self) -> None:
        """変更があれば backup を残して registry を原子的に置換する。"""
        if self.action == "noop":
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_name(f"{self.path.name}.bak"))
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(f"{self.as_json()}\n")
            temporary.replace(self.path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise


def _normalized(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _same_path(left: Path, right: Path) -> bool:
    normalized_left = _normalized(str(left))
    normalized_right = _normalized(str(right))
    return normalized_left == normalized_right or left.resolve(strict=False) == right.resolve(strict=False)


def plan_channel_registry_update(path: Path, *, source: Path, destination: Path) -> ChannelRegistryUpdate:
    """source の同位置置換、destination の追加、または no-op を計画する。"""
    destination = destination.absolute()
    channels = load_channel_registry(path) if path.exists() else []
    for index, channel in enumerate(channels):
        if _same_path(channel, destination):
            return ChannelRegistryUpdate(path, tuple(channels), "noop", index)
    for index, channel in enumerate(channels):
        if _same_path(channel, source):
            updated = [*channels]
            updated[index] = destination
            return ChannelRegistryUpdate(path, tuple(updated), "replace", index)
    return ChannelRegistryUpdate(path, (*channels, destination), "append", len(channels))


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
        normalized = _normalized(value)
        if normalized in seen:
            raise ChannelRegistryError(f"channel registry index {index} の path が重複しています: {value}")
        seen.add(normalized)
        channels.append(channel)
    return channels
