"""返信履歴ファイルの読み書きテスト."""

from __future__ import annotations

import json
import os

import pytest

from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.comments.history import SCHEMA_VERSION, ReplyHistory


def test_fresh_history_is_empty(tmp_path):
    history = ReplyHistory(tmp_path / "reply.json")
    assert history.replied_count() == 0
    assert history.has_replied("abc") is False


def test_mark_and_save_roundtrip(tmp_path):
    path = tmp_path / "reply.json"
    history = ReplyHistory(path)
    history.mark_replied(
        "UgABC",
        {
            "video_id": "vid1",
            "replied_at": "2026-04-23T10:00:00+09:00",
            "rule": "greeting",
            "reply_text": "どうも！",
        },
    )
    history.save()
    # 別インスタンスで再ロード
    history2 = ReplyHistory(path)
    assert history2.has_replied("UgABC") is True
    assert history2.replied_count() == 1

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION
    assert "UgABC" in raw["replied"]


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "reply.json"
    path.write_text("not a json", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON パース失敗"):
        ReplyHistory(path)


def test_toplevel_must_be_object(tmp_path):
    path = tmp_path / "reply.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError, match="object でなければなりません"):
        ReplyHistory(path)


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "deep" / "nested" / "reply.json"
    history = ReplyHistory(path)
    history.mark_replied("x", {"video_id": "v"})
    history.save()
    assert path.exists()


def test_replied_must_be_object(tmp_path):
    path = tmp_path / "reply.json"
    path.write_text('{"replied": []}', encoding="utf-8")

    with pytest.raises(ConfigError, match="replied は object"):
        ReplyHistory(path)


def test_replied_video_ids_ignores_legacy_and_invalid_records(tmp_path):
    path = tmp_path / "reply.json"
    path.write_text(
        json.dumps(
            {
                "replied": {
                    "current": {"video_id": "v1"},
                    "legacy": {"reply_text": "thanks"},
                    "invalid": "old-record",
                }
            }
        ),
        encoding="utf-8",
    )

    assert ReplyHistory(path).replied_video_ids() == {"v1"}


def test_replace_failure_keeps_existing_history_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "reply.json"
    original = '{"schema_version": 1, "replied": {}}\n'
    path.write_text(original, encoding="utf-8")
    history = ReplyHistory(path)
    history.mark_replied("new", {"video_id": "v1"})
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        history.save()

    assert path.read_text(encoding="utf-8") == original
    assert path.with_suffix(".json.tmp").exists()
