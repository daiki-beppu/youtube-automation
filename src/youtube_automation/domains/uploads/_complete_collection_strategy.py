"""Complete Collection 動画アップロード strategy。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

from youtube_automation.core.adapters.media import probe_duration
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.collections.paths import CollectionPaths
from youtube_automation.domains.documents.video_description import read_video_description_metadata
from youtube_automation.domains.uploads._uploader_constants import (
    UPLOAD_SOURCE_EXISTING,
    UPLOAD_SOURCE_NEW,
)
from youtube_automation.domains.uploads.master_video import resolve_master_video
from youtube_automation.infrastructure.filesystem import glob_files, path_exists

logger = logging.getLogger(__name__)


class _CompleteCollectionMetadata(Protocol):
    """Metadata operation consumed by the upload strategy, independent of its implementation."""

    def generate_complete_collection_metadata(
        self,
        title_override: str | None = None,
        loops: int = 1,
        *,
        duration_seconds: int | float | None = None,
    ) -> Dict: ...


class CompleteCollectionStrategy:
    """明示された upload 操作と dedup collaborator で動画を公開する。"""

    def __init__(self, upload_video, dedup_search) -> None:
        self.upload_video = upload_video
        self.dedup_search = dedup_search

    @staticmethod
    def load_description_document(collection_dir: Path) -> dict[str, object] | None:
        """validated JSON 正本だけを読み、旧 Markdown は暗黙 parse しない。"""
        paths = CollectionPaths(collection_dir)
        source = paths.descriptions_json_path
        if not path_exists(source):
            if path_exists(paths.descriptions_md_path):
                raise ValidationError(
                    f"{paths.descriptions_md_path}: 旧 descriptions.md は upload 入力にできません。"
                    "明示 migration で descriptions.json + descriptions.html pair へ移行してください"
                )
            stray = glob_files(paths.docs_dir, "description*")
            if stray:
                raise ValidationError(
                    f"descriptions.json が無いのに別名ファイルが存在します: {[path.name for path in stray]}\n"
                    "→ /video --describe で検証済み JSON+HTML pair を生成してください"
                )
            return None
        return read_video_description_metadata(source)

    def upload(
        self,
        collection_dir: Path,
        metadata_gen: _CompleteCollectionMetadata,
        publish_at: Optional[str] = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Optional[Dict]:
        """Complete Collection 動画アップロード"""
        logger.info("📹 Complete Collection アップロード準備中...")

        paths = CollectionPaths(collection_dir)

        master_video = resolve_master_video(collection_dir)
        duration_seconds = probe_duration(master_video)
        if duration_seconds is None:
            raise ValidationError(
                f"実マスター尺を取得できません: {master_video.name}。"
                "ffprobe で読み取れる完成済みマスター動画を指定してください"
            )

        # descriptions.json が最終タイトル/概要/タグを供給するなら先に読み込み、
        # 中間タイトル生成（_generate_title）を title_override でスキップする。
        # これにより title.template が未知プレースホルダ（例 {adjective}）を含んでも
        # 本来捨てられる中間タイトル生成で upload 全体がクラッシュしない（#574）。
        prebuilt = self.load_description_document(collection_dir)

        # メタデータ生成（BAHMetadataGenerator — localizations 等）
        metadata = metadata_gen.generate_complete_collection_metadata(
            loops=1,
            title_override=prebuilt["title"] if prebuilt else None,
            duration_seconds=duration_seconds,
        )

        # validated descriptions.json が存在すれば公開 metadata を上書き
        if prebuilt:
            metadata["title"] = prebuilt["title"]
            metadata["description"] = prebuilt["description"]
            if prebuilt["tags"]:
                metadata["tags"] = prebuilt["tags"]

            # 空 object は「文書側に最終翻訳なし」を表すため、scene_phrases から
            # metadata generator が組み立てた翻訳を消さない。非空なら承認済み文書を優先する。
            if prebuilt["localizations"]:
                metadata["localizations"] = prebuilt["localizations"]

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
        existing = self.dedup_search.find_existing_video_by_title(metadata["title"])
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


__all__ = ["CompleteCollectionStrategy", "resolve_master_video"]
