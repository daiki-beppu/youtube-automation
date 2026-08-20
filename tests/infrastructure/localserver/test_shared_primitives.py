from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from youtube_automation.infrastructure.localserver.collections import (
    find_collection_dirs,
    find_suno_collection_dirs,
)
from youtube_automation.infrastructure.localserver.cors import is_origin_allowed
from youtube_automation.infrastructure.localserver.lifecycle import (
    LifecycleRecord,
    consume_stop_request,
    pid_file_path,
    pid_is_running,
    read_pid_file,
    remove_owned_pid_file,
    startup_lock_path,
    stop_request_path,
    write_pid_file,
)


def test_collection_discovery_is_importable_without_collection_server(tmp_path: Path) -> None:
    planning = tmp_path / "collections" / "planning"
    live = tmp_path / "collections" / "live"
    planning.mkdir(parents=True)
    (planning / "b-collection").mkdir()
    (planning / "a-collection").mkdir()
    (planning / "not-a-collection.txt").write_text("ignored", encoding="utf-8")
    completed = live / "a-collection"
    completed.mkdir(parents=True)
    (completed / "workflow-state.json").write_text(
        json.dumps({"schema_version": 4, "collection_id": "a-collection", "phase": "complete"}),
        encoding="utf-8",
    )

    assert [path.name for path in find_collection_dirs(planning)] == ["a-collection", "b-collection"]
    assert [path.name for path in find_suno_collection_dirs(planning)] == ["b-collection"]


def test_lifecycle_paths_preserve_collection_server_names_and_separate_server_kinds(tmp_path: Path) -> None:
    assert pid_file_path(tmp_path, 7873) == tmp_path / ".collection-serve-7873.pid"
    assert stop_request_path(tmp_path, 7873) == tmp_path / ".collection-serve-7873.stop"
    assert startup_lock_path(tmp_path, 7873) == tmp_path / ".collection-serve-7873"
    assert pid_file_path(tmp_path, 7873, server_kind="audio-studio") == tmp_path / ".audio-studio-7873.pid"


def test_lifecycle_record_reader_and_cors_are_importable_without_server_module(tmp_path: Path) -> None:
    path = tmp_path / "server.pid"
    path.write_text(
        json.dumps({"pid": 123, "token": "owner", "configuration": "digest"}),
        encoding="utf-8",
    )

    assert read_pid_file(path) == LifecycleRecord(pid=123, token="owner", configuration="digest")
    assert is_origin_allowed("chrome-extension://abc", None)
    assert not is_origin_allowed("https://example.com", None)


def test_lifecycle_record_publish_consume_and_owned_cleanup_are_shared(tmp_path: Path) -> None:
    pid_path = pid_file_path(tmp_path, 7873, server_kind="audio-studio")
    stop_path = stop_request_path(tmp_path, 7873, server_kind="audio-studio")
    record = LifecycleRecord(pid=os.getpid(), token="owner", configuration="digest")

    write_pid_file(pid_path, record)
    write_pid_file(stop_path, record)

    assert read_pid_file(pid_path) == record
    assert pid_is_running(record.pid)
    assert consume_stop_request(stop_path, record.pid)
    assert not stop_path.exists()
    remove_owned_pid_file(pid_path, record.pid)
    assert not pid_path.exists()


@pytest.mark.parametrize("server_kind", ["../escape", "Audio-Studio", "audio_studio", ""])
def test_lifecycle_paths_reject_unsafe_server_kinds(tmp_path: Path, server_kind: str) -> None:
    with pytest.raises(ValueError, match="server_kind"):
        pid_file_path(tmp_path, 7873, server_kind=server_kind)
