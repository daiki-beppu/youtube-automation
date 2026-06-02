"""公開日一覧取得とスケジュール公開日時の計算ロジック。

責務分割（Issue #465）の一環で ``collection_uploader.py`` から分離した。
``self.config`` / ``self.youtube_service`` / ``self.initialize_youtube_service``
は合成先クラス（``CollectionUploader`` 本体）が提供する。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from youtube_automation.utils.schedule import get_schedule_timezone

logger = logging.getLogger(__name__)


class PublishedDatesMixin:
    """公開済み/予約済み動画の取得とスケジュール公開日時計算を提供する mixin。"""

    # 曜日名 → isoweekday() マッピング（月=1, 日=7）
    _WEEKDAY_MAP = {
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

        auto_schedule_enabled が true の場合:
        - cadence で指定された曜日（例: tue, thu, sat）に限定
        - 当日の publish_time を過ぎていたら次の cadence 曜日から探索
        - 同日に既存の公開/予約動画があればさらに次の cadence 曜日にスライド

        auto_schedule_enabled が false の場合は None（即時公開）。

        Returns:
            ISO 8601 形式の公開日時文字列。即時公開時は None。
        """
        schedule_cfg = self.config.get("schedule", {})
        if not schedule_cfg.get("auto_schedule_enabled", False):
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
            response = (
                self.youtube_service.search()
                .list(forMine=True, type="video", order="date", maxResults=50, part="id")
                .execute()
            )

            video_ids = [item["id"]["videoId"] for item in response.get("items", [])]
            if not video_ids:
                return dates

            # status.publishAt（公開予約）と snippet.publishedAt（公開済み）を取得
            videos_response = (
                self.youtube_service.videos().list(id=",".join(video_ids), part="status,snippet").execute()
            )

            for video in videos_response.get("items", []):
                # 公開予約日時を優先、なければ公開日時を使用
                publish_at = video.get("status", {}).get("publishAt")
                if publish_at:
                    dt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(video["snippet"]["publishedAt"].replace("Z", "+00:00"))
                dates.add(dt.astimezone(tz).date())

        except Exception as e:
            logger.warning(f"⚠️  公開日一覧取得エラー: {e}")

        return dates


__all__ = ["PublishedDatesMixin"]
