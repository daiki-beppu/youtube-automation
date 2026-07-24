"""公開日一覧取得とスケジュール公開日時の計算ロジック。

責務分割（Issue #465）の一環で ``collection_uploader.py`` から分離した。
``self.config`` / ``self.youtube_service`` / ``self.initialize_youtube_service``
は合成先クラス（``CollectionUploader`` 本体）が提供する。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import ClassVar

from youtube_automation.configuration import load_config
from youtube_automation.infrastructure.errors import ValidationError, YouTubeAPIError
from youtube_automation.infrastructure.google.youtube import execute_youtube_request, validate_youtube_response_items
from youtube_automation.infrastructure.quota import youtube_quota_recorder
from youtube_automation.utils.publish_schedule import resolve_default_publish_at
from youtube_automation.utils.schedule import get_schedule_timezone

logger = logging.getLogger(__name__)

# YouTube Data API v3 の公式 quota cost（search.list=100 / videos.list=1）
_SEARCH_LIST_UNITS = 100
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


def _scheduling_enabled(schedule_cfg: dict) -> bool:
    """``schedule_config.json`` の ``schedule`` セクションからスケジュール公開有効性を判定する。

    優先順位（#647 ユーザーが「予約投稿の設定をしたつもりが即時公開された」FB 対応）:

    1. ``auto_schedule_enabled`` が明示的に ``true`` → 有効。
    2. ``auto_schedule_enabled`` が明示的に ``false`` → 無効（即時公開を強制）。
    3. キー未設定で ``cadence`` (非空) または ``publish_time`` が明示設定 → 暗黙オプトイン: 有効。
    4. 上記いずれにも該当しなければ無効（即時公開）。

    ``day1_time`` は旧テンプレ互換のため ``publish_time`` が無いときのフォールバックとして使うが、
    「明示的なスケジュール設定」のシグナルとしては扱わない（過去テンプレで既定値が
    入っていることがあるため）。
    """
    if "auto_schedule_enabled" in schedule_cfg:
        return bool(schedule_cfg["auto_schedule_enabled"])

    has_cadence = bool(schedule_cfg.get("cadence"))
    has_publish_time = "publish_time" in schedule_cfg and bool(schedule_cfg.get("publish_time"))
    return has_cadence or has_publish_time


class PublishedDatesMixin:
    """公開済み/予約済み動画の取得とスケジュール公開日時計算を提供する mixin。"""

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

    def _calculate_publish_at(self) -> str | None:
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
            ISO 8601 形式の公開日時文字列。即時公開時は None。
        """
        schedule_cfg = self.config.get("schedule", {})
        if not _scheduling_enabled(schedule_cfg):
            if schedule_cfg.get("auto_schedule_enabled") is False:
                logger.info("📅 公開設定: 即時公開（schedule.auto_schedule_enabled=false）")
                return None
            default_publish_at = resolve_default_publish_at(load_config())
            if default_publish_at:
                logger.info(f"📅 channel youtube.default_publish_time から公開予定を適用: {default_publish_at}")
                return default_publish_at
            logger.info("📅 公開設定: 即時公開（schedule_config.json で auto_schedule_enabled 未設定）")
            return None

        publish_time = schedule_cfg.get("publish_time", schedule_cfg.get("day1_time", "17:00"))
        tz = get_schedule_timezone(self.config)
        hour, minute = map(int, publish_time.split(":"))

        # cadence 曜日を isoweekday に変換（未設定なら全曜日許可）
        cadence = schedule_cfg.get("cadence", [])
        allowed_weekdays = {self._WEEKDAY_MAP[d.lower()] for d in cadence} if cadence else set(range(1, 8))

        now = datetime.now(tz)
        publish_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # 既に今日の公開時刻を過ぎていたら翌日から開始
        if publish_dt <= now:
            publish_dt += timedelta(days=1)

        # cadence 曜日かつ既存公開日と重複しない日を探す
        existing_dates = self._get_published_dates()
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

    def _get_published_dates(self) -> set:
        """YouTube API でチャンネルの公開済み/予約済み動画の公開日セットを取得

        search().list() で動画IDを取得し、videos().list(part='status,snippet') で
        公開予約日時（status.publishAt）と公開日時（snippet.publishedAt）の両方を収集する。
        """
        if not self.youtube_service:
            self.initialize_youtube_service()

        tz = get_schedule_timezone(self.config)
        dates = set()

        try:
            # 動画IDを取得（part='id' でクォータ節約）
            search_request = self.youtube_service.search().list(
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
            videos_request = self.youtube_service.videos().list(id=",".join(video_ids), part="status,snippet")
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


__all__ = ["PublishedDatesMixin"]
