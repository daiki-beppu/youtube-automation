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
from youtube_automation.utils.comments.generator import build_generators
from youtube_automation.utils.comments.generator.base import GeneratedReply, ReplyContext, ReplyGenerator
from youtube_automation.utils.comments.history import ReplyHistory
from youtube_automation.utils.comments.rule_engine import RuleEngine, RuleMatch
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
    except HttpError as error:
        raise YouTubeAPIError.from_http_error(error, "channels.list (mine=True) 失敗") from error

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
        except HttpError as error:
            raise YouTubeAPIError.from_http_error(error, "playlistItems.list 失敗") from error
        for item in resp.get("items", []):
            yield item["contentDetails"]["videoId"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return


def _truncate_reply_text(text: str, *, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    logger.warning("generated reply exceeded max_length=%d and was truncated", max_length)
    return text[:max_length]


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
        self._generators = build_generators(config)
        self._last_generation_at: float | None = None

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
            default_generator_name=self._config.generator.type,
        )
        plan = ReplyPlan()
        limit = self._config.max_replies_per_run

        video_source: Iterator[str] = iter(video_ids) if video_ids else _iter_uploaded_video_ids(self._youtube)

        for video_id in video_source:
            if len(plan.planned) >= limit:
                break
            for comment in fetch_top_level_comments(
                self._youtube, video_id=video_id, max_results=per_video_limit, since=since
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
        except HttpError as error:
            raise YouTubeAPIError.from_http_error(error, f"videos.list 失敗 (video_id={video_id})") from error
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
        context = self._build_reply_context(comment, match, video_title)
        generated = self._generate_reply(context, match, comment, plan)
        if generated is None:
            return
        reply, generator_name = generated

        metadata = self._reply_metadata(comment, match, video_title, reply, generator_name)
        plan.planned.append({"comment_id": comment.comment_id, **metadata})

        if dry_run:
            return

        if self._post_reply(comment, metadata, plan):
            self._sleep(self._config.delay_between_replies_sec)

    def _build_reply_context(self, comment: FetchedComment, match: RuleMatch, video_title: str) -> ReplyContext:
        return ReplyContext(
            video_id=comment.video_id,
            video_title=video_title,
            comment_id=comment.comment_id,
            comment_text=comment.text,
            comment_author=comment.author,
            language=match.template_language if match.generator_name == "template" else None,
            channel_persona=self._config.generator.channel_persona,
            max_length=self._config.generator.max_length,
            parent_thread=None,
            template_text=match.template_text,
        )

    def _generate_reply(
        self,
        context: ReplyContext,
        match: RuleMatch,
        comment: FetchedComment,
        plan: ReplyPlan,
    ) -> tuple[GeneratedReply, str] | None:
        try:
            reply = self._generate_with_generator(match.generator_name, context)
        except Exception as error:  # noqa: BLE001
            return self._handle_generator_error(error, context, match, comment, plan)
        return self._normalized_reply(reply, max_length=context.max_length), match.generator_name

    def _generate_with_generator(self, generator_name: str, context: ReplyContext) -> GeneratedReply:
        generator = self._get_generator(generator_name)
        self._sleep_for_generation_interval(generator_name)
        reply = generator.generate(context)
        self._last_generation_at = time.monotonic()
        return reply

    def _get_generator(self, generator_name: str) -> ReplyGenerator:
        generator = self._generators.get(generator_name)
        if generator is None:
            raise RuntimeError(f"generator not configured: {generator_name}")
        return generator

    def _sleep_for_generation_interval(self, generator_name: str) -> None:
        if generator_name == "template":
            return
        interval = self._config.generator.min_interval_sec
        if interval <= 0 or self._last_generation_at is None:
            return
        self._sleep(interval)

    def _handle_generator_error(
        self,
        error: Exception,
        context: ReplyContext,
        match: RuleMatch,
        comment: FetchedComment,
        plan: ReplyPlan,
    ) -> tuple[GeneratedReply, str] | None:
        if match.generator_name != "template" and self._config.generator.fallback_on_error == "template":
            if "template" in self._generators and context.template_text is not None:
                reply = self._generate_with_generator("template", context)
                return self._normalized_reply(reply, max_length=context.max_length), "template"
        if self._config.generator.fallback_on_error == "skip":
            plan.skipped.append(self._skip_record(comment, f"generator_error: {error}"))
            return None
        plan.errors.append(self._error_record(comment, f"generator_error: {error}"))
        return None

    def _normalized_reply(self, reply: GeneratedReply, *, max_length: int) -> GeneratedReply:
        return GeneratedReply(
            text=_truncate_reply_text(reply.text, max_length=max_length),
            prompt=reply.prompt,
        )

    def _reply_metadata(
        self,
        comment: FetchedComment,
        match: RuleMatch,
        video_title: str,
        reply: GeneratedReply,
        generator_name: str,
    ) -> dict:
        template_key = match.rule.template_key if generator_name == "template" else None
        language = match.template_language if generator_name == "template" else None
        return {
            "video_id": comment.video_id,
            "video_title": video_title,
            "comment_author": comment.author,
            "comment_text": comment.text,
            "rule": match.rule.name,
            "generator": generator_name,
            "template_key": template_key,
            "language": language,
            "reply_text": reply.text,
            "prompt": reply.prompt,
        }

    def _skip_reason(self, comment: FetchedComment) -> str | None:
        if not comment.can_reply:
            return "canReply=False"
        if self._config.skip_held_for_review and comment.moderation_status == _HELD_FOR_REVIEW:
            return f"moderationStatus={_HELD_FOR_REVIEW}"
        if self._history.has_replied(comment.comment_id):
            return "already_replied"
        return None

    def _post_reply(self, comment: FetchedComment, metadata: dict, plan: ReplyPlan) -> bool:
        try:
            self._youtube.comments().insert(
                part="snippet",
                body={
                    "snippet": {
                        "parentId": comment.comment_id,
                        "textOriginal": metadata["reply_text"],
                    }
                },
            ).execute()
        except HttpError as error:
            status = getattr(getattr(error, "resp", None), "status", None)
            plan.errors.append(self._error_record(comment, f"comments.insert 失敗: status={status} {error}"))
            return False

        persisted = {
            **metadata,
            "replied_at": datetime.now(timezone.utc).isoformat(),
        }
        self._history.mark_replied(comment.comment_id, persisted)
        self._history.save()
        plan.replied.append({"comment_id": comment.comment_id, **persisted})
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
