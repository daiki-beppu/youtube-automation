"""返信履歴ファイルの読み書きテスト."""

from __future__ import annotations

import json

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
