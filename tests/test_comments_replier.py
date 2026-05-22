"""CommentReplier の dry-run / apply 分岐、履歴、delay、上限のテスト."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from youtube_automation.utils.comments.generator.base import GeneratedReply
from youtube_automation.utils.comments.history import ReplyHistory
from youtube_automation.utils.comments.replier import CommentReplier
from youtube_automation.utils.config.comments import CommentRule, Comments, GeneratorConfig


def _mock_youtube(
    *,
    video_ids: list[str],
    comments_by_video: dict[str, list[dict]],
    insert_side_effect=None,
) -> MagicMock:
    """youtube.* チェーン呼び出しを MagicMock で構築."""
    yt = MagicMock()

    # channels().list(part=..., mine=True).execute()
    yt.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "PLuploads"}}}]
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
        items = []
        for c in raw:
            items.append(
                {
                    "snippet": {
                        "canReply": c.get("can_reply", True),
                        "totalReplyCount": c.get("total_reply_count", 0),
                        "topLevelComment": {
                            "id": c["comment_id"],
                            "snippet": {
                                "authorDisplayName": c.get("author", "Unknown"),
                                "textOriginal": c["text"],
                                "publishedAt": c.get("published_at", "2026-04-01T00:00:00Z"),
                                "moderationStatus": c.get("moderation_status"),
                            },
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


def _make_config(**overrides) -> Comments:
    base = dict(
        enabled=True,
        rules=[
            CommentRule(
                name="greeting",
                keywords=["こんにちは"],
                template_key="greet",
                language="ja",
                priority=10,
            )
        ],
        templates={"ja": {"greet": "{comment_author}さん、{video_title} を見てくれてありがとう！"}},
        ng_words=["spam"],
        max_replies_per_run=20,
        delay_between_replies_sec=0.0,
        history_file="comment_reply_history.json",
        skip_held_for_review=True,
        generator=GeneratorConfig(
            type="template",
            model="",
            channel_persona="",
            max_length=280,
            fallback_on_error="template",
            min_interval_sec=0.0,
        ),
    )
    base.update(overrides)
    return Comments(**base)


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

    assert len(plan.planned) == 1
    assert plan.planned[0]["comment_id"] == "c1"
    assert "Alice" in plan.planned[0]["reply_text"]
    assert plan.replied == []
    yt._insert_mock.execute.assert_not_called()

    # 履歴ファイルは書かれない
    assert not (tmp_path / "comment_reply_history.json").exists()


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
    assert any(row["reason"] == "no_rule_matched" for row in plan.skipped if row["comment_id"] == "c1")


def test_explicit_video_ids_skip_channel_resolution(tmp_path):
    yt = _mock_youtube(
        video_ids=["v1", "v2"],
        comments_by_video={"v2": [{"comment_id": "c2", "text": "こんにちは！", "author": "B"}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True, video_ids=["v2"])

    assert len(plan.planned) == 1
    assert plan.planned[0]["video_id"] == "v2"
    # mine=True 解決は呼ばれない
    yt.channels.return_value.list.assert_not_called()


def test_api_error_recorded_in_errors(tmp_path):
    from googleapiclient.errors import HttpError

    class _FakeResp:
        status = 403
        reason = "Forbidden"

        def __getitem__(self, _key):
            return "application/json"

        def get(self, _key, default=None):
            return default

    err = HttpError(_FakeResp(), b'{"error": "forbidden"}')
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


@pytest.mark.parametrize(
    "reason_text,expected_reason",
    [
        ("spam", "no_rule_matched"),
        ("まったく関係ない文章", "no_rule_matched"),
    ],
)
def test_no_match_reasons(tmp_path, reason_text, expected_reason):
    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": reason_text}]},
    )
    replier = CommentReplier(yt, config=_make_config(), channel_dir=tmp_path, default_language="ja")
    plan = replier.run(dry_run=True)
    assert plan.planned == []
    assert any(row["reason"] == expected_reason for row in plan.skipped)


def test_dry_run_records_llm_prompt_and_generator_metadata(tmp_path, monkeypatch):
    class _Generator:
        def __init__(self):
            self.calls = []

        def generate(self, ctx):
            self.calls.append(ctx)
            return GeneratedReply(
                text="Aliceさん、来てくれてありがとう！",
                prompt="reply to Alice in rainy jazz tone",
            )

    generator = _Generator()
    monkeypatch.setattr(
        "youtube_automation.utils.comments.replier.build_generators",
        lambda config: {"gemini": generator},
    )

    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(
            rules=[CommentRule(name="default_ai", pattern=r".+", language="en", priority=0, generator="gemini")],
            templates={},
            generator=GeneratorConfig(
                type="gemini",
                model="gemini-2.5-flash",
                channel_persona="Rain Jazz Night host",
                max_length=180,
                fallback_on_error="template",
                min_interval_sec=0.0,
            ),
        ),
        channel_dir=tmp_path,
        default_language="ja",
    )

    plan = replier.run(dry_run=True)

    assert len(plan.planned) == 1
    assert plan.planned[0]["generator"] == "gemini"
    assert plan.planned[0]["template_key"] is None
    assert plan.planned[0]["prompt"] == "reply to Alice in rainy jazz tone"
    assert plan.planned[0]["reply_text"] == "Aliceさん、来てくれてありがとう！"
    assert plan.planned[0]["language"] is None
    assert generator.calls[0].language is None
    assert generator.calls[0].parent_thread is None
    assert generator.calls[0].channel_persona == "Rain Jazz Night host"
    assert generator.calls[0].max_length == 180
    yt._insert_mock.execute.assert_not_called()


def test_dry_run_truncates_generated_reply_to_max_length_and_warns(tmp_path, monkeypatch, caplog):
    class _Generator:
        def generate(self, _ctx):
            return GeneratedReply(text="ABCDEFGHIJKLMN", prompt="reply briefly")

    monkeypatch.setattr(
        "youtube_automation.utils.comments.replier.build_generators",
        lambda config: {"gemini": _Generator()},
    )

    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(
            rules=[CommentRule(name="default_ai", pattern=r".+", priority=0, generator="gemini")],
            templates={},
            generator=GeneratorConfig(
                type="gemini",
                model="gemini-2.5-flash",
                channel_persona="Rain Jazz Night host",
                max_length=10,
                fallback_on_error="template",
                min_interval_sec=0.0,
            ),
        ),
        channel_dir=tmp_path,
        default_language="ja",
    )

    with caplog.at_level("WARNING"):
        plan = replier.run(dry_run=True)

    assert len(plan.planned) == 1
    assert plan.planned[0]["reply_text"] == "ABCDEFGHIJ"
    assert any("max_length" in record.message for record in caplog.records)


def test_generator_error_falls_back_to_template(tmp_path, monkeypatch):
    class _FailingGenerator:
        def generate(self, _ctx):
            raise RuntimeError("gemini unavailable")

    class _TemplateGenerator:
        def __init__(self):
            self.called = 0

        def generate(self, _ctx):
            self.called += 1
            return GeneratedReply(text="Aliceさん、ありがとう！", prompt=None)

    template_generator = _TemplateGenerator()
    monkeypatch.setattr(
        "youtube_automation.utils.comments.replier.build_generators",
        lambda config: {
            "gemini": _FailingGenerator(),
            "template": template_generator,
        },
    )

    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(
            rules=[CommentRule(name="greeting", keywords=["こんにちは"], template_key="greet", generator="gemini")],
            generator=GeneratorConfig(
                type="gemini",
                model="gemini-2.5-flash",
                channel_persona="Rain Jazz Night host",
                max_length=180,
                fallback_on_error="template",
                min_interval_sec=0.0,
            ),
        ),
        channel_dir=tmp_path,
        default_language="ja",
    )

    plan = replier.run(dry_run=True)

    assert len(plan.planned) == 1
    assert plan.planned[0]["reply_text"] == "Aliceさん、ありがとう！"
    assert template_generator.called == 1
    assert plan.errors == []


def test_generator_error_with_skip_fallback_records_skipped_without_insert(tmp_path, monkeypatch):
    class _FailingGenerator:
        def generate(self, _ctx):
            raise RuntimeError("gemini unavailable")

    monkeypatch.setattr(
        "youtube_automation.utils.comments.replier.build_generators",
        lambda config: {"gemini": _FailingGenerator()},
    )

    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "こんにちは！", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(
            rules=[CommentRule(name="greeting", keywords=["こんにちは"], template_key="greet", generator="gemini")],
            generator=GeneratorConfig(
                type="gemini",
                model="gemini-2.5-flash",
                channel_persona="Rain Jazz Night host",
                max_length=180,
                fallback_on_error="skip",
                min_interval_sec=0.0,
            ),
        ),
        channel_dir=tmp_path,
        default_language="ja",
    )

    plan = replier.run(dry_run=False)

    assert plan.planned == []
    assert plan.replied == []
    assert any(row["comment_id"] == "c1" for row in plan.skipped)
    yt._insert_mock.execute.assert_not_called()


def test_dry_run_rate_limits_llm_generation_separately_from_reply_delay(tmp_path, monkeypatch):
    class _Generator:
        def __init__(self):
            self.calls = []

        def generate(self, ctx):
            self.calls.append(ctx.comment_id)
            return GeneratedReply(text=f"reply-{ctx.comment_id}", prompt=f"prompt-{ctx.comment_id}")

    generator = _Generator()
    monkeypatch.setattr(
        "youtube_automation.utils.comments.replier.build_generators",
        lambda config: {"gemini": generator},
    )

    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={
            "v1": [
                {"comment_id": "c1", "text": "first!", "author": "Alice"},
                {"comment_id": "c2", "text": "nice!", "author": "Bob"},
            ]
        },
    )
    sleep_calls: list[float] = []
    replier = CommentReplier(
        yt,
        config=_make_config(
            rules=[CommentRule(name="default_ai", pattern=r".+", priority=0, generator="gemini")],
            templates={},
            delay_between_replies_sec=0.0,
            generator=GeneratorConfig(
                type="gemini",
                model="gemini-2.5-flash",
                channel_persona="Rain Jazz Night host",
                max_length=180,
                fallback_on_error="template",
                min_interval_sec=2.5,
            ),
        ),
        channel_dir=tmp_path,
        default_language="ja",
        sleep_fn=sleep_calls.append,
    )

    plan = replier.run(dry_run=True)

    assert [row["comment_id"] for row in plan.planned] == ["c1", "c2"]
    assert generator.calls == ["c1", "c2"]
    assert sleep_calls == [2.5]
    yt._insert_mock.execute.assert_not_called()


def test_apply_persists_generator_metadata_in_history(tmp_path, monkeypatch):
    class _Generator:
        def generate(self, _ctx):
            return GeneratedReply(text="Custom reply", prompt="custom prompt")

    monkeypatch.setattr(
        "youtube_automation.utils.comments.replier.build_generators",
        lambda config: {"gemini": _Generator()},
    )

    yt = _mock_youtube(
        video_ids=["v1"],
        comments_by_video={"v1": [{"comment_id": "c1", "text": "first!", "author": "Alice"}]},
    )
    replier = CommentReplier(
        yt,
        config=_make_config(
            rules=[CommentRule(name="default_ai", pattern=r".+", priority=0, generator="gemini")],
            templates={},
            generator=GeneratorConfig(
                type="gemini",
                model="gemini-2.5-flash",
                channel_persona="Rain Jazz Night host",
                max_length=180,
                fallback_on_error="template",
                min_interval_sec=0.0,
            ),
        ),
        channel_dir=tmp_path,
        default_language="ja",
    )

    plan = replier.run(dry_run=False)
    history_data = json.loads((tmp_path / "comment_reply_history.json").read_text(encoding="utf-8"))

    assert len(plan.replied) == 1
    assert plan.replied[0]["generator"] == "gemini"
    assert plan.replied[0]["template_key"] is None
    assert history_data["replied"]["c1"]["generator"] == "gemini"
    assert history_data["replied"]["c1"]["template_key"] is None
    assert history_data["replied"]["c1"]["prompt"] == "custom prompt"
