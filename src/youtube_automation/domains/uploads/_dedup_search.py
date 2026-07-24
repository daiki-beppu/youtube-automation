"""publish 直前の dedup 安全網（同タイトル動画の既存検出）。

``YouTubeAutoUploader`` から分離した mixin。挙動は分割前と同一で、
``self.youtube`` / ``self._ensure_service`` は合成先（``YouTubeUploadCore`` 継承クラス）
が提供する。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from youtube_automation.domains.uploads._uploader_constants import (
    _REUSABLE_UPLOAD_STATUSES,
    YOUTUBE_VIDEO_URL_PREFIX,
)
from youtube_automation.infrastructure.errors import ValidationError, YouTubeAPIError
from youtube_automation.infrastructure.google.youtube import execute_youtube_request, validate_youtube_response_items
from youtube_automation.infrastructure.quota import youtube_quota_recorder

logger = logging.getLogger(__name__)

# YouTube Data API v3 の公式 quota cost（search.list=100 / videos.list=1）
_SEARCH_LIST_UNITS = 100
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
            resp = execute_youtube_request(
                search_request,
                "upload dedup search.list failed",
                on_attempt=youtube_quota_recorder(
                    "search.list", _SEARCH_LIST_UNITS, metadata={"context": _QUOTA_CONTEXT}
                ),
            )
            candidate_ids = self._exact_title_video_ids(validate_youtube_response_items(resp, "search.list"), title)
            if not candidate_ids:
                return None

            videos_request = self.youtube.videos().list(id=",".join(candidate_ids), part="status,snippet")
            videos_response = execute_youtube_request(
                videos_request,
                "upload dedup videos.list failed",
                on_attempt=youtube_quota_recorder(
                    "videos.list", _VIDEOS_LIST_UNITS, metadata={"context": _QUOTA_CONTEXT}
                ),
            )
            return self._first_reusable_video(validate_youtube_response_items(videos_response, "videos.list"), title)
        except (ValidationError, YouTubeAPIError) as e:
            # fail-open: 安全網のエラーは upload を block しない(一次対策は session URI 持ち越し)
            logger.warning(f"⚠️  既存動画検索失敗（upload 続行）: {e}")
            return None

    @staticmethod
    def _exact_title_video_ids(items: list[dict], title: str) -> list[str]:
        video_ids = []
        for item in items:
            if not isinstance(item, dict):
                raise ValidationError("search.list response item must be an object")
            snippet = item.get("snippet")
            identity = item.get("id")
            if not isinstance(snippet, dict) or not isinstance(snippet.get("title"), str):
                raise ValidationError("search.list response item is missing snippet.title")
            if not isinstance(identity, dict) or not isinstance(identity.get("videoId"), str):
                raise ValidationError("search.list response item is missing id.videoId")
            if snippet["title"] == title:
                video_ids.append(identity["videoId"])
        return video_ids

    @staticmethod
    def _first_reusable_video(videos: list[dict], title: str) -> Optional[Dict[str, str]]:
        for video in videos:
            if not DedupSearchMixin._is_reusable_exact_title_video(video, title):
                continue
            video_id = video.get("id")
            if not isinstance(video_id, str):
                raise ValidationError("videos.list response item is missing id")
            return {
                "video_id": video_id,
                "video_url": f"{YOUTUBE_VIDEO_URL_PREFIX}{video_id}",
            }
        return None

    @staticmethod
    def _is_reusable_exact_title_video(video: dict, title: str) -> bool:
        if not isinstance(video, dict):
            raise ValidationError("videos.list response item must be an object")
        snippet = video.get("snippet")
        status = video.get("status")
        if not isinstance(snippet, dict) or not isinstance(snippet.get("title"), str):
            raise ValidationError("videos.list response item is missing snippet.title")
        if not isinstance(status, dict) or not isinstance(status.get("uploadStatus"), str):
            raise ValidationError("videos.list response item is missing status.uploadStatus")
        return snippet["title"] == title and status["uploadStatus"] in _REUSABLE_UPLOAD_STATUSES
