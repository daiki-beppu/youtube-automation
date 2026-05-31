"""コメント自動返信の司令塔（dry-run / apply）."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from googleapiclient.errors import HttpError

from youtube_automation.utils.comments.fetcher import FetchedComment, fetch_comments
from youtube_automation.utils.comments.generator import (
    ReplyContext,
    ReplyGenerator,
)
from youtube_automation.utils.comments.generator_factory import create_reply_generator
from youtube_automation.utils.comments.history import ReplyHistory
from youtube_automation.utils.comments.rule_engine import RuleEngine, RuleMatch
from youtube_automation.utils.config.comments import (
    FALLBACK_RETRY,
    PROVIDER_CODEX,
    PROVIDER_GEMINI,
    Comments,
    GeneratorConfig,
)
from youtube_automation.utils.exceptions import ConfigError, GeneratorError, YouTubeAPIError

logger = logging.getLogger(__name__)

_HELD_FOR_REVIEW = "heldForReview"
_COMMENTS_DISABLED_API_REASON = "commentsDisabled"
_COMMENTS_DISABLED_SKIP_REASON = "comments_disabled"

# videos.list の id 上限（1 リクエストあたり 50 件）
_VIDEOS_LIST_CHUNK = 50
_PRIVACY_STATUS_PRIVATE = "private"
_SKIP_VIDEO_NOT_FOUND = "video_not_found"
_SKIP_VIDEO_PRIVATE = "video_private"


def fetch_video_status(youtube, video_ids: list[str]) -> dict[str, dict | None]:
    """video_ids の status を videos.list で一括取得する（50 件単位で chunk 化）.

    Args:
        youtube: `youtube_service.get_youtube()` / `ServiceRegistry.youtube`
        video_ids: status を確認したい動画 ID のリスト

    Returns:
        `{video_id: status_dict | None}`。API 応答に存在しない（削除済み等）video は
        `None`。status_dict は videos.list の `status` part（`privacyStatus` 等）。

    Raises:
        YouTubeAPIError: HttpError を status_code 付きでラップ（取得失敗は握りつぶさない）
    """
    result: dict[str, dict | None] = {vid: None for vid in video_ids}
    for start in range(0, len(video_ids), _VIDEOS_LIST_CHUNK):
        chunk = video_ids[start : start + _VIDEOS_LIST_CHUNK]
        try:
            resp = youtube.videos().list(part="status", id=",".join(chunk)).execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, f"videos.list (status) 失敗 (count={len(chunk)})") from e
        for item in resp.get("items", []):
            result[item["id"]] = item.get("status", {})
    return result


@dataclass
class ReplyPlan:
    """dry-run / apply 実行後のサマリー."""

    planned: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    replied: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


class CommentReplier:
    """コメント自動返信の実行司令塔."""

    def __init__(
        self,
        youtube,
        *,
        config: Comments,
        channel_dir: Path,
        default_language: str,
        owner_channel_id: str | None = None,
        sleep_fn=time.sleep,
    ):
        self._youtube = youtube
        self._config = config
        self._channel_dir = channel_dir
        self._default_language = default_language
        self._owner_channel_id = owner_channel_id
        self._sleep = sleep_fn
        self._history = ReplyHistory(channel_dir / config.history_file)
        self._title_cache: dict[str, str] = {}
        self._generators = self._create_generators()

    @property
    def history(self) -> ReplyHistory:
        return self._history

    def _resolve_owner_channel_id(self) -> None:
        """owner_channel_id が未解決の場合に channels.list API で取得しキャッシュする."""
        if self._owner_channel_id is not None:
            return
        try:
            resp = self._youtube.channels().list(part="id", mine=True).execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "channels.list (owner channel ID) 失敗") from e
        items = resp.get("items") or []
        if not items:
            raise YouTubeAPIError("channels.list が空を返しました — チャンネルが見つかりません")
        self._owner_channel_id = items[0]["id"]

    def _fetch_channel_info(self) -> tuple[str, str]:
        """channels().list(part="contentDetails") から (owner_id, uploads_playlist_id) を返す."""
        try:
            resp = self._youtube.channels().list(part="contentDetails", mine=True).execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "channels.list (mine=True) 失敗") from e
        items = resp.get("items") or []
        if not items:
            raise YouTubeAPIError("channels.list が空を返しました — チャンネルが見つかりません")
        return items[0]["id"], items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def _iter_uploaded_video_ids(self, uploads_playlist_id: str) -> Iterator[str]:
        """自チャンネルのアップロード動画 ID を generator で返す（早期 break 可能）."""
        page_token: str | None = None
        while True:
            try:
                resp = (
                    self._youtube.playlistItems()
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

    def _create_generators(self) -> dict[str, ReplyGenerator]:
        providers = {self._config.generator.provider}
        providers.update(rule.provider for rule in self._config.rules if rule.provider is not None)
        return {
            provider: create_reply_generator(self._generator_config_for(provider), sleep_fn=self._sleep)
            for provider in providers
        }

    def _generator_config_for(self, provider: str) -> GeneratorConfig:
        if provider == self._config.generator.provider:
            return self._config.generator
        if provider == PROVIDER_GEMINI:
            raise ConfigError(
                "rule.provider='gemini' には comments.generator.provider='gemini' と model 設定が必要です"
            )
        if provider == PROVIDER_CODEX:
            return GeneratorConfig(
                provider=PROVIDER_CODEX,
                model=None,
                channel_persona=self._config.generator.channel_persona,
                max_length=self._config.generator.max_length,
                fallback_on_error=self._config.generator.fallback_on_error,
                requests_per_minute=self._config.generator.requests_per_minute,
            )
        raise ConfigError(f"comments provider 未対応: {provider!r}")

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
            default_language=self._default_language,
            ng_words=self._config.ng_words,
            default_provider=self._config.generator.provider,
        )
        plan = ReplyPlan()
        limit = self._config.max_replies_per_run

        if video_ids is not None:
            # 明示指定時: uploads playlist 解決は不要だが owner_channel_id は別途解決する
            self._resolve_owner_channel_id()
            target_video_ids = list(video_ids)
        else:
            owner_id, uploads_playlist_id = self._fetch_channel_info()
            self._owner_channel_id = self._owner_channel_id or owner_id
            target_video_ids = list(self._iter_uploaded_video_ids(uploads_playlist_id))

        # preflight: 削除済み / private video を dry-run / apply 共通で事前 skip する
        target_video_ids = self._preflight_video_status(target_video_ids, plan)

        for vid in target_video_ids:
            if len(plan.planned) >= limit:
                break
            self._process_video_comments(vid, engine, plan, dry_run, per_video_limit, since, limit)

        return plan

    def _preflight_video_status(self, video_ids: list[str], plan: ReplyPlan) -> list[str]:
        """video status を一括取得し、削除済み / private を plan.skipped に積んで除外する.

        quota 節約のため、history に返信実績がある video は status check を省く
        （過去に到達できた video は引き続き存在するとみなす）。

        Returns:
            preflight を通過した（コメント処理を続行すべき）video_id のリスト。
        """
        replied_videos = self._history.replied_video_ids()
        to_check = [vid for vid in video_ids if vid not in replied_videos]
        statuses = fetch_video_status(self._youtube, to_check) if to_check else {}

        allowed: list[str] = []
        for vid in video_ids:
            if vid in replied_videos:
                allowed.append(vid)
                continue
            status = statuses.get(vid)
            if status is None:
                plan.skipped.append(self._video_skip_record(vid, _SKIP_VIDEO_NOT_FOUND))
                continue
            if status.get("privacyStatus") == _PRIVACY_STATUS_PRIVATE:
                plan.skipped.append(self._video_skip_record(vid, _SKIP_VIDEO_PRIVATE))
                continue
            allowed.append(vid)
        return allowed

    def _process_video_comments(
        self,
        video_id: str,
        engine: RuleEngine,
        plan: ReplyPlan,
        dry_run: bool,
        per_video_limit: int,
        since: datetime | None,
        limit: int,
    ) -> None:
        comments = fetch_comments(self._youtube, video_id=video_id, max_results=per_video_limit, since=since)
        while len(plan.planned) < limit:
            try:
                comment = next(comments)
            except StopIteration:
                return
            except YouTubeAPIError as e:
                if not _is_comments_disabled_error(e):
                    raise
                plan.skipped.append(self._video_skip_record(video_id, _COMMENTS_DISABLED_SKIP_REASON))
                return
            self._process_comment(comment, engine, plan, dry_run)

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

        match = engine.evaluate(comment.text, is_reply=comment.parent_id is not None)
        if match is None:
            plan.skipped.append(self._skip_record(comment, "no_rule_matched"))
            return

        video_title = self._get_title(comment.video_id)

        ctx = ReplyContext(
            video_id=comment.video_id,
            video_title=video_title,
            comment_id=comment.comment_id,
            comment_text=comment.text,
            comment_author=comment.author,
            language=match.language,
            channel_persona=self._config.generator.channel_persona,
            max_length=self._config.generator.max_length,
            parent_thread=None,
            dry_run=dry_run,
        )

        reply_text = self._generate_reply(comment, match, ctx, plan)
        if reply_text is None:
            return

        plan.planned.append(
            {
                "comment_id": comment.comment_id,
                "video_id": comment.video_id,
                "video_title": video_title,
                "comment_author": comment.author,
                "comment_text": comment.text,
                "rule": match.rule.name,
                **self._generator_metadata(match),
                "language": match.language,
                "reply_text": reply_text,
            }
        )

        if dry_run:
            return

        if self._post_reply(comment, reply_text, match, video_title, plan):
            self._sleep(self._config.delay_between_replies_sec)

    def _generate_reply(
        self,
        comment: FetchedComment,
        match: RuleMatch,
        ctx: ReplyContext,
        plan: ReplyPlan,
    ) -> str | None:
        """返信テキストを生成する. LLM 失敗時は plan を更新して None を返す."""
        generator = self._resolve_generator(match)
        try:
            return generator.generate(ctx)
        except GeneratorError as e:
            return self._handle_generator_error(comment, match, ctx, e, plan)

    def _resolve_generator(self, match: RuleMatch) -> ReplyGenerator:
        generator = self._generators.get(match.effective_provider)
        if generator is None:
            raise ConfigError(f"rule '{match.rule.name}' の provider={match.effective_provider!r} が未初期化です")
        return generator

    def _handle_generator_error(
        self,
        comment: FetchedComment,
        match: RuleMatch,
        ctx: ReplyContext,
        error: GeneratorError,
        plan: ReplyPlan,
    ) -> str | None:
        fallback = self._config.generator.fallback_on_error
        if fallback == FALLBACK_RETRY:
            logger.warning("LLM 生成失敗、同じ provider で再試行: %s", error)
            try:
                return self._resolve_generator(match).generate(ctx)
            except GeneratorError as retry_error:
                logger.warning("LLM 生成の再試行も失敗、スキップ: %s", retry_error)
                plan.skipped.append(self._skip_record(comment, "llm_error_retry_failed"))
                return None
        logger.warning("LLM 生成失敗、スキップ: %s", error)
        plan.skipped.append(self._skip_record(comment, "llm_error_skip"))
        return None

    def _skip_reason(self, comment: FetchedComment) -> str | None:
        if not comment.can_reply:
            return "canReply=False"
        if self._config.skip_held_for_review and comment.moderation_status == _HELD_FOR_REVIEW:
            return f"moderationStatus={_HELD_FOR_REVIEW}"
        if self._history.has_replied(comment.comment_id):
            return "already_replied"
        # reply 走査時に履歴外の自分のコメントを拾わないよう authorChannelId で除外する
        if self._owner_channel_id and comment.author_channel_id == self._owner_channel_id:
            return "own_comment"
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
            **self._generator_metadata(match),
            "language": match.language,
            "replied_at": datetime.now(timezone.utc).isoformat(),
            "reply_text": reply_text,
        }
        self._history.mark_replied(comment.comment_id, metadata)
        # 途中断絶時の二重返信を防ぐため、返信成功ごとに履歴を永続化する
        self._history.save()
        plan.replied.append({"comment_id": comment.comment_id, **metadata})
        return True

    @staticmethod
    def _generator_metadata(match: RuleMatch) -> dict:
        """planned / replied 両レコードで共通する provider メタデータを返す."""
        return {"provider": match.effective_provider}

    @staticmethod
    def _skip_record(comment: FetchedComment, reason: str) -> dict:
        return {
            "comment_id": comment.comment_id,
            "video_id": comment.video_id,
            "comment_author": comment.author,
            "reason": reason,
        }

    @staticmethod
    def _video_skip_record(video_id: str, reason: str) -> dict:
        return {
            "comment_id": None,
            "video_id": video_id,
            "comment_author": None,
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


def _is_comments_disabled_error(error: YouTubeAPIError) -> bool:
    return error.status_code == 403 and error.reason == _COMMENTS_DISABLED_API_REASON
