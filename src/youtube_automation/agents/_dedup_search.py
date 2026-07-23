"""publish 直前の dedup 安全網（同タイトル動画の既存検出）。

``YouTubeAutoUploader`` から分離した mixin。挙動は分割前と同一で、
``self.youtube`` / ``self._ensure_service`` は合成先（``YouTubeUploadCore`` 継承クラス）
が提供する。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from googleapiclient.errors import HttpError

from youtube_automation.agents._uploader_constants import (
    _REUSABLE_UPLOAD_STATUSES,
    YOUTUBE_VIDEO_URL_PREFIX,
)
from youtube_automation.utils import cost_tracker

logger = logging.getLogger(__name__)

_QUOTA_SERVICE = "youtube-data-api"
# YouTube Data API v3 の公式 quota cost（2026-06-01以降は search.list 独立 bucket で 1/call）
_SEARCH_LIST_UNITS = 1
_VIDEOS_LIST_UNITS = 1
_QUOTA_CONTEXT = "upload_dedup_search"


class DedupSearchMixin:
    """own channel 内の同タイトル動画検出ロジックを提供する mixin。"""

    def _find_existing_video_by_title(self, title: str) -> Optional[Dict[str, str]]:
        """own channel 内に同タイトル（完全一致）の動画があれば video_id / video_url を返す。

        publish 直前の dedup 安全網。session URI 持ち越し（一次対策）が破れた場合の
        二次防衛線として、`videos().insert()` を呼ぶ前に既存動画の有無を確認する。
        search index は eventual-consistent なため、候補 ID は videos.list で再検証する。

        Args:
            title: 完全一致で検索するタイトル文字列

        Returns:
            hit: `{"video_id": ..., "video_url": ...}` / miss: None / 検索エラー: None（fail-open）
        """
        self._ensure_service()
        try:
            search_request = self.youtube.search().list(
                forMine=True, type="video", q=title, maxResults=10, part="snippet"
            )
            # 失敗 request も quota を消費するため、成否によらず記録してから既存の fail-open に委ねる
            try:
                resp = search_request.execute()
            finally:
                cost_tracker.log_quota(
                    _QUOTA_SERVICE,
                    "search.list",
                    _SEARCH_LIST_UNITS,
                    metadata={"context": _QUOTA_CONTEXT},
                )
            candidate_ids = self._exact_title_video_ids(resp.get("items", []), title)
            if not candidate_ids:
                return None

            videos_request = self.youtube.videos().list(id=",".join(candidate_ids), part="status,snippet")
            try:
                videos_response = videos_request.execute()
            finally:
                cost_tracker.log_quota(
                    _QUOTA_SERVICE,
                    "videos.list",
                    _VIDEOS_LIST_UNITS,
                    metadata={"context": _QUOTA_CONTEXT},
                )
            return self._first_reusable_video(videos_response.get("items", []), title)
        except HttpError as e:
            # fail-open: 安全網のエラーは upload を block しない(一次対策は session URI 持ち越し)
            logger.warning(f"⚠️  既存動画検索失敗（upload 続行）: {e}")
            return None

    @staticmethod
    def _exact_title_video_ids(items: list[dict], title: str) -> list[str]:
        video_ids = []
        for item in items:
            if item["snippet"]["title"] == title:
                video_ids.append(item["id"]["videoId"])
        return video_ids

    @staticmethod
    def _first_reusable_video(videos: list[dict], title: str) -> Optional[Dict[str, str]]:
        for video in videos:
            if not DedupSearchMixin._is_reusable_exact_title_video(video, title):
                continue
            video_id = video["id"]
            return {
                "video_id": video_id,
                "video_url": f"{YOUTUBE_VIDEO_URL_PREFIX}{video_id}",
            }
        return None

    @staticmethod
    def _is_reusable_exact_title_video(video: dict, title: str) -> bool:
        upload_status = video.get("status", {}).get("uploadStatus")
        return video["snippet"]["title"] == title and upload_status in _REUSABLE_UPLOAD_STATUSES
