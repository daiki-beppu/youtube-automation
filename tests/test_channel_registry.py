"""所有チャンネル registry の public contract。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.utils.channel_registry import load_channel_registry
from youtube_automation.utils.exceptions import ChannelRegistryError


def test_registry_returns_absolute_paths_in_declared_order(tmp_path: Path) -> None:
    first = tmp_path / "first-channel"
    second = tmp_path / "second-channel"
    registry = tmp_path / "channels.json"
    registry.write_text(json.dumps([str(second), str(first)]), encoding="utf-8")

    assert load_channel_registry(registry) == [second, first]


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("not-json", "JSON"),
        (json.dumps({"channels": []}), "JSON 配列"),
        (json.dumps(["relative/channel"]), "index 0"),
    ],
)
def test_registry_rejects_invalid_documents(tmp_path: Path, contents: str, message: str) -> None:
    registry = tmp_path / "channels.json"
    registry.write_text(contents, encoding="utf-8")

    with pytest.raises(ChannelRegistryError, match=message):
        load_channel_registry(registry)


def test_registry_reports_missing_location(tmp_path: Path) -> None:
    registry = tmp_path / "missing.json"

    with pytest.raises(ChannelRegistryError, match=str(registry)):
        load_channel_registry(registry)


def test_registry_rejects_duplicate_paths(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    registry = tmp_path / "channels.json"
    registry.write_text(json.dumps([str(channel), str(channel)]), encoding="utf-8")

    with pytest.raises(ChannelRegistryError, match="index 1.*重複"):
        load_channel_registry(registry)
