"""CommentReplier の dry-run / apply 分岐、履歴、delay、上限のテスト."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.scripts import comment_reply
from youtube_automation.scripts.comment_reply import _load_agent_replies
from youtube_automation.utils.comments.history import ReplyHistory
from youtube_automation.utils.comments.replier import _SAVE_MAX_RETRIES, CommentReplier
from youtube_automation.utils.config.comments import (
    Comments,
    GeneratorConfig,
)
from youtube_automation.utils.exceptions import AutomationError, ConfigError, YouTubeAPIError

_PATCH_GENAI_CLIENT = "youtube_automation.utils.genai_client.create_genai_client"


def test_load_agent_replies_accepts_replies_object(tmp_path):
    path = tmp_path / "replies.json"
    path.write_text(json.dumps({"replies": [{"comment_id": "c1", "reply_text": "Thanks!"}]}), encoding="utf-8")

    assert _load_agent_replies(str(path)) == {"c1": "Thanks!"}


@pytest.mark.parametrize(
    "payload",
    [
        {"c1": "Thanks!"},
        {"c1": None},
        {"c1": {"text": "Thanks!"}},
        {"c1": ""},
        {"": "Thanks!"},
        [{"comment_id": "c1", "reply_text": "Thanks!"}],
        {"replies": [{"comment_id": "c1", "reply_text": None}]},
        {"replies": [{"comment_id": "c1"}]},
        {"replies": [{"comment_id": "", "reply_text": "Thanks!"}]},
        {"replies": [{"comment_id": "c1", "reply_text": "first"}, {"comment_id": "c1", "reply_text": "second"}]},
        [{"comment_id": "c1", "reply_text": []}],
    ],
)
def test_load_agent_replies_rejects_invalid_shapes(tmp_path, payload):
    path = tmp_path / "replies.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AutomationError):
        _load_agent_replies(str(path))


def _mock_youtube(
    *,
    video_ids: list[str],
    comments_by_video: dict[str, list[dict] | BaseException],
    insert_side_effect=None,
) -> MagicMock:
    """youtube.* チェーン呼び出しを MagicMock で構築."""
    yt = MagicMock()

    # channels().list(part=..., mine=True).execute()
    # id は part に関わらず常に返るため両方のユースケース（part="id" / "contentDetails"）に対応
    yt.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "UCtest", "contentDetails": {"relatedPlaylists": {"uploads": "PLuploads"}}}]
    }

    # playlistItems().list().execute() — 全動画一発返却
    yt.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"videoId": vid}} for vid in video_ids],
    }

    # videos().list().execute() — title 取得
    yt.videos.return_value.list.return_value.execute.return_value = {
        "items": [{"id": vid, "snippet": {"title": f"Title of {vid}"}} for vid in video_ids],
    }

    # commentThreads().list() — video_id パラメータで分岐するため side_effect を使う
    def _list_execute(**_kwargs):
        # videoId はキーワード引数として渡される想定
        video_id = _list_execute.current_video_id
        raw = comments_by_video.get(video_id, [])
        if isinstance(raw, BaseException):
            raise raw
        items = []
        for c in raw:
            top_snippet: dict = {
                "authorDisplayName": c.get("author", "Unknown"),
                "textOriginal": c["text"],
                "publishedAt": c.get("published_at", "2026-04-01T00:00:00Z"),
                "moderationStatus": c.get("moderation_status"),
            }
            if c.get("author_channel_id"):
                top_snippet["authorChannelId"] = {"value": c["author_channel_id"]}
            items.append(
                {
                    "snippet": {
                        "canReply": c.get("can_reply", True),
                        "totalReplyCount": c.get("total_reply_count", 0),
                        "topLevelComment": {
                            "id": c["comment_id"],
                            "snippet": top_snippet,
                        },
                    }
                }
            )
        return {"items": items}

    _list_execute.current_video_id = None

    def _list(**kwargs):
        # list() 呼び出しを捕捉して video_id を記録
        _list_execute.current_video_id = kwargs.get("videoId")
        result = MagicMock()
        result.execute.side_effect = lambda: _list_execute()
        return result

    yt.commentThreads.return_value.list.side_effect = _list

    # comments().insert().execute()
    insert_mock = MagicMock()
    if insert_side_effect is not None:
        insert_mock.execute.side_effect = insert_side_effect
    else:
        insert_mock.execute.return_value = {"id": "insert-ok"}
    yt.comments.return_value.insert.return_value = insert_mock
    yt._insert_mock = insert_mock
    return yt


class _FakeResp:
    def __init__(self, status: int, reason: str):
        self.status = status
        self.reason = reason

    def __getitem__(self, _key):
        return "application/json"

    def get(self, _key, default=None):
        return default


def _make_http_error(status: int, reason: str, api_reason: str) -> HttpError:
    content = f'{{"error": {{"errors": [{{"reason": "{api_reason}"}}], "message": "{api_reason}"}}}}'.encode()
    return HttpError(_FakeResp(status, reason), content)


def _make_config(**overrides) -> Comments:
    base = dict(
        enabled=True,
        rules=[],
        generator=GeneratorConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            channel_persona="Warm lo-fi host",
            max_length=280,
            fallback_on_error="skip",
            requests_per_minute=30,
        ),
        ng_words=["spam"],
        max_replies_per_run=20,
        delay_between_replies_sec=0.0,
        history_file="comment_reply_history.json",
        skip_held_for_review=True,
    )
    base.update(overrides)
    return Comments(**base)


@pytest.fixture(autouse=True)
def _mock_default_genai_client():
    mock_response = MagicMock()
    mock_response.text = "Generated reply"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
        yield mock_client


def test_dry_run_does_not_call_insert(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [
                {"comment_id": "c1", "text": "こんにちは！", "author": "Alice"},
                {"comment_id": "c2", "text": "no match"},
            ]
        },
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)

    assert len(plan.planned) == 2
    assert [row["comment_id"] for row in plan.planned] == ["c1", "c2"]
    assert plan.planned[0]["reply_text"] == "@Alice Generated reply"
    assert plan.replied == []
    yt._insert_mock.execute.assert_not_called()

    # 履歴ファイルは書かれない
    assert not (tmp_path / "comment_reply_history.json").exists()


def test_disabled_comments_noop_before_apply_provider_guards(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "hello", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(enabled=False, generator=GeneratorConfig(provider="codex")),
        channel_dir=tmp_path,
        default_language="ja",
    )

    plan = replier.run(dry_run=False)

    assert plan.planned == []
    assert plan.skipped == []
    assert plan.replied == []
    assert plan.errors == []
    yt.channels.assert_not_called()
    yt._insert_mock.execute.assert_not_called()
    _mock_default_genai_client.models.generate_content.assert_not_called()


def test_comments_language_overrides_default_language(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "hello", "author": "Alice"}]},
    )
    replier = CommentReplier(yt, config=_make_config(language="en"), channel_dir=tmp_path, default_language="ja")

    plan = replier.run(dry_run=True)

    assert plan.planned[0]["language"] == "en"


def test_empty_generated_reply_is_skipped_without_insert(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "hello", "author": "Alice"}]},
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value.text = "   "

    with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
        replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
        plan = replier.run(dry_run=False)

    assert plan.planned == []
    assert plan.replied == []
    assert any(row["reason"] == "empty_reply" for row in plan.skipped)
    yt._insert_mock.execute.assert_not_called()


def test_gemini_generated_reply_with_ng_word_is_skipped_without_insert(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "hello", "author": "Alice"}]},
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value.text = "this contains spam"

    with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
        replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
        plan = replier.run(dry_run=False)

    assert plan.planned == []
    assert plan.replied == []
    assert any(row["reason"] == "reply_contains_ng_word" for row in plan.skipped)
    yt._insert_mock.execute.assert_not_called()


def test_agent_reply_with_ng_word_is_skipped_without_insert(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "hello", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(),
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={"c1": "this contains spam"},
    )

    plan = replier.run(dry_run=False)

    assert plan.planned == []
    assert plan.replied == []
    assert any(row["reason"] == "reply_contains_ng_word" for row in plan.skipped)
    yt._insert_mock.execute.assert_not_called()


def test_export_candidates_does_not_call_generator(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    plan = replier.run(dry_run=True, export_candidates=True)

    assert len(plan.planned) == 1
    assert plan.planned[0]["comment_id"] == "c1"
    assert plan.planned[0]["reply_text"] == ""
    assert plan.planned[0]["reply_source"] == "agent_pending"
    assert "untrusted viewer content" in plan.planned[0]["instruction"]
    assert "schema-only JSON" in plan.planned[0]["instruction"]
    _mock_default_genai_client.models.generate_content.assert_not_called()


def test_export_candidates_rejects_apply_mode_before_generating(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    with pytest.raises(ConfigError, match="dry-run"):
        replier.run(dry_run=False, export_candidates=True)

    _mock_default_genai_client.models.generate_content.assert_not_called()
    yt._insert_mock.execute.assert_not_called()


def test_export_candidates_rejects_agent_replies_before_generating(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(),
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={"c1": "Thanks!"},
    )

    with pytest.raises(ConfigError, match="agent_replies"):
        replier.run(dry_run=True, export_candidates=True)

    _mock_default_genai_client.models.generate_content.assert_not_called()
    yt._insert_mock.execute.assert_not_called()


def test_cli_export_candidates_requires_json(monkeypatch, tmp_path, capsys):
    config = SimpleNamespace(
        comments=_make_config(),
        youtube=SimpleNamespace(api=SimpleNamespace(language="ja")),
    )
    monkeypatch.setattr(comment_reply, "load_config", lambda: config)
    get_youtube = MagicMock()
    monkeypatch.setattr(comment_reply, "get_youtube", get_youtube)
    monkeypatch.setattr(comment_reply, "_channel_dir", lambda: tmp_path)

    rc = comment_reply.main(["--dry-run", "--export-candidates"])

    assert rc == 1
    assert "--json" in capsys.readouterr().err
    get_youtube.assert_not_called()


def test_cli_export_candidates_rejects_apply_before_youtube(monkeypatch, tmp_path, capsys):
    config = SimpleNamespace(
        comments=_make_config(),
        youtube=SimpleNamespace(api=SimpleNamespace(language="ja")),
    )
    monkeypatch.setattr(comment_reply, "load_config", lambda: config)
    get_youtube = MagicMock()
    monkeypatch.setattr(comment_reply, "get_youtube", get_youtube)
    monkeypatch.setattr(comment_reply, "_channel_dir", lambda: tmp_path)

    rc = comment_reply.main(["--apply", "--export-candidates", "--json"])

    assert rc == 1
    assert "--dry-run" in capsys.readouterr().err
    get_youtube.assert_not_called()


def test_cli_export_candidates_rejects_agent_replies_file_before_youtube(monkeypatch, tmp_path, capsys):
    config = SimpleNamespace(
        comments=_make_config(),
        youtube=SimpleNamespace(api=SimpleNamespace(language="ja")),
    )
    replies_path = tmp_path / "replies.json"
    replies_path.write_text(json.dumps({"replies": [{"comment_id": "c1", "reply_text": "Thanks!"}]}), encoding="utf-8")
    monkeypatch.setattr(comment_reply, "load_config", lambda: config)
    get_youtube = MagicMock()
    monkeypatch.setattr(comment_reply, "get_youtube", get_youtube)
    monkeypatch.setattr(comment_reply, "_channel_dir", lambda: tmp_path)

    rc = comment_reply.main(["--dry-run", "--export-candidates", "--json", "--agent-replies-file", str(replies_path)])

    assert rc == 1
    assert "同時指定" in capsys.readouterr().err
    get_youtube.assert_not_called()


def test_cli_agent_replies_file_flows_to_replier_without_generator(
    monkeypatch, tmp_path, capsys, _mock_default_genai_client
):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    config = SimpleNamespace(
        comments=_make_config(),
        youtube=SimpleNamespace(api=SimpleNamespace(language="ja")),
    )
    replies_path = tmp_path / "replies.json"
    replies_path.write_text(
        json.dumps({"replies": [{"comment_id": "c1", "reply_text": "見つけてくださってありがとうございます。"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(comment_reply, "load_config", lambda: config)
    monkeypatch.setattr(comment_reply, "get_youtube", lambda: yt)
    monkeypatch.setattr(comment_reply, "_channel_dir", lambda: tmp_path)

    rc = comment_reply.main(
        [
            "--dry-run",
            "--json",
            "--video-id",
            "v1",
            "--agent-replies-file",
            str(replies_path),
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["planned"][0]["reply_source"] == "agent"
    assert payload["planned"][0]["reply_text"] == "@Alice 見つけてくださってありがとうございます。"
    _mock_default_genai_client.models.generate_content.assert_not_called()


def test_cli_non_json_summary_uses_reply_policy_not_rule(monkeypatch, tmp_path, capsys):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    config = SimpleNamespace(
        comments=_make_config(),
        youtube=SimpleNamespace(api=SimpleNamespace(language="ja")),
    )
    monkeypatch.setattr(comment_reply, "load_config", lambda: config)
    monkeypatch.setattr(comment_reply, "get_youtube", lambda: yt)
    monkeypatch.setattr(comment_reply, "_channel_dir", lambda: tmp_path)

    rc = comment_reply.main(["--dry-run", "--video-id", "v1"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "policy=all_comments" in out
    assert "provider=gemini" in out
    assert "rule=" not in out


def test_agent_replies_file_path_uses_provided_reply_without_generator(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(),
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={"c1": "見つけてくださってありがとうございます。"},
    )

    plan = replier.run(dry_run=True)

    assert len(plan.planned) == 1
    assert plan.planned[0]["reply_text"] == "@Alice 見つけてくださってありがとうございます。"
    assert plan.planned[0]["reply_source"] == "agent"
    _mock_default_genai_client.models.generate_content.assert_not_called()


def test_agent_replies_apply_posts_reply_and_saves_history_without_generator(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(),
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={"c1": "見つけてくださってありがとうございます。"},
    )

    plan = replier.run(dry_run=False)

    assert plan.planned[0]["reply_source"] == "agent"
    assert plan.replied[0]["reply_text"] == "@Alice 見つけてくださってありがとうございます。"
    assert plan.replied[0]["reply_source"] == "agent"
    yt._insert_mock.execute.assert_called_once()
    history = ReplyHistory(tmp_path / "comment_reply_history.json")
    assert history.has_replied("c1")
    assert history._data["replied"]["c1"]["reply_source"] == "agent"
    _mock_default_genai_client.models.generate_content.assert_not_called()


def test_agent_replies_over_max_length_is_truncated_without_generator(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(generator=GeneratorConfig(provider="gemini", model="gemini-3.5-flash", max_length=12)),
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={"c1": "123456789"},
    )

    plan = replier.run(dry_run=True)

    assert plan.planned[0]["reply_text"] == "@Alice 12345"
    _mock_default_genai_client.models.generate_content.assert_not_called()


def test_agent_replies_skip_when_mention_exceeds_max_length(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(generator=GeneratorConfig(provider="gemini", model="gemini-3.5-flash", max_length=5)),
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={"c1": "123456789"},
    )

    plan = replier.run(dry_run=False)

    assert plan.planned == []
    assert any(row["reason"] == "mention_exceeds_max_length" for row in plan.skipped)
    yt._insert_mock.execute.assert_not_called()
    _mock_default_genai_client.models.generate_content.assert_not_called()


def test_codex_generator_apply_requires_agent_replies(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(generator=GeneratorConfig(provider="codex", max_length=280)),
        channel_dir=tmp_path,
        default_language="ja",
    )

    with pytest.raises(ConfigError, match="codex"):
        replier.run(dry_run=False)

    yt._insert_mock.execute.assert_not_called()


def test_codex_generator_dry_run_requires_export_candidates_or_agent_replies(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(generator=GeneratorConfig(provider="codex", max_length=280)),
        channel_dir=tmp_path,
        default_language="ja",
    )

    with pytest.raises(ConfigError, match="codex"):
        replier.run(dry_run=True)

    yt._insert_mock.execute.assert_not_called()


def test_agent_replies_missing_comment_is_skipped_without_generator(tmp_path, _mock_default_genai_client):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(),
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={},
    )

    plan = replier.run(dry_run=True)

    assert plan.planned == []
    assert any(row["comment_id"] == "c1" and row["reason"] == "agent_reply_missing" for row in plan.skipped)
    _mock_default_genai_client.models.generate_content.assert_not_called()


def test_apply_calls_insert_and_saves_history(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}],
        },
    )
    sleep_calls: list[float] = []
    replier = CommentReplier(
        yt,
        config=_make_config(delay_between_replies_sec=1.5),
        channel_dir=tmp_path,
        default_language="ja",
        sleep_fn=sleep_calls.append,
    )
    plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    yt._insert_mock.execute.assert_called_once()
    # delay が呼ばれている
    assert sleep_calls == [1.5]

    # 履歴が保存されている
    history_path = tmp_path / "comment_reply_history.json"
    assert history_path.exists()
    history = ReplyHistory(history_path)
    assert history.has_replied("c1") is True


def test_already_replied_is_skipped(tmp_path):
    # 事前に履歴を仕込む
    existing = ReplyHistory(tmp_path / "comment_reply_history.json")
    existing.mark_replied("c1", {"video_id": "v1"})
    existing.save()

    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}],
        },
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=False)

    assert plan.planned == []
    assert plan.replied == []
    assert any(row["reason"] == "already_replied" for row in plan.skipped)
    yt._insert_mock.execute.assert_not_called()


def test_held_for_review_is_skipped(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [
                {
                    "comment_id": "c1",
                    "text": "こんにちは！",
                    "moderation_status": "heldForReview",
                }
            ],
        },
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)
    assert any(row["reason"].startswith("moderationStatus") for row in plan.skipped)
    assert plan.planned == []


def test_max_replies_per_run_caps_planned(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [{"comment_id": f"c{i}", "text": "こんにちは！", "author": f"U{i}"} for i in range(5)],
        },
    )
    replier = CommentReplier(
        yt,
        config=_make_config(max_replies_per_run=2),
        channel_dir=tmp_path,
        default_language="ja",
    )
    plan = replier.run(dry_run=True)
    assert len(plan.planned) == 2


def test_disabled_short_circuits(tmp_path):
    yt = _mock_youtube(video_ids=[], comments_by_video={})
    replier = CommentReplier(yt, config=_make_config(enabled=False), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)
    assert plan == plan  # no exception
    assert plan.planned == []
    # API も呼ばれない（disabled なので video 解決にも行かない）
    yt.channels.return_value.list.assert_not_called()


def test_ng_word_excludes_comment(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [
                {"comment_id": "c1", "text": "こんにちは、spam です"},
                {"comment_id": "c2", "text": "こんにちは！"},
            ],
        },
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)

    planned_ids = [row["comment_id"] for row in plan.planned]
    assert planned_ids == ["c2"]
    assert any(row["reason"] == "ng_word" for row in plan.skipped if row["comment_id"] == "c1")


def test_explicit_video_ids_skip_playlist_items_lookup(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1", "v2"],
        comments_by_video={"v2": [{"comment_id": "c2", "text": "こんにちは！", "author": "B"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True, video_ids=["v2"])

    assert len(plan.planned) == 1
    assert plan.planned[0]["video_id"] == "v2"
    # video_ids 指定時は uploads playlist（playlistItems）は解決されない
    yt.playlistItems.return_value.list.assert_not_called()


def test_comments_disabled_video_is_skipped_and_next_video_is_processed(tmp_path):
    err = _make_http_error(403, "Forbidden", "commentsDisabled")
    yt = _mock_youtube(
        video_ids=["disabled", "enabled"],
        comments_by_video={
            "disabled": err,
            "enabled": [{"comment_id": "c1", "text": "こんにちは！", "author": "Viewer"}],
        },
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    plan = replier.run(dry_run=True)

    assert len(plan.planned) == 1
    assert plan.planned[0]["video_id"] == "enabled"
    assert any(
        row["video_id"] == "disabled" and row["comment_id"] is None and row["reason"] == "comments_disabled"
        for row in plan.skipped
    )


def test_comments_disabled_explicit_video_id_is_skipped(tmp_path):
    err = _make_http_error(403, "Forbidden", "commentsDisabled")
    yt = _mock_youtube(video_ids=["disabled"], comments_by_video={"disabled": err})
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    plan = replier.run(dry_run=True, video_ids=["disabled"])

    assert plan.planned == []
    assert plan.skipped == [
        {
            "comment_id": None,
            "video_id": "disabled",
            "comment_author": None,
            "reason": "comments_disabled",
        }
    ]


def test_comment_threads_api_error_other_than_comments_disabled_is_raised(tmp_path):
    err = _make_http_error(403, "Forbidden", "quotaExceeded")
    yt = _mock_youtube(video_ids=["v1"], comments_by_video={"v1": err})
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    with pytest.raises(YouTubeAPIError) as exc_info:
        replier.run(dry_run=True)

    assert "quotaExceeded" in str(exc_info.value)


def test_api_error_recorded_in_errors(tmp_path):
    err = HttpError(_FakeResp(403, "Forbidden"), b'{"error": "forbidden"}')
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！"}]},
        insert_side_effect=err,
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=False)

    assert plan.replied == []
    assert len(plan.errors) == 1
    assert "comments.insert" in plan.errors[0]["error"]
    assert not (tmp_path / "comment_reply_history.json").exists()


def test_unrelated_comment_is_planned_after_basic_filters(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "まったく関係ない文章", "author": "Viewer"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)
    assert [row["comment_id"] for row in plan.planned] == ["c1"]
    assert plan.skipped == []


def test_ng_word_reason(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "spam"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)
    assert plan.planned == []
    assert any(row["reason"] == "ng_word" for row in plan.skipped)


def test_own_comment_is_skipped_when_owner_channel_id_provided(tmp_path):
    # Given: owner_channel_id が設定されており、同じ channel_id のコメントが混在
    owner_id = "UCowner"
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [
                # チャンネルオーナー自身のコメント（自分の返信に視聴者が反応したケース等）
                {
                    "comment_id": "c_own",
                    "text": "こんにちは！",
                    "author": "Owner",
                    "author_channel_id": owner_id,
                },
                # 視聴者のコメント
                {
                    "comment_id": "c_viewer",
                    "text": "こんにちは！",
                    "author": "Viewer",
                    "author_channel_id": "UCviewer",
                },
            ]
        },
    )
    replier = CommentReplier(
        yt,
        config=_make_config(),
        channel_dir=tmp_path,
        default_language="ja",
        owner_channel_id=owner_id,
    )
    plan = replier.run(dry_run=True)

    # Then: オーナーのコメントはスキップ、視聴者のは計画に含まれる
    planned_ids = [row["comment_id"] for row in plan.planned]
    assert "c_own" not in planned_ids
    assert "c_viewer" in planned_ids
    assert any(row["comment_id"] == "c_own" and row["reason"] == "own_comment" for row in plan.skipped)


def test_resolve_owner_channel_id_returns_and_caches(tmp_path):
    """正常系: channels().list(part="id") から channel_id を取得してキャッシュする."""
    yt = MagicMock()
    yt.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": "UC12345"}]}
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    replier._resolve_owner_channel_id()

    assert replier._owner_channel_id == "UC12345"
    yt.channels.return_value.list.assert_called_once_with(part="id", mine=True)


def test_resolve_owner_channel_id_raises_on_empty_items(tmp_path):
    """空 items 系: YouTubeAPIError が送出される."""
    from youtube_automation.utils.exceptions import YouTubeAPIError

    yt = MagicMock()
    yt.channels.return_value.list.return_value.execute.return_value = {"items": []}
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    with pytest.raises(YouTubeAPIError, match="チャンネルが見つかりません"):
        replier._resolve_owner_channel_id()


def test_resolve_owner_channel_id_raises_on_http_error(tmp_path):
    """HttpError 系: YouTubeAPIError に変換される."""
    from googleapiclient.errors import HttpError

    from youtube_automation.utils.exceptions import YouTubeAPIError

    class _FakeResp:
        status = 403
        reason = "Forbidden"

        def __getitem__(self, _key):
            return "application/json"

        def get(self, _key, default=None):
            return default

    err = HttpError(_FakeResp(), b'{"error": "forbidden"}')
    yt = MagicMock()
    yt.channels.return_value.list.return_value.execute.side_effect = err
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    with pytest.raises(YouTubeAPIError):
        replier._resolve_owner_channel_id()


def test_resolve_owner_channel_id_skips_if_already_set(tmp_path):
    """既設定時: API を呼ばずキャッシュ値を維持する."""
    yt = MagicMock()
    replier = CommentReplier(
        yt,
        config=_make_config(),
        channel_dir=tmp_path,
        default_language="ja",
        owner_channel_id="UCpre",
    )

    replier._resolve_owner_channel_id()

    yt.channels.assert_not_called()
    assert replier._owner_channel_id == "UCpre"


def test_own_comment_not_skipped_when_owner_channel_id_is_none(tmp_path):
    # Given: owner_channel_id が未設定（デフォルト）
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [
                {
                    "comment_id": "c1",
                    "text": "こんにちは！",
                    "author": "Anyone",
                    "author_channel_id": "UCsomeone",
                }
            ]
        },
    )
    # owner_channel_id を渡さない
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)

    # Then: own_comment スキップは働かない
    assert any(row["comment_id"] == "c1" for row in plan.planned)
    assert not any(row.get("reason") == "own_comment" for row in plan.skipped)


# --- リグレッション防止テスト（SRP: _fetch_channel_info / _iter_uploaded_video_ids） ---


def test_fetch_channel_info_returns_owner_and_uploads_playlist_id(tmp_path):
    """_fetch_channel_info が (owner_id, uploads_playlist_id) タプルを返すことを確認."""
    yt = _mock_youtube(video_ids=[], comments_by_video={})
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    owner_id, uploads_id = replier._fetch_channel_info()

    assert owner_id == "UCtest"
    assert uploads_id == "PLuploads"


def test_iter_uploaded_video_ids_does_not_mutate_owner_channel_id(tmp_path):
    """_iter_uploaded_video_ids が _owner_channel_id を変更せず channels.list を呼ばないことを確認（SRP）."""
    yt = _mock_youtube(video_ids=["v1", "v2"], comments_by_video={})
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")

    assert replier._owner_channel_id is None
    list(replier._iter_uploaded_video_ids("PLuploads"))
    assert replier._owner_channel_id is None
    yt.channels.assert_not_called()


# ─── LLM provider 関連 ───────────────────────────────────────────────────────


def _make_gemini_config(**overrides) -> Comments:
    """global provider=gemini を設定した Comments を返す."""
    base = dict(
        enabled=True,
        rules=[],
        ng_words=[],
        max_replies_per_run=20,
        delay_between_replies_sec=0.0,
        history_file="comment_reply_history.json",
        skip_held_for_review=True,
        generator=GeneratorConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            channel_persona="Warm lo-fi host",
            max_length=280,
            fallback_on_error="skip",
            requests_per_minute=30,
        ),
    )
    base.update(overrides)
    return Comments(**base)


def _make_mock_genai_client(reply_text: str = "AI reply") -> MagicMock:
    mock_response = MagicMock()
    mock_response.text = reply_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


def test_gemini_generator_used_when_configured(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!", "author": "Alice"}]},
    )
    mock_client = _make_mock_genai_client("Thanks for being first!")

    with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
        replier = CommentReplier(
            yt,
            config=_make_gemini_config(),
            channel_dir=tmp_path,
            default_language="ja",
        )
        plan = replier.run(dry_run=True)

    assert len(plan.planned) == 1
    assert plan.planned[0]["reply_text"] == "@Alice Thanks for being first!"
    assert plan.planned[0]["provider"] == "gemini"
    assert "template_key" not in plan.planned[0]


def test_gemini_generator_history_metadata_includes_generator(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "nice!", "author": "Bob"}]},
    )
    mock_client = _make_mock_genai_client("Thanks!")

    with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
        replier = CommentReplier(
            yt,
            config=_make_gemini_config(delay_between_replies_sec=0.0),
            channel_dir=tmp_path,
            default_language="ja",
        )
        plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    history = ReplyHistory(tmp_path / "comment_reply_history.json")
    assert history.has_replied("c1")
    metadata = history._data["replied"]["c1"]
    assert metadata["provider"] == "gemini"
    assert "template_key" not in metadata


def test_llm_retry_on_error_then_plans_reply(tmp_path):
    """fallback_on_error='retry' のとき、同じ provider で 1 回だけ再試行する."""
    config = _make_gemini_config(
        generator=GeneratorConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            channel_persona="Warm lo-fi host",
            max_length=280,
            fallback_on_error="retry",
            requests_per_minute=30,
        ),
    )
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "nice video!", "author": "Alice"}]},
    )
    mock_client = MagicMock()
    first_error = RuntimeError("API 失敗")
    retry_response = MagicMock()
    retry_response.text = "Retry reply"
    mock_client.models.generate_content.side_effect = [first_error, retry_response]

    with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
        replier = CommentReplier(yt, config=config, channel_dir=tmp_path, default_language="ja")
        plan = replier.run(dry_run=True)

    assert len(plan.planned) == 1
    assert plan.planned[0]["reply_text"] == "@Alice Retry reply"
    assert plan.errors == []
    assert mock_client.models.generate_content.call_count == 2


def test_llm_skip_on_error_when_fallback_is_skip(tmp_path):
    """fallback_on_error='skip' のとき、LLM 失敗でコメントをスキップする."""
    config = _make_gemini_config(
        generator=GeneratorConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            channel_persona="persona",
            max_length=280,
            fallback_on_error="skip",
            requests_per_minute=30,
        ),
    )
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!"}]},
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API 失敗")

    with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
        replier = CommentReplier(yt, config=config, channel_dir=tmp_path, default_language="ja")
        plan = replier.run(dry_run=True)

    assert plan.planned == []
    assert any(row["reason"] == "llm_error_skip" for row in plan.skipped)


def test_llm_retry_failure_is_skipped(tmp_path):
    """retry 再失敗時は退避せず llm_error_retry_failed でスキップする."""
    config = _make_gemini_config(
        generator=GeneratorConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            channel_persona="persona",
            max_length=280,
            fallback_on_error="retry",
            requests_per_minute=30,
        ),
    )
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!"}]},
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API 失敗")

    with patch(_PATCH_GENAI_CLIENT, return_value=mock_client):
        replier = CommentReplier(yt, config=config, channel_dir=tmp_path, default_language="ja")
        plan = replier.run(dry_run=True)

    assert plan.planned == []
    assert any(row["reason"] == "llm_error_retry_failed" for row in plan.skipped)
    assert mock_client.models.generate_content.call_count == 2


def test_legacy_rule_provider_is_ignored(tmp_path):
    """rules[].provider は後方互換で受け取るが処理では無視する."""
    config = _make_config(
        rules=[],
        generator=GeneratorConfig(
            provider="codex",
            model=None,
            channel_persona="persona",
            max_length=280,
            fallback_on_error="skip",
            requests_per_minute=30,
        ),
    )
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!", "author": "Alice"}]},
    )

    replier = CommentReplier(
        yt,
        config=config,
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={"c1": "Thanks!"},
    )
    plan = replier.run(dry_run=True)

    assert plan.planned[0]["provider"] == "codex"


def test_agent_and_export_paths_do_not_require_generator_setup(tmp_path):
    """provider を使わない経路は rule.provider validation を踏まず候補処理できる."""
    config = _make_config(
        rules=[],
        generator=GeneratorConfig(
            provider="codex",
            model=None,
            channel_persona="persona",
            max_length=280,
            fallback_on_error="skip",
            requests_per_minute=30,
        ),
    )
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!"}]},
    )
    export_replier = CommentReplier(yt, config=config, channel_dir=tmp_path, default_language="ja")

    export_plan = export_replier.run(dry_run=True, export_candidates=True)

    assert export_plan.planned[0]["reply_source"] == "agent_pending"

    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!"}]},
    )
    agent_replier = CommentReplier(
        yt,
        config=config,
        channel_dir=tmp_path,
        default_language="ja",
        agent_replies={"c1": "Thanks!"},
    )

    agent_plan = agent_replier.run(dry_run=True)

    assert agent_plan.planned[0]["reply_source"] == "agent"
    assert agent_plan.planned[0]["reply_text"] == "@Unknown Thanks!"


def _mock_youtube_with_status(
    *,
    video_ids: list[str],
    privacy_by_video: dict[str, str | None],
    comments_by_video: dict[str, list[dict]] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """videos().list を status preflight 用に side_effect 化した mock を返す.

    privacy_by_video の値が None の video は API 応答に含めない（削除済み扱い）。
    その他は privacyStatus として返す。`part="snippet"`（title 取得）は従来通り返す。
    """
    yt = _mock_youtube(
        video_ids=video_ids,
        comments_by_video=comments_by_video or {},
    )

    status_list_mock = MagicMock()

    def _videos_list(**kwargs):
        part = kwargs.get("part")
        if part == "status":
            requested = kwargs.get("id", "").split(",") if kwargs.get("id") else []
            items = [
                {"id": vid, "status": {"privacyStatus": privacy_by_video.get(vid)}}
                for vid in requested
                if privacy_by_video.get(vid) is not None
            ]
            result = MagicMock()
            result.execute.return_value = {"items": items}
            status_list_mock(**kwargs)
            return result
        # part="snippet"（title 取得）— video_ids 全件の title を返す
        result = MagicMock()
        result.execute.return_value = {
            "items": [{"id": vid, "snippet": {"title": f"Title of {vid}"}} for vid in video_ids],
        }
        return result

    yt.videos.return_value.list.side_effect = _videos_list
    return yt, status_list_mock


def test_preflight_skips_deleted_video(tmp_path):
    """削除済み video（API 応答に存在しない）は dry-run で video_not_found スキップ."""
    yt, _ = _mock_youtube_with_status(
        video_ids=["gone", "alive"],
        privacy_by_video={"gone": None, "alive": "public"},
        comments_by_video={"alive": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)

    assert any(
        row["video_id"] == "gone" and row["comment_id"] is None and row["reason"] == "video_not_found"
        for row in plan.skipped
    )
    # 通過した動画はコメント処理される
    assert [row["video_id"] for row in plan.planned] == ["alive"]


def test_preflight_skips_private_video(tmp_path):
    """private video は dry-run で video_private スキップ."""
    yt, _ = _mock_youtube_with_status(
        video_ids=["secret", "alive"],
        privacy_by_video={"secret": "private", "alive": "public"},
        comments_by_video={"alive": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)

    assert any(row["video_id"] == "secret" and row["reason"] == "video_private" for row in plan.skipped)
    assert [row["video_id"] for row in plan.planned] == ["alive"]


def test_preflight_passes_unlisted_video(tmp_path):
    """unlisted video はオーナーがコメント可能なため通過させる."""
    yt, _ = _mock_youtube_with_status(
        video_ids=["hidden"],
        privacy_by_video={"hidden": "unlisted"},
        comments_by_video={"hidden": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)

    assert not any(row["reason"] in ("video_not_found", "video_private") for row in plan.skipped)
    assert [row["video_id"] for row in plan.planned] == ["hidden"]


def test_preflight_applies_in_apply_mode(tmp_path):
    """apply モードでも preflight が動き、private への insert を未然に防ぐ."""
    yt, _ = _mock_youtube_with_status(
        video_ids=["secret"],
        privacy_by_video={"secret": "private"},
        comments_by_video={"secret": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=False)

    assert any(row["reason"] == "video_private" for row in plan.skipped)
    assert plan.replied == []
    yt._insert_mock.execute.assert_not_called()


def test_preflight_skips_status_check_for_history_recorded_video(tmp_path):
    """history に返信実績がある video は status check 対象外（quota 節約）."""
    existing = ReplyHistory(tmp_path / "comment_reply_history.json")
    existing.mark_replied("old", {"video_id": "known"})
    existing.save()

    yt, status_list_mock = _mock_youtube_with_status(
        video_ids=["known", "fresh"],
        privacy_by_video={"known": "public", "fresh": "public"},
        comments_by_video={
            "known": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}],
            "fresh": [{"comment_id": "c2", "text": "こんにちは！", "author": "B"}],
        },
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    replier.run(dry_run=True)

    # status preflight は履歴未記録の "fresh" のみを問い合わせる
    assert status_list_mock.call_count == 1
    requested_ids = status_list_mock.call_args.kwargs["id"].split(",")
    assert requested_ids == ["fresh"]


def test_preflight_chunks_video_ids_in_50s(tmp_path):
    """videos.list は 50 件単位で chunk 化して呼ばれる."""
    video_ids = [f"v{i}" for i in range(120)]
    yt, status_list_mock = _mock_youtube_with_status(
        video_ids=video_ids,
        privacy_by_video={vid: "public" for vid in video_ids},
        comments_by_video={},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    replier.run(dry_run=True)

    # 120 件 → 50 + 50 + 20 の 3 チャンク
    assert status_list_mock.call_count == 3
    chunk_sizes = [len(call.kwargs["id"].split(",")) for call in status_list_mock.call_args_list]
    assert chunk_sizes == [50, 50, 20]


def test_fetch_video_status_returns_none_for_missing_video(tmp_path):
    """fetch_video_status は API 応答に無い video を None で返す."""
    from youtube_automation.utils.comments.replier import fetch_video_status

    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "exists", "status": {"privacyStatus": "public"}}],
    }
    result = fetch_video_status(yt, ["exists", "missing"])

    assert result["exists"] == {"privacyStatus": "public"}
    assert result["missing"] is None


def test_fetch_video_status_wraps_http_error(tmp_path):
    """status 取得失敗は YouTubeAPIError に変換され、握りつぶされない."""
    from youtube_automation.utils.comments.replier import fetch_video_status

    err = _make_http_error(403, "Forbidden", "quotaExceeded")
    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.side_effect = err

    with pytest.raises(YouTubeAPIError):
        fetch_video_status(yt, ["v1"])


def test_legacy_rule_generator_key_is_ignored_by_loader():
    """旧 rules[].generator は後方互換で読み捨てる."""
    from youtube_automation.utils.config.loader import _build_comments

    merged = {
        "comments": {
            "enabled": True,
            "rules": [{"name": "bad", "keywords": ["hi"], "generator": "gemini"}],
        }
    }

    comments = _build_comments(merged)
    assert comments.rules == []


# ─── 履歴 save リトライのテスト (#382) ────────────────────────────────────────


def test_save_succeeds_first_try_no_warning(tmp_path, caplog):
    """save が初回で成功すればリトライ警告が出ない."""
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(delay_between_replies_sec=0.0),
        channel_dir=tmp_path,
        default_language="ja",
    )

    with caplog.at_level(logging.WARNING, logger="youtube_automation.utils.comments.replier"):
        plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    assert "save_failed" not in plan.replied[0]
    assert "履歴保存リトライ" not in caplog.text
    assert "履歴保存が 3 回失敗" not in caplog.text


def test_save_fails_once_then_succeeds_logs_warning(tmp_path, caplog):
    """save が 1 回失敗して 2 回目で成功したとき、リトライ警告が出るがエラーは出ない."""
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(delay_between_replies_sec=0.0),
        channel_dir=tmp_path,
        default_language="ja",
    )

    original_save = replier._history.save
    call_count = 0

    def _flaky_save():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("disk full")
        return original_save()

    with patch.object(replier._history, "save", side_effect=_flaky_save):
        with caplog.at_level(logging.WARNING, logger="youtube_automation.utils.comments.replier"):
            plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    assert "save_failed" not in plan.replied[0]
    assert plan.errors == []
    assert "履歴保存リトライ 1/3" in caplog.text
    assert "履歴保存が 3 回失敗" not in caplog.text


def test_save_fails_all_3_times_logs_error_and_flags_record(tmp_path, caplog):
    """save 全失敗時: エラーログ + save_failed フラグ + plan.errors 記録."""
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(delay_between_replies_sec=0.0),
        channel_dir=tmp_path,
        default_language="ja",
    )

    with patch.object(replier._history, "save", side_effect=OSError("disk full")):
        with caplog.at_level(logging.WARNING, logger="youtube_automation.utils.comments.replier"):
            plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    assert plan.replied[0]["save_failed"] is True
    assert plan.replied[0]["comment_id"] == "c1"
    # plan.errors に記録されている（CLI の exit code に反映）
    assert len(plan.errors) == 1
    assert "履歴保存が 3 回失敗" in plan.errors[0]["error"]
    assert plan.errors[0]["comment_id"] == "c1"
    # 3 回分のリトライ警告 + 最終エラー
    assert caplog.text.count("履歴保存リトライ") == 3
    assert "履歴保存が 3 回失敗" in caplog.text
    # ログレベル検証: WARNING 3 件 + ERROR 1 件
    replier_records = [r for r in caplog.records if r.name == "youtube_automation.utils.comments.replier"]
    warning_records = [r for r in replier_records if r.levelno == logging.WARNING]
    error_records = [r for r in replier_records if r.levelno == logging.ERROR]
    assert len(warning_records) == 3
    assert len(error_records) == 1


def test_save_fails_once_then_succeeds_log_levels(tmp_path, caplog):
    """部分失敗（1 回失敗 → 2 回目成功）: WARNING 1 件、ERROR 0 件."""
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(delay_between_replies_sec=0.0),
        channel_dir=tmp_path,
        default_language="ja",
    )

    original_save = replier._history.save
    call_count = 0

    def _flaky_save():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("disk full")
        return original_save()

    with patch.object(replier._history, "save", side_effect=_flaky_save):
        with caplog.at_level(logging.WARNING, logger="youtube_automation.utils.comments.replier"):
            plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    assert plan.errors == []
    replier_records = [r for r in caplog.records if r.name == "youtube_automation.utils.comments.replier"]
    warning_records = [r for r in replier_records if r.levelno == logging.WARNING]
    error_records = [r for r in replier_records if r.levelno == logging.ERROR]
    assert len(warning_records) == 1
    assert len(error_records) == 0


def test_same_comment_id_in_two_videos_only_inserts_once_when_save_always_fails(tmp_path):
    """save が全失敗しても mark_replied() のメモリ記録で同一実行内の二重返信を防ぐ."""
    # 同じ comment_id "c_dup" が 2 つの video に出現する fixture
    yt = _mock_youtube(
        video_ids=["v1", "v2"],
        comments_by_video={
            "v1": [{"comment_id": "c_dup", "text": "こんにちは！", "author": "Alice"}],
            "v2": [{"comment_id": "c_dup", "text": "こんにちは！", "author": "Alice"}],
        },
    )
    replier = CommentReplier(
        yt,
        config=_make_config(delay_between_replies_sec=0.0),
        channel_dir=tmp_path,
        default_language="ja",
    )

    with patch.object(replier._history, "save", side_effect=OSError("disk full")):
        plan = replier.run(dry_run=False)

    # insert は 1 回だけ（v1 の c_dup に対して）
    assert yt._insert_mock.execute.call_count == 1
    # replied に 1 件（v1 の c_dup）
    assert len(plan.replied) == 1
    assert plan.replied[0]["comment_id"] == "c_dup"
    # 2 件目は already_replied でスキップ
    assert any(row["comment_id"] == "c_dup" and row["reason"] == "already_replied" for row in plan.skipped)


# ─── save() 呼び出し回数の厳密検証 (#382) ───────────────────────────────────


def test_save_call_count_success_first_try(tmp_path):
    """save 成功時: save() は 1 回だけ呼ばれる."""
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(
        yt, config=_make_config(delay_between_replies_sec=0.0), channel_dir=tmp_path, default_language="ja"
    )

    with patch.object(replier._history, "save", wraps=replier._history.save) as mock_save:
        plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    assert mock_save.call_count == 1


def test_save_call_count_one_failure_then_success(tmp_path):
    """save 1 回失敗 → 2 回目成功: save() は 2 回呼ばれる."""
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(
        yt, config=_make_config(delay_between_replies_sec=0.0), channel_dir=tmp_path, default_language="ja"
    )

    original_save = replier._history.save
    effects = [OSError("disk full"), original_save]

    with patch.object(replier._history, "save", side_effect=effects) as mock_save:
        plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    assert mock_save.call_count == 2


def test_save_call_count_all_retries_exhausted(tmp_path):
    """save 全失敗: save() は _SAVE_MAX_RETRIES 回呼ばれる."""
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "A"}]},
    )
    replier = CommentReplier(
        yt, config=_make_config(delay_between_replies_sec=0.0), channel_dir=tmp_path, default_language="ja"
    )

    with patch.object(replier._history, "save", side_effect=OSError("disk full")) as mock_save:
        plan = replier.run(dry_run=False)

    assert len(plan.replied) == 1
    assert plan.replied[0]["save_failed"] is True
    assert mock_save.call_count == _SAVE_MAX_RETRIES
