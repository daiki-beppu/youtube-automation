"""Complete Collection 動画アップロード経路。

``YouTubeAutoUploader`` から分離した mixin。挙動は分割前と同一で、
``self.upload_video`` / ``self._load_descriptions_md`` /
``self._extract_body_for_localizations`` / ``self._find_existing_video_by_title``
は合成先クラス（本体 + 他 mixin）が提供する。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, Optional

from youtube_automation.agents._uploader_constants import (
    UPLOAD_SOURCE_EXISTING,
    UPLOAD_SOURCE_NEW,
)
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.metadata_generator import BAHMetadataGenerator

logger = logging.getLogger(__name__)


class CompleteCollectionMixin:
    """Complete Collection 動画のアップロード経路を提供する mixin。"""

    def _upload_complete_collection(
        self,
        collection_dir: Path,
        metadata_gen: BAHMetadataGenerator,
        publish_at: str = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Optional[Dict]:
        """Complete Collection 動画アップロード"""
        logger.info("📹 Complete Collection アップロード準備中...")

        paths = CollectionPaths(collection_dir)

        # マスター動画ファイル検索
        video_files = list(paths.movie_dir.glob("*master*.mp4"))
        if not video_files:
            video_files = list(paths.master_dir.glob("*.mp4"))

        if not video_files:
            error_msg = "マスター動画ファイルが見つかりません"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}

        master_video = video_files[0]

        # descriptions.md が最終タイトル/概要/タグを供給するなら先に読み込み、
        # 中間タイトル生成（_generate_title）を title_override でスキップする。
        # これにより title.template が未知プレースホルダ（例 {adjective}）を含んでも
        # 本来捨てられる中間タイトル生成で upload 全体がクラッシュしない（#574）。
        prebuilt = self._load_descriptions_md(collection_dir)

        # メタデータ生成（BAHMetadataGenerator — localizations 等）
        metadata = metadata_gen.generate_complete_collection_metadata(
            title_override=prebuilt["title"] if prebuilt else None
        )

        # descriptions.md が存在すれば title/description/tags を上書き
        if prebuilt:
            metadata["title"] = prebuilt["title"]
            metadata["description"] = prebuilt["description"]
            if prebuilt["tags"]:
                metadata["tags"] = prebuilt["tags"]

            # ローカライゼーションにもキュレーション済みのタイムスタンプを使用
            curated_timestamps = self._extract_body_for_localizations(prebuilt["description"])
            scene_phrases = getattr(metadata_gen, "_last_scene_phrases", {})
            scene_emoji = metadata_gen._load_scene_emoji()
            if curated_timestamps:
                metadata["localizations"] = metadata_gen.generate_localizations(
                    metadata["title"], curated_timestamps, scene_phrases, scene_emoji=scene_emoji
                )

        if publish_at:
            metadata["publish_at"] = publish_at

        # アップロード用サムネイル検索。main.png/jpg は textless 動画背景なので使わない。
        thumbnail = paths.find_thumbnail()
        if thumbnail is None:
            raise ValidationError(
                "アップロード用サムネイルが見つかりません: "
                "10-assets/thumbnail.jpg または thumbnail.png を作成してください。"
                "main.png/main.jpg は textless 動画背景なので YouTube サムネイルには使いません。"
            )
        thumbnail_path = str(thumbnail)

        # publish 直前の dedup 安全網: 同タイトル動画が own channel に既に存在すれば
        # `videos().insert()` を呼ばず既存 video_id を採用する
        existing = self._find_existing_video_by_title(metadata["title"])
        if existing:
            logger.info(f"⚠️  既存動画を検出（upload skip）: {existing['video_url']}")
            return {
                "video_id": existing["video_id"],
                "video_url": existing["video_url"],
                "upload_source": UPLOAD_SOURCE_EXISTING,
                "title": metadata["title"],
                "file_path": str(master_video),
                "thumbnail_path": thumbnail_path,
            }

        # アップロード実行
        video_id = self.upload_video(
            str(master_video),
            metadata,
            thumbnail_path,
            resume_session_uri=resume_session_uri,
            on_session_uri_changed=on_session_uri_changed,
            on_upload_complete=on_upload_complete,
        )

        if video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            return {
                "video_id": video_id,
                "video_url": video_url,
                "upload_source": UPLOAD_SOURCE_NEW,
                "title": metadata["title"],
                "file_path": str(master_video),
                "thumbnail_path": thumbnail_path,
            }
        else:
            return {"error": "Complete Collection アップロード失敗"}
