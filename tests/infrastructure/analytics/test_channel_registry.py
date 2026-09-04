"""所有チャンネル registry の public contract。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import ChannelRegistryError
from youtube_automation.infrastructure.analytics.channel_registry import (
    load_channel_registry,
    plan_channel_registry_update,
)


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


def test_registry_replaces_resolved_workspace_path_in_place_and_backs_up(tmp_path: Path) -> None:
    real_workspace = tmp_path / "real-workspace"
    source = real_workspace / "channels/demo"
    source.mkdir(parents=True)
    workspace_link = tmp_path / "workspace-link"
    workspace_link.symlink_to(real_workspace, target_is_directory=True)
    first = tmp_path / "first"
    destination = tmp_path / "exported"
    registry = tmp_path / "channels.json"
    original = json.dumps([str(first), str(workspace_link / "channels/demo")])
    registry.write_text(original, encoding="utf-8")

    update = plan_channel_registry_update(registry, source=source, destination=destination)
    assert update.action == "replace"
    assert update.index == 1
    update.write()

    assert load_channel_registry(registry) == [first, destination]
    assert registry.with_name("channels.json.bak").read_text(encoding="utf-8") == original


def test_registry_appends_missing_destination_and_existing_destination_is_noop(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    destination = tmp_path / "exported"
    registry = tmp_path / "channels.json"
    registry.write_text(json.dumps([str(existing)]), encoding="utf-8")

    update = plan_channel_registry_update(registry, source=tmp_path / "missing", destination=destination)
    assert (update.action, update.index) == ("append", 1)
    update.write()
    before = registry.read_bytes()
    backup_before = registry.with_name("channels.json.bak").read_bytes()

    noop = plan_channel_registry_update(registry, source=tmp_path / "missing", destination=destination)
    assert (noop.action, noop.index) == ("noop", 1)
    noop.write()
    assert registry.read_bytes() == before
    assert registry.with_name("channels.json.bak").read_bytes() == backup_before


def test_registry_missing_file_is_created_and_invalid_json_is_preserved(tmp_path: Path) -> None:
    destination = tmp_path / "exported"
    registry = tmp_path / "channels.json"
    update = plan_channel_registry_update(registry, source=tmp_path / "missing", destination=destination)
    update.write()
    assert load_channel_registry(registry) == [destination]

    registry.write_text("invalid", encoding="utf-8")
    with pytest.raises(ChannelRegistryError, match="JSON"):
        plan_channel_registry_update(registry, source=tmp_path / "missing", destination=tmp_path / "other")
    assert registry.read_text(encoding="utf-8") == "invalid"
