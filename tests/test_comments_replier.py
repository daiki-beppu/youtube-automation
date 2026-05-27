"""CommentReplier の dry-run / apply 分岐、履歴、delay、上限のテスト."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.comments.history import ReplyHistory
from youtube_automation.utils.comments.replier import CommentReplier
from youtube_automation.utils.config.comments import (
    CommentRule,
    Comments,
    GeneratorConfig,
)

_PATCH_GENAI_CLIENT = "youtube_automation.utils.genai_client.create_genai_client"


def _mock_youtube(
    *,
    video_ids: list[str],
    comments_by_video: dict[str, list[dict]],
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


def _make_config(**overrides) -> Comments:
    base = dict(
        enabled=True,
        rules=[
            CommentRule(
                name="greeting",
                keywords=["こんにちは"],
                language="ja",
                priority=10,
            )
        ],
        generator=GeneratorConfig(
            provider="gemini",
            model="gemini-2.5-flash",
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

    assert len(plan.planned) == 1
    assert plan.planned[0]["comment_id"] == "c1"
    assert plan.planned[0]["reply_text"] == "Generated reply"
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
        rules=[
            CommentRule(
                name="catch_all",
                pattern=".+",
                priority=0,
            )
        ],
        ng_words=[],
        max_replies_per_run=20,
        delay_between_replies_sec=0.0,
        history_file="comment_reply_history.json",
        skip_held_for_review=True,
        generator=GeneratorConfig(
            provider="gemini",
            model="gemini-2.5-flash",
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
    assert plan.planned[0]["reply_text"] == "Thanks for being first!"
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
            model="gemini-2.5-flash",
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
    assert plan.planned[0]["reply_text"] == "Retry reply"
    assert plan.errors == []
    assert mock_client.models.generate_content.call_count == 2


def test_llm_skip_on_error_when_fallback_is_skip(tmp_path):
    """fallback_on_error='skip' のとき、LLM 失敗でコメントをスキップする."""
    config = _make_gemini_config(
        generator=GeneratorConfig(
            provider="gemini",
            model="gemini-2.5-flash",
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
            model="gemini-2.5-flash",
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


def test_rule_provider_override_gemini_requires_explicit_gemini_generator_config(tmp_path):
    """rule.provider='gemini' は Gemini 用 model が解決できない設定を拒否する."""
    config = _make_config(
        rules=[CommentRule(name="ai_rule", pattern=".+", provider="gemini")],
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

    from youtube_automation.utils.exceptions import ConfigError

    with pytest.raises(ConfigError, match="rule.provider='gemini'"):
        CommentReplier(yt, config=config, channel_dir=tmp_path, default_language="ja")


def test_legacy_rule_generator_key_rejected_by_loader():
    """旧 rules[].generator は ConfigError で停止する."""
    from youtube_automation.utils.config.loader import _build_comments
    from youtube_automation.utils.exceptions import ConfigError

    merged = {
        "comments": {
            "enabled": True,
            "rules": [{"name": "bad", "keywords": ["hi"], "generator": "gemini"}],
        }
    }

    with pytest.raises(ConfigError, match="comments.rules\\[0\\].generator"):
        _build_comments(merged)
