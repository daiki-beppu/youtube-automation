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
    GeminiGenerator,
    ReplyContext,
    ReplyGenerator,
    TemplateGenerator,
)
from youtube_automation.utils.comments.history import ReplyHistory
from youtube_automation.utils.comments.rule_engine import RuleEngine, RuleMatch
from youtube_automation.utils.config.comments import (
    CHANNEL_PERSONA_DEFAULT,
    FALLBACK_TEMPLATE,
    GENERATOR_TYPE_GEMINI,
    GENERATOR_TYPE_TEMPLATE,
    MAX_LENGTH_DEFAULT,
    Comments,
)
from youtube_automation.utils.exceptions import ConfigError, GeneratorError, YouTubeAPIError

logger = logging.getLogger(__name__)

_HELD_FOR_REVIEW = "heldForReview"


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
        self._gemini_generator: GeminiGenerator | None = self._create_gemini_generator()

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

    def _create_gemini_generator(self) -> GeminiGenerator | None:
        uses_gemini_rule = any(r.generator == GENERATOR_TYPE_GEMINI for r in self._config.rules)
        global_is_gemini = self._config.generator is not None and self._config.generator.type == GENERATOR_TYPE_GEMINI

        if not (uses_gemini_rule or global_is_gemini):
            return None

        cfg = self._config.generator
        return GeminiGenerator(
            model=cfg.model,
            max_length=cfg.max_length,
            requests_per_minute=cfg.requests_per_minute,
            sleep_fn=self._sleep,
        )

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

        default_generator_type = self._config.generator.type if self._config.generator else GENERATOR_TYPE_TEMPLATE
        engine = RuleEngine(
            rules=self._config.rules,
            templates=self._config.templates,
            default_language=self._default_language,
            ng_words=self._config.ng_words,
            default_generator_type=default_generator_type,
        )
        plan = ReplyPlan()
        limit = self._config.max_replies_per_run

        if video_ids is not None:
            # 明示指定時: uploads playlist 解決は不要だが owner_channel_id は別途解決する
            self._resolve_owner_channel_id()
            video_source: Iterator[str] = iter(video_ids)
        else:
            owner_id, uploads_playlist_id = self._fetch_channel_info()
            self._owner_channel_id = self._owner_channel_id or owner_id
            video_source = self._iter_uploaded_video_ids(uploads_playlist_id)

        for vid in video_source:
            if len(plan.planned) >= limit:
                break
            for comment in fetch_comments(self._youtube, video_id=vid, max_results=per_video_limit, since=since):
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
        effective_generator_type = match.effective_generator_type

        gen = self._config.generator
        ctx = ReplyContext(
            video_id=comment.video_id,
            video_title=video_title,
            comment_id=comment.comment_id,
            comment_text=comment.text,
            comment_author=comment.author,
            language=match.template_language,
            channel_persona=gen.channel_persona if gen else CHANNEL_PERSONA_DEFAULT,
            max_length=gen.max_length if gen else MAX_LENGTH_DEFAULT,
            parent_thread=None,
            dry_run=dry_run,
        )

        reply_text = self._generate_reply(comment, match, ctx, effective_generator_type, plan)
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
                **self._generator_metadata(match, effective_generator_type),
                "language": match.template_language,
                "reply_text": reply_text,
            }
        )

        if dry_run:
            return

        if self._post_reply(comment, reply_text, match, video_title, effective_generator_type, plan):
            self._sleep(self._config.delay_between_replies_sec)

    def _generate_reply(
        self,
        comment: FetchedComment,
        match: RuleMatch,
        ctx: ReplyContext,
        effective_generator_type: str,
        plan: ReplyPlan,
    ) -> str | None:
        """返信テキストを生成する. Gemini 失敗時は plan を更新して None を返す.

        GeneratorError は GeminiGenerator のみが送出する（外部 SDK 境界で昇格）。
        TemplateGenerator が送出する ValidationError はコンフィグ不備のため上位へ伝播させる。
        """
        generator = self._resolve_generator(match, effective_generator_type)
        try:
            return generator.generate(ctx)
        except GeneratorError as e:
            return self._handle_gemini_error(comment, match, ctx, e, plan)

    def _resolve_generator(self, match: RuleMatch, effective_generator_type: str) -> ReplyGenerator:
        if effective_generator_type == GENERATOR_TYPE_GEMINI:
            if self._gemini_generator is None:
                raise ConfigError(
                    f"rule '{match.rule.name}' の effective generator='gemini' だが "
                    "GeminiGenerator が初期化されていません"
                )
            return self._gemini_generator
        if match.template_text is None:
            raise ConfigError(
                f"rule '{match.rule.name}' の effective generator='template' だが テンプレートが解決されていません"
            )
        return TemplateGenerator(match.template_text)

    def _handle_gemini_error(
        self,
        comment: FetchedComment,
        match: RuleMatch,
        ctx: ReplyContext,
        error: GeneratorError,
        plan: ReplyPlan,
    ) -> str | None:
        """Gemini 生成エラー時に fallback_on_error 設定に従って処理する.

        _create_gemini_generator() で gemini 使用時は必ず generator セクションが
        存在することを保証しているため、self._config.generator は非 None。
        template fallback の ValidationError（コンフィグ不備）は上位へ伝播させる（fail-fast）。
        """
        assert self._config.generator is not None  # __post_init__ + _create_gemini_generator で保証
        fallback = self._config.generator.fallback_on_error
        if fallback == FALLBACK_TEMPLATE:
            if match.template_text is not None:
                logger.warning("Gemini 生成失敗、テンプレートにフォールバック: %s", error)
                template_gen = TemplateGenerator(match.template_text)
                return template_gen.generate(ctx)
            logger.warning("Gemini 生成失敗かつテンプレートなし、スキップ: %s", error)
            plan.skipped.append(self._skip_record(comment, "llm_error_no_fallback"))
            return None
        # FALLBACK_SKIP
        logger.warning("Gemini 生成失敗、スキップ: %s", error)
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
        effective_generator_type: str,
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
            **self._generator_metadata(match, effective_generator_type),
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
    def _generator_metadata(match: RuleMatch, effective_generator_type: str) -> dict:
        """planned / replied 両レコードで共通する generator メタデータを返す."""
        return {
            "template_key": match.rule.template_key if effective_generator_type == GENERATOR_TYPE_TEMPLATE else None,
            "generator": effective_generator_type if effective_generator_type != GENERATOR_TYPE_TEMPLATE else None,
        }

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
