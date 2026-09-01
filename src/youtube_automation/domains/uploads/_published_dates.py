"""公開日一覧取得とスケジュール公開日時の計算コラボレータ。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import ClassVar

from youtube_automation.configuration import ScheduleConfig, load_config
from youtube_automation.core.adapters.runtime import get_schedule_timezone, resolve_default_publish_at
from youtube_automation.core.errors import ValidationError, YouTubeAPIError
from youtube_automation.infrastructure.google.youtube import execute_youtube_request, validate_youtube_response_items
from youtube_automation.infrastructure.quota import youtube_quota_recorder

logger = logging.getLogger(__name__)

_QUOTA_SERVICE = "youtube-data-api"
# YouTube Data API v3 の公式 quota cost（2026-06-01以降は search.list 独立 bucket で 1/call）
_SEARCH_LIST_UNITS = 1
_VIDEOS_LIST_UNITS = 1
_QUOTA_CONTEXT = "published_dates_lookup"


def _video_ids(response: object) -> list[str]:
    ids: list[str] = []
    for item in validate_youtube_response_items(response, "published dates search.list"):
        if not isinstance(item, dict):
            raise ValidationError("published dates search.list response contains an invalid item")
        video_id = item.get("id", {}).get("videoId") if isinstance(item.get("id"), dict) else None
        if not isinstance(video_id, str) or not video_id:
            raise ValidationError("published dates search.list response is missing id.videoId")
        ids.append(video_id)
    return ids


def _published_datetime(video: object) -> datetime:
    if not isinstance(video, dict):
        raise ValidationError("published dates videos.list response contains an invalid item")

    status = video.get("status")
    if not isinstance(status, dict):
        raise ValidationError("published dates videos.list response is missing status")
    publish_at = status.get("publishAt")
    if not publish_at:
        snippet = video.get("snippet")
        publish_at = snippet.get("publishedAt") if isinstance(snippet, dict) else None
    if not isinstance(publish_at, str) or not publish_at:
        raise ValidationError("published dates videos.list response is missing publishedAt")
    try:
        return datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"published dates response has invalid publishedAt: {publish_at}") from exc


class PublishedDatesScheduler:
    """設定と YouTube service provider から公開日時を計算する。"""

    # 曜日名 → isoweekday() マッピング（月=1, 日=7）
    _WEEKDAY_MAP: ClassVar[dict[str, int]] = {
        "mon": 1,
        "tue": 2,
        "wed": 3,
        "thu": 4,
        "fri": 5,
        "sat": 6,
        "sun": 7,
    }

    def __init__(
        self,
        config: ScheduleConfig,
        youtube_service_provider: Callable[[], object],
        now_provider: Callable[[tzinfo | None], datetime] | None = None,
    ) -> None:
        self.config = config
        self.youtube_service_provider = youtube_service_provider
        self.now_provider = now_provider if now_provider is not None else lambda timezone: datetime.now(timezone)

    def parse_persisted_datetime(self, raw: str, *, source: Path, field: str) -> datetime | None:
        """永続化日時を読み、legacy の TZ-naive 値を schedule timezone で補正する。"""
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed

        timezone = get_schedule_timezone(self.config)
        logger.warning(
            "%s に TZ-naive な %s=%r が含まれます; schedule timezone %s で backfill します"
            "（レガシーデータ救済 / #532）",
            source,
            field,
            raw,
            timezone,
        )
        return parsed.replace(tzinfo=timezone)

    def calculate_short_publish_at(
        self,
        tracking: dict,
        *,
        tracking_path: Path,
        publish_time: str,
    ) -> str | None:
        """Complete Collection 公開日時の翌日に Short の公開日時を置く。"""
        complete_collection = tracking.get("complete_collection") or {}
        base = complete_collection.get("publish_at")
        base_field = "complete_collection.publish_at"
        if not base:
            base = complete_collection.get("upload_time")
            base_field = "complete_collection.upload_time"
        if not base:
            return None

        try:
            hour, minute = (int(value) for value in publish_time.split(":"))
        except ValueError:
            logger.warning(f"short_publish_time のパース失敗: {publish_time}（HH:MM 形式が必要）")
            return None

        base_datetime = self.parse_persisted_datetime(base, source=tracking_path, field=base_field)
        if base_datetime is None:
            return None

        timezone = get_schedule_timezone(self.config)
        publish_datetime = base_datetime.astimezone(timezone) + timedelta(days=1)
        publish_datetime = publish_datetime.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if publish_datetime <= self.now_provider(timezone):
            return None
        return publish_datetime.isoformat()

    def calculate_publish_at(self) -> str | None:
        """CC のスケジュール公開日時を計算

        スケジュール公開（YouTube ``status.publishAt``）を有効化する条件:

        - ``schedule.auto_schedule_enabled`` が ``true`` に明示設定されている
        - もしくは ``schedule.cadence`` / ``schedule.publish_time`` のいずれかが
          明示設定されている（暗黙オプトイン: #647）。
          ``auto_schedule_enabled`` が明示的に ``false`` の場合のみ無効化される。

        スケジュール公開が有効な場合:

        - cadence で指定された曜日（例: tue, thu, sat）に限定
        - 当日の publish_time を過ぎていたら次の cadence 曜日から探索
        - 同日に既存の公開/予約動画があればさらに次の cadence 曜日にスライド

        スケジュール公開が無効な場合は None（即時公開）。

        Returns:
            ISO 8601 形式の公開日時文字列。予約日時を設定しない場合は None。
        """
        if not self.config.scheduling_enabled:
            if self.config.scheduling_explicitly_disabled:
                logger.info("📅 自動予約: 無効（schedule.auto_schedule_enabled=false）")
                return None
            default_publish_at = resolve_default_publish_at(load_config())
            if default_publish_at:
                logger.info(f"📅 channel youtube.default_publish_time から公開予定を適用: {default_publish_at}")
                return default_publish_at
            logger.info("📅 自動予約: 無効（schedule_config.json で auto_schedule_enabled 未設定）")
            return None

        publish_time = self.config.publish_time
        tz = get_schedule_timezone(self.config)
        hour, minute = map(int, publish_time.split(":"))

        # cadence 曜日を isoweekday に変換（未設定なら全曜日許可）
        cadence = self.config.cadence
        allowed_weekdays = {self._WEEKDAY_MAP[d.lower()] for d in cadence} if cadence else set(range(1, 8))

        now = self.now_provider(tz)
        publish_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # 既に今日の公開時刻を過ぎていたら翌日から開始
        if publish_dt <= now:
            publish_dt += timedelta(days=1)

        # cadence 曜日かつ既存公開日と重複しない日を探す
        existing_dates = self.get_published_dates()
        max_slide = 30  # 無限ループ防止
        for _ in range(max_slide):
            if publish_dt.isoweekday() in allowed_weekdays and publish_dt.date() not in existing_dates:
                break
            publish_dt += timedelta(days=1)
            if publish_dt.isoweekday() not in allowed_weekdays:
                continue
            logger.info(f"📅 公開日スライド → {publish_dt.date()} ({publish_dt.strftime('%a')})")

        logger.info(f"📅 CC 公開予定: {publish_dt.isoformat()}")
        return publish_dt.isoformat()

    def get_published_dates(self) -> set:
        """YouTube API でチャンネルの公開済み/予約済み動画の公開日セットを取得

        search().list() で動画IDを取得し、videos().list(part='status,snippet') で
        公開予約日時（status.publishAt）と公開日時（snippet.publishedAt）の両方を収集する。
        """
        youtube_service = self.youtube_service_provider()

        tz = get_schedule_timezone(self.config)
        dates = set()

        try:
            # 動画IDを取得（part='id' でクォータ節約）
            search_request = youtube_service.search().list(
                forMine=True, type="video", order="date", maxResults=50, part="id"
            )
            # 失敗 request も quota を消費するため、成否によらず記録してから既存の fail-safe に委ねる
            response = execute_youtube_request(
                search_request,
                "published dates search.list failed",
                on_attempt=youtube_quota_recorder(
                    "search.list", _SEARCH_LIST_UNITS, metadata={"context": _QUOTA_CONTEXT}
                ),
            )

            video_ids = _video_ids(response)
            if not video_ids:
                return dates

            # status.publishAt（公開予約）と snippet.publishedAt（公開済み）を取得
            videos_request = youtube_service.videos().list(id=",".join(video_ids), part="status,snippet")
            videos_response = execute_youtube_request(
                videos_request,
                "published dates videos.list failed",
                on_attempt=youtube_quota_recorder(
                    "videos.list", _VIDEOS_LIST_UNITS, metadata={"context": _QUOTA_CONTEXT}
                ),
            )

            for video in validate_youtube_response_items(videos_response, "published dates videos.list"):
                dt = _published_datetime(video)
                dates.add(dt.astimezone(tz).date())

        except (RuntimeError, ValidationError, YouTubeAPIError) as e:
            logger.warning(f"⚠️  公開日一覧取得エラー: {e}")

        return dates


__all__ = ["PublishedDatesScheduler"]
