"""ライブチャット取得・判定・投稿ループ."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from youtube_automation.configuration.comments import LiveChatConfig
from youtube_automation.infrastructure.errors import GeneratorError, YouTubeAPIError
from youtube_automation.infrastructure.retry import execute_with_retry
from youtube_automation.utils.live_chat.codex import CodexLiveChatGenerator
from youtube_automation.utils.live_chat.filters import audit_text
from youtube_automation.utils.live_chat.history import LiveChatHistory
from youtube_automation.utils.live_chat.models import LiveChatMessage

logger = logging.getLogger(__name__)
_PACIFIC = ZoneInfo("America/Los_Angeles")
_ENDED_REASONS = {"liveChatEnded", "liveChatNotFound", "liveChatDisabled"}


class LiveChatReplier:
    """公式 API の page token / polling interval 契約に従う前景ループ."""

    def __init__(
        self,
        youtube,
        *,
        config: LiveChatConfig,
        channel_dir: Path,
        generator: CodexLiveChatGenerator | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._youtube = youtube
        self._config = config
        self._history = LiveChatHistory(channel_dir / config.history_file)
        self._generator = generator or CodexLiveChatGenerator(
            model=config.model,
            timeout_sec=config.codex_timeout_sec,
        )
        self._sleep = sleep_fn
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    @property
    def history(self) -> LiveChatHistory:
        return self._history

    def resolve_active_chat_id(self) -> str | None:
        request = self._youtube.liveBroadcasts().list(
            part="snippet",
            broadcastStatus="active",
            mine=True,
        )
        response = execute_with_retry(request, "liveBroadcasts.list (active) failed")
        for item in response.get("items", []):
            chat_id = item.get("snippet", {}).get("liveChatId")
            if chat_id:
                return str(chat_id)
        return None

    def fetch_messages(self, chat_id: str, page_token: str | None) -> dict:
        parameters = {
            "part": "id,snippet,authorDetails",
            "liveChatId": chat_id,
            "maxResults": 200,
        }
        if page_token:
            parameters["pageToken"] = page_token
        request = self._youtube.liveChatMessages().list(**parameters)
        return execute_with_retry(request, "liveChatMessages.list failed")

    def run_forever(self, *, max_polls: int | None = None) -> None:
        if not self._config.enabled:
            logger.warning("comments.live_chat.enabled=false のため何もしません")
            return

        chat_id: str | None = None
        page_token: str | None = None
        polls = 0
        while max_polls is None or polls < max_polls:
            if chat_id is None:
                chat_id = self.resolve_active_chat_id()
                page_token = None
                if chat_id is None:
                    logger.info(
                        "アクティブ配信はありません。%.1f 秒後に再試行します",
                        self._config.no_broadcast_retry_sec,
                    )
                    self._sleep(self._config.no_broadcast_retry_sec)
                    continue
                logger.info("ライブチャットを検出: %s", chat_id)

            try:
                response = self.fetch_messages(chat_id, page_token)
            except YouTubeAPIError as error:
                if error.reason not in _ENDED_REASONS:
                    raise
                logger.info("ライブチャットが終了しました: %s", error.reason)
                chat_id = None
                page_token = None
                self._sleep(self._config.no_broadcast_retry_sec)
                continue

            polls += 1
            initial_page = page_token is None
            page_token = response.get("nextPageToken")
            messages = list(self._messages(response))
            if initial_page and not self._config.process_initial_messages:
                for message in messages:
                    if not self._history.has_processed(message.message_id):
                        self._history.mark(
                            message.message_id,
                            outcome="initial_backlog",
                            recorded_at=self._now().isoformat(),
                            author_channel_id=message.author_channel_id,
                        )
            else:
                for message in messages:
                    self._process(message, chat_id)

            interval = max(0.0, float(response.get("pollingIntervalMillis", 5000)) / 1000.0)
            if max_polls is None or polls < max_polls:
                self._sleep(interval)

    def _messages(self, response: dict):
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            author = item.get("authorDetails", {})
            if snippet.get("type") != "textMessageEvent" or author.get("isChatOwner"):
                continue
            message_id = item.get("id")
            text = snippet.get("textMessageDetails", {}).get("messageText")
            author_id = author.get("channelId") or snippet.get("authorChannelId")
            if not all(isinstance(value, str) and value for value in (message_id, text, author_id)):
                continue
            yield LiveChatMessage(
                message_id=message_id,
                author_channel_id=author_id,
                author_name=str(author.get("displayName", "")),
                text=text,
                published_at=str(snippet.get("publishedAt", "")),
            )

    def _process(self, message: LiveChatMessage, chat_id: str) -> None:
        if self._history.has_processed(message.message_id):
            return
        input_reason = audit_text(
            message.text,
            expected_language=self._config.language,
            ng_words=self._config.ng_words,
            max_length=1000,
        )
        if input_reason:
            self._mark_skip(message, f"input_{input_reason}")
            return
        rate_reason = self._rate_limit_reason(message.author_channel_id)
        if rate_reason:
            self._mark_skip(message, rate_reason)
            return
        try:
            decision = self._generator.decide(
                message,
                persona=self._config.channel_persona,
                language=self._config.language,
                max_length=self._config.max_length,
            )
        except GeneratorError as error:
            logger.warning("codex exec 失敗のため skip: %s", error)
            self._mark_skip(message, "codex_error", error=str(error))
            return
        if not decision.should_reply:
            self._mark_skip(message, "not_reply_worthy", decision_reason=decision.reason)
            return
        output_reason = audit_text(
            decision.reply_text,
            expected_language=self._config.language,
            ng_words=self._config.ng_words,
            max_length=self._config.max_length,
        )
        if output_reason:
            self._mark_skip(message, f"output_{output_reason}")
            return
        body = {
            "snippet": {
                "liveChatId": chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {"messageText": decision.reply_text},
            }
        }
        try:
            request = self._youtube.liveChatMessages().insert(part="snippet", body=body)
            response = execute_with_retry(request, "liveChatMessages.insert failed")
        except YouTubeAPIError as error:
            logger.warning("ライブチャット投稿失敗のため skip: %s", error)
            self._mark_skip(message, "insert_error", error=str(error))
            return
        self._history.mark(
            message.message_id,
            outcome="replied",
            recorded_at=self._now().isoformat(),
            author_channel_id=message.author_channel_id,
            author_name=message.author_name,
            reply_text=decision.reply_text,
            reply_message_id=response.get("id"),
            quota_cost=self._config.reply_quota_cost,
        )
        logger.info("ライブチャットへ返信: %s", message.message_id)

    def _mark_skip(self, message: LiveChatMessage, reason: str, **metadata) -> None:
        self._history.mark(
            message.message_id,
            outcome="skipped",
            recorded_at=self._now().isoformat(),
            reason=reason,
            author_channel_id=message.author_channel_id,
            **metadata,
        )

    def _rate_limit_reason(self, author_channel_id: str) -> str | None:
        now = self._now()
        replies = self._history.replied_records()
        recent = [record for record in replies if _parse_time(record.get("recorded_at")) >= now - timedelta(hours=1)]
        if len(recent) >= self._config.max_replies_per_hour:
            return "hourly_reply_limit"

        consecutive = 0
        for record in reversed(replies):
            if record.get("author_channel_id") != author_channel_id:
                break
            consecutive += 1
        if consecutive >= self._config.max_consecutive_per_user:
            return "consecutive_user_limit"

        today = now.astimezone(_PACIFIC).date()
        quota_used = sum(
            int(record.get("quota_cost", self._config.reply_quota_cost))
            for record in replies
            if _parse_time(record.get("recorded_at")).astimezone(_PACIFIC).date() == today
        )
        if quota_used + self._config.reply_quota_cost > self._config.daily_quota_budget:
            return "daily_quota_budget"
        return None


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
