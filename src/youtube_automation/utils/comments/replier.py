"""コメント自動返信の司令塔（dry-run / apply）."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from googleapiclient.errors import HttpError

from youtube_automation.utils.comments.fetcher import FetchedComment, fetch_top_level_comments
from youtube_automation.utils.comments.history import ReplyHistory
from youtube_automation.utils.comments.rule_engine import RuleEngine, RuleMatch
from youtube_automation.utils.comments.template import render_template
from youtube_automation.utils.config.comments import Comments
from youtube_automation.utils.exceptions import YouTubeAPIError

logger = logging.getLogger(__name__)

_HELD_FOR_REVIEW = "heldForReview"


@dataclass
class ReplyPlan:
    """dry-run / apply 実行後のサマリー."""

    planned: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    replied: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def _iter_uploaded_video_ids(youtube) -> Iterator[str]:
    """自チャンネルのアップロード動画 ID を generator で返す（早期 break 可能）."""
    try:
        channel_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, "channels.list (mine=True) 失敗") from e

    items = channel_resp.get("items") or []
    if not items:
        return
    uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    page_token: str | None = None
    while True:
        try:
            resp = (
                youtube.playlistItems()
                .list(
                    part="contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                )
                .execute()
            )
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "playlistItems.list 失敗") from e
        for item in resp.get("items", []):
            yield item["contentDetails"]["videoId"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return


class CommentReplier:
    """コメント自動返信の実行司令塔."""

    def __init__(
        self,
        youtube,
        *,
        config: Comments,
        channel_dir: Path,
        default_language: str,
        sleep_fn=time.sleep,
    ):
        self._youtube = youtube
        self._config = config
        self._channel_dir = channel_dir
        self._default_language = default_language
        self._sleep = sleep_fn
        self._history = ReplyHistory(channel_dir / config.history_file)
        self._title_cache: dict[str, str] = {}

    @property
    def history(self) -> ReplyHistory:
        return self._history

    def run(
        self,
        *,
        dry_run: bool,
        video_ids: list[str] | None = None,
        per_video_limit: int = 100,
        since: datetime | None = None,
    ) -> ReplyPlan:
        """返信を計画 / 実行する."""
        if not self._config.enabled:
            logger.warning("comments.enabled=false のため、何もしません")
            return ReplyPlan()

        engine = RuleEngine(
            rules=self._config.rules,
            templates=self._config.templates,
            default_language=self._default_language,
            ng_words=self._config.ng_words,
        )
        plan = ReplyPlan()
        limit = self._config.max_replies_per_run

        video_source: Iterator[str] = iter(video_ids) if video_ids else _iter_uploaded_video_ids(self._youtube)

        for vid in video_source:
            if len(plan.planned) >= limit:
                break
            for comment in fetch_top_level_comments(
                self._youtube, video_id=vid, max_results=per_video_limit, since=since
            ):
                if len(plan.planned) >= limit:
                    break
                self._process_comment(comment, engine, plan, dry_run)

        return plan

    def _get_title(self, video_id: str) -> str:
        if video_id in self._title_cache:
            return self._title_cache[video_id]
        try:
            resp = self._youtube.videos().list(part="snippet", id=video_id).execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, f"videos.list 失敗 (video_id={video_id})") from e
        title = ""
        for item in resp.get("items", []):
            title = item["snippet"].get("title", "")
            break
        self._title_cache[video_id] = title
        return title

    def _process_comment(
        self,
        comment: FetchedComment,
        engine: RuleEngine,
        plan: ReplyPlan,
        dry_run: bool,
    ) -> None:
        skip_reason = self._skip_reason(comment)
        if skip_reason is not None:
            plan.skipped.append(self._skip_record(comment, skip_reason))
            return

        match = engine.evaluate(comment.text)
        if match is None:
            plan.skipped.append(self._skip_record(comment, "no_rule_matched"))
            return

        video_title = self._get_title(comment.video_id)
        try:
            reply_text = render_template(
                match.template_text,
                context={
                    "video_title": video_title,
                    "video_id": comment.video_id,
                    "comment_author": comment.author,
                    "comment_text": comment.text,
                },
            )
        except Exception as e:  # noqa: BLE001
            plan.errors.append(self._error_record(comment, f"template_error: {e}"))
            return

        plan.planned.append(
            {
                "comment_id": comment.comment_id,
                "video_id": comment.video_id,
                "video_title": video_title,
                "comment_author": comment.author,
                "comment_text": comment.text,
                "rule": match.rule.name,
                "template_key": match.rule.template_key,
                "language": match.template_language,
                "reply_text": reply_text,
            }
        )

        if dry_run:
            return

        if self._post_reply(comment, reply_text, match, video_title, plan):
            self._sleep(self._config.delay_between_replies_sec)

    def _skip_reason(self, comment: FetchedComment) -> str | None:
        if not comment.can_reply:
            return "canReply=False"
        if self._config.skip_held_for_review and comment.moderation_status == _HELD_FOR_REVIEW:
            return f"moderationStatus={_HELD_FOR_REVIEW}"
        if self._history.has_replied(comment.comment_id):
            return "already_replied"
        return None

    def _post_reply(
        self,
        comment: FetchedComment,
        reply_text: str,
        match: RuleMatch,
        video_title: str,
        plan: ReplyPlan,
    ) -> bool:
        try:
            self._youtube.comments().insert(
                part="snippet",
                body={
                    "snippet": {
                        "parentId": comment.comment_id,
                        "textOriginal": reply_text,
                    }
                },
            ).execute()
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            plan.errors.append(
                self._error_record(
                    comment,
                    f"comments.insert 失敗: status={status} {e}",
                )
            )
            return False

        metadata = {
            "video_id": comment.video_id,
            "video_title": video_title,
            "comment_author": comment.author,
            "rule": match.rule.name,
            "template_key": match.rule.template_key,
            "language": match.template_language,
            "replied_at": datetime.now(timezone.utc).isoformat(),
            "reply_text": reply_text,
        }
        self._history.mark_replied(comment.comment_id, metadata)
        # 途中断絶時の二重返信を防ぐため、返信成功ごとに履歴を永続化する
        self._history.save()
        plan.replied.append({"comment_id": comment.comment_id, **metadata})
        return True

    @staticmethod
    def _skip_record(comment: FetchedComment, reason: str) -> dict:
        return {
            "comment_id": comment.comment_id,
            "video_id": comment.video_id,
            "comment_author": comment.author,
            "reason": reason,
        }

    @staticmethod
    def _error_record(comment: FetchedComment, message: str) -> dict:
        return {
            "comment_id": comment.comment_id,
            "video_id": comment.video_id,
            "comment_author": comment.author,
            "error": message,
        }
