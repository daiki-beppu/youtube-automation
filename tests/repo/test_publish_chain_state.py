"""State decisions for the initial ``/publish`` upload chain (#3841)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from tests.helpers.paths import REPO_ROOT

SCRIPT = REPO_ROOT / ".claude" / "skills" / "publish" / "references" / "publish-chain-state.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publish_chain_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collection(tmp_path: Path, upload: object) -> Path:
    collection = tmp_path / "collections" / "planning" / "sample"
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(json.dumps({"upload": upload}), encoding="utf-8")
    return collection


def _channel(tmp_path: Path, playlists: object) -> Path:
    channel = tmp_path / "channel"
    config = channel / "config" / "channel"
    config.mkdir(parents=True)
    (config / "playlists.json").write_text(json.dumps({"playlists": playlists}), encoding="utf-8")
    return channel


def test_playlist_runs_when_any_playlist_id_is_missing(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": None})
    channel = _channel(tmp_path, {"focus": {"title": "Focus", "playlist_id": None}})

    code, result = module.evaluate(collection, "playlist", channel)

    assert code == module.EXIT_RUN
    assert result["decision"] == "run"
    assert result["reason"] == "playlist_id_missing"


def test_playlist_skips_when_all_playlist_ids_are_recorded(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": None})
    channel = _channel(
        tmp_path,
        {
            "focus": {"title": "Focus", "playlist_id": "PL-focus"},
            "all": {"title": "All", "playlist_id": "PL-all"},
        },
    )

    code, result = module.evaluate(collection, "playlist", channel)

    assert code == module.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["artifacts"] == ["config/channel/playlists.json::playlists.*.playlist_id"]


def test_playlist_blocks_on_invalid_config(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": None})
    channel = _channel(tmp_path, "invalid")

    code, result = module.evaluate(collection, "playlist", channel)

    assert code == module.EXIT_BLOCKED
    assert result["decision"] == "blocked"
    assert result["reason"] == "playlists_invalid"


def test_upload_runs_when_video_id_is_missing(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": None})

    code, result = module.evaluate(collection, "upload")

    assert code == module.EXIT_RUN
    assert result["decision"] == "run"
    assert result["reason"] == "video_id_missing"


def test_upload_blocks_when_collection_dir_is_missing() -> None:
    module = _module()

    code, result = module.evaluate(None, "upload")

    assert code == module.EXIT_BLOCKED
    assert result["reason"] == "collection_dir_missing"


def test_upload_skips_when_video_id_is_recorded(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": "youtube-id"})

    code, result = module.evaluate(collection, "upload")

    assert code == module.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["artifacts"] == ["workflow-state.json::upload.video_id"]


def test_upload_blocks_on_invalid_upload_state(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "invalid")

    code, result = module.evaluate(collection, "upload")

    assert code == module.EXIT_BLOCKED
    assert result["decision"] == "blocked"
    assert result["reason"] == "upload_state_invalid"


def test_community_runs_when_post_text_is_missing(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": "youtube-id"})

    code, result = module.evaluate(collection, "community")

    assert code == module.EXIT_RUN
    assert result["decision"] == "run"
    assert result["reason"] == "community_post_missing"


def test_community_skips_when_post_text_exists(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": "youtube-id"})
    documentation = collection / "20-documentation"
    documentation.mkdir()
    (documentation / "community-post.txt").write_text("Ready", encoding="utf-8")

    code, result = module.evaluate(collection, "community")

    assert code == module.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["artifacts"] == ["20-documentation/community-post.txt"]


def test_community_blocks_until_upload_is_recorded(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": None})

    code, result = module.evaluate(collection, "community")

    assert code == module.EXIT_BLOCKED
    assert result["reason"] == "video_id_missing"


def _write_pinned_config(channel: Path, history_file: str = "pinned_comment_history.json") -> None:
    config = channel / "config/channel"
    config.mkdir(parents=True, exist_ok=True)
    (config / "pinned-comment.json").write_text(
        json.dumps({"pinned_comment": {"history_file": history_file}}),
        encoding="utf-8",
    )


def test_pinned_runs_when_video_is_not_in_history(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": "youtube-id"})
    channel = tmp_path / "channel"
    _write_pinned_config(channel)

    code, result = module.evaluate(collection, "pinned", channel)

    assert code == module.EXIT_RUN
    assert result["reason"] == "pinned_comment_missing"


def test_pinned_skips_when_video_is_recorded_in_configured_history(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": "youtube-id"})
    channel = tmp_path / "channel"
    _write_pinned_config(channel, "history/pins.json")
    history = channel / "history/pins.json"
    history.parent.mkdir()
    history.write_text(json.dumps({"schema_version": 1, "posted": {"youtube-id": {}}}), encoding="utf-8")

    code, result = module.evaluate(collection, "pinned", channel)

    assert code == module.EXIT_SKIP
    assert result["artifacts"] == ["history/pins.json"]


def test_pinned_blocks_on_invalid_history(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": "youtube-id"})
    channel = tmp_path / "channel"
    _write_pinned_config(channel)
    (channel / "pinned_comment_history.json").write_text("[]", encoding="utf-8")

    code, result = module.evaluate(collection, "pinned", channel)

    assert code == module.EXIT_BLOCKED
    assert result["reason"] == "pinned_comment_history_invalid"
