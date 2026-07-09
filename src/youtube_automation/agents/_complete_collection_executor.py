"""Complete Collection アップロード実行ループ。

責務分割（Issue #465）の一環で ``collection_uploader.py`` から分離した。
``self.uploader`` / ``self._load_tracking`` / ``self._save_tracking`` /
``self._completed_tracking_record`` / ``self.config`` /
``self._move_collection_to_live`` / ``self._update_workflow_upload`` /
``self._assign_to_playlists`` は合成先クラス（``CollectionUploader`` 本体および
他 mixin）が提供する。
"""

from __future__ import annotations

import logging
from pathlib import Path

from youtube_automation.agents._collection_uploader_constants import (
    ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED,
    ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
    ACTION_COMPLETE_COLLECTION_UPLOADED,
    TRACKING_STATUS_COMPLETED,
)
from youtube_automation.agents.youtube_auto_uploader import UPLOAD_SOURCE_EXISTING
from youtube_automation.utils.exceptions import QuotaExhaustedError

logger = logging.getLogger(__name__)


class CompleteCollectionExecutorMixin:
    """Complete Collection アップロード実行ループを提供する mixin。"""

    def _execute_complete_collection(
        self, collection_path: Path, tracking: dict, publish_at: str | None = None
    ) -> dict:
        """Complete Collection アップロード"""
        logger.info("📅 Complete Collection アップロード開始")
        logger.info(f"🎵 コレクション: {collection_path.name}")
        if publish_at:
            logger.info(f"📅 スケジュール公開: {publish_at}")

        # tracking から resumable upload session URI を取り出す（無ければ None でフレッシュ実行）
        cc = tracking.get("complete_collection", {})
        resume_session_uri = cc.get("resume_session_uri")

        def _on_session_uri_changed(uri: str | None) -> None:
            """upload 中の URI 変化を tracking に永続化する。

            並行更新（プレイリスト追加等が tracking を書く可能性）に備え、
            毎回 disk から再ロードしてから書き戻す。
            """
            current = self._load_tracking(collection_path) or {}
            cc_current = current.setdefault("complete_collection", {})
            if uri is None:
                cc_current.pop("resume_session_uri", None)
            else:
                cc_current["resume_session_uri"] = uri
            self._save_tracking(collection_path, current)

        def _on_upload_complete() -> None:
            """upload 成功通知。後続の status="completed" 書き込みと整合させるため URI を消す。"""
            _on_session_uri_changed(None)

        try:
            result = self.uploader.upload_collection(
                str(collection_path),
                publish_at=publish_at,
                apply_default_publish_at=False,
                resume_session_uri=resume_session_uri,
                on_session_uri_changed=_on_session_uri_changed,
                on_upload_complete=_on_upload_complete,
            )
            complete_video = result.get("complete_video")

            if complete_video and "video_id" in complete_video:
                tracking = {
                    **tracking,
                    "complete_collection": self._completed_tracking_record(complete_video, publish_at),
                    "status": TRACKING_STATUS_COMPLETED,
                }

                # live 移動
                if self.config["collections_management"].get("auto_move_to_live", True):
                    collection_path = self._move_collection_to_live(collection_path)

                self._update_workflow_upload(collection_path, complete_video, publish_at)
                self._save_tracking(collection_path, tracking)

                if complete_video.get("upload_source") == UPLOAD_SOURCE_EXISTING:
                    logger.info("⏭️  Complete Collection は既存動画を流用")
                else:
                    logger.info("✅ Complete Collection アップロード完了")
                logger.info(f"📹 {complete_video['video_url']}")

                # プレイリスト自動追加
                self._assign_to_playlists(complete_video["video_id"], collection_path)

                action = (
                    ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED
                    if complete_video.get("upload_source") == UPLOAD_SOURCE_EXISTING
                    else ACTION_COMPLETE_COLLECTION_UPLOADED
                )
                return {"action": action, "details": {**tracking["complete_collection"]}}
            else:
                error_msg = (complete_video or {}).get("error", "Unknown error")
                # callback が disk に書いた URI 状態（session 失効クリア等）を保ったまま
                # status 更新を載せるため、disk から再ロードしてから書き戻す。
                current = self._load_tracking(collection_path) or tracking
                cc_current = current.setdefault("complete_collection", {})
                cc_current["status"] = "failed"
                cc_current["error"] = error_msg
                self._save_tracking(collection_path, current)
                logger.error(f"❌ Complete Collection 失敗: {error_msg}")
                return {"action": "complete_collection_failed", "details": {"error": error_msg}}

        except QuotaExhaustedError as e:
            # リトライ可能: tracking を failed にせず、resume URI（callback が永続化済み）を
            # 温存して次回実行に委ねる
            logger.error(f"⏸️  quota 枯渇のため中断（再実行で resume）: {e}")
            return {
                "action": ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
                "details": {"error": str(e), "retry_after_seconds": e.retry_after_seconds},
            }
        except Exception as e:
            # 例外パスでも callback が書いた disk 状態を尊重するため再ロード
            current = self._load_tracking(collection_path) or tracking
            cc_current = current.setdefault("complete_collection", {})
            cc_current["status"] = "failed"
            cc_current["error"] = str(e)
            self._save_tracking(collection_path, current)
            logger.error(f"❌ Complete Collection エラー: {e}")
            return {"action": "complete_collection_failed", "details": {"error": str(e)}}


__all__ = ["CompleteCollectionExecutorMixin"]
