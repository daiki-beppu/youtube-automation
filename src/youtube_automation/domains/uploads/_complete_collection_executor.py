"""Complete Collection アップロード実行 collaborator。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from youtube_automation.core.adapters import cost_tracker
from youtube_automation.core.adapters.security import redact_sensitive_data
from youtube_automation.core.adapters.youtube import complete_collection_quota_plan, quota_shortages
from youtube_automation.core.errors import AutomationError, QuotaExhaustedError, UploadJournalError
from youtube_automation.domains.uploads._collection_uploader_constants import (
    ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED,
    ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
    ACTION_COMPLETE_COLLECTION_UPLOADED,
    TRACKING_STATUS_COMPLETED,
)
from youtube_automation.domains.uploads.upload_journal import UploadJournal
from youtube_automation.domains.uploads.youtube import UPLOAD_SOURCE_EXISTING

logger = logging.getLogger(__name__)

_COMPLETE_COLLECTION_ERROR = "complete collection upload failed"


class CompleteCollectionExecutor:
    """明示された collaborator で Complete Collection 実行ループを進める。"""

    def __init__(
        self,
        uploader,
        tracking_store,
        config: dict,
        playlist_assignment,
        move_collection_to_live,
        upload_journal_factory: Callable[[Path], UploadJournal] = UploadJournal,
    ) -> None:
        self.uploader = uploader
        self.tracking_store = tracking_store
        self.config = config
        self.playlist_assignment = playlist_assignment
        self.move_collection_to_live = move_collection_to_live
        self.upload_journal_factory = upload_journal_factory

    def failed(self, collection_path: Path, tracking: dict, error: AutomationError) -> dict:
        current = self.tracking_store.load(collection_path) or tracking
        cc_current = current.setdefault("complete_collection", {})
        cc_current["status"] = "failed"
        cc_current["error"] = _COMPLETE_COLLECTION_ERROR
        self.tracking_store.save(collection_path, current)
        logger.error("❌ Complete Collection エラー: %s", redact_sensitive_data(str(error), collection_path))
        return {"action": "complete_collection_failed", "details": {"error": _COMPLETE_COLLECTION_ERROR}}

    def finish(
        self,
        collection_path: Path,
        tracking: dict,
        complete_video: dict,
        publish_at: str | None,
    ) -> dict:
        # playlist 所有権エラー時にローカル状態を成功確定しないため、最初に割り当てる。
        self.playlist_assignment.assign(complete_video["video_id"], collection_path)

        tracking = {
            **tracking,
            "complete_collection": self.tracking_store.completed_record(complete_video, publish_at),
            "status": TRACKING_STATUS_COMPLETED,
        }
        # YouTube 側の成功直後に正規状態を保存し、後処理失敗で video_id を失わない。
        self.tracking_store.save(collection_path, tracking)

        post_processing_errors: list[str] = []
        if self.config["collections_management"].get("auto_move_to_live", True):
            try:
                collection_path = self.move_collection_to_live(collection_path)
            except AutomationError as error:
                post_processing_errors.append("move_to_live")
                logger.error(
                    "⚠️  Complete Collection 後処理エラー (move_to_live): %s",
                    redact_sensitive_data(str(error), collection_path),
                )

        try:
            self.tracking_store.update_workflow_upload(collection_path, complete_video, publish_at)
        except AutomationError as error:
            post_processing_errors.append("workflow_upload")
            logger.error(
                "⚠️  Complete Collection 後処理エラー (workflow_upload): %s",
                redact_sensitive_data(str(error), collection_path),
            )

        if post_processing_errors:
            tracking["complete_collection"] = {
                **tracking["complete_collection"],
                "post_processing_status": "partial",
                "post_processing_errors": post_processing_errors,
            }
        self.tracking_store.save(collection_path, tracking)

        if complete_video.get("upload_source") == UPLOAD_SOURCE_EXISTING:
            logger.info("⏭️  Complete Collection は既存動画を流用")
            action = ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED
        else:
            logger.info("✅ Complete Collection アップロード完了")
            action = ACTION_COMPLETE_COLLECTION_UPLOADED
        logger.info(f"📹 {complete_video['video_url']}")
        return {"action": action, "details": {**tracking["complete_collection"]}}

    def run(self, collection_path: Path, tracking: dict, publish_at: str | None = None) -> dict:
        """Complete Collection アップロード"""
        logger.info("📅 Complete Collection アップロード開始")
        logger.info(f"🎵 コレクション: {collection_path.name}")
        if publish_at:
            logger.info(f"📅 スケジュール公開: {publish_at}")

        # 移行前 tracking の URI は journal 初回利用時だけ引き継ぐ。
        cc = tracking.get("complete_collection", {})
        try:
            attempt = self.upload_journal_factory(collection_path).begin("complete_collection")
            resume_session_uri = attempt.resume_uri
            legacy_resume_uri = cc.get("resume_session_uri")
            if resume_session_uri is None and isinstance(legacy_resume_uri, str):
                attempt.record_session(legacy_resume_uri)
                resume_session_uri = legacy_resume_uri
        except UploadJournalError as error:
            logger.error("❌ upload journal 読み込み失敗: %s", error)
            return {"action": "complete_collection_failed", "details": {"error": _COMPLETE_COLLECTION_ERROR}}

        shortages = quota_shortages(
            complete_collection_quota_plan(),
            cost_tracker.read_quota_log(),
        )
        if shortages:
            error = QuotaExhaustedError("YouTube API quota preflight failed: " + "; ".join(shortages))
            logger.error(f"⏸️  quota 枯渇のため中断（再実行で resume）: {error}")
            return {
                "action": ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
                "details": {"error": str(error), "retry_after_seconds": None},
            }

        def _on_session_uri_changed(uri: str | None) -> None:
            """upload 中の URI 変化を journal に永続化する。"""
            attempt.record_session(uri)

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
        except QuotaExhaustedError as e:
            # リトライ可能: tracking を failed にせず、resume URI（callback が永続化済み）を
            # 温存して次回実行に委ねる
            logger.error("⏸️  quota 枯渇のため中断（再実行で resume）")
            return {
                "action": ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
                "details": {"error": "quota exhausted", "retry_after_seconds": e.retry_after_seconds},
            }
        except AutomationError as error:
            try:
                attempt.fail(_COMPLETE_COLLECTION_ERROR)
            except UploadJournalError:
                logger.exception("upload journal への失敗記録にも失敗しました")
            return self.failed(collection_path, tracking, error)

        complete_video = result.get("complete_video")
        if complete_video and "video_id" in complete_video:
            try:
                attempt.complete(complete_video)
            except UploadJournalError as error:
                logger.error("❌ upload journal 完了記録失敗: %s", error)
                return {"action": "complete_collection_failed", "details": {"error": _COMPLETE_COLLECTION_ERROR}}
            return self.finish(collection_path, tracking, complete_video, publish_at)

        error_msg = _COMPLETE_COLLECTION_ERROR
        attempt.fail(error_msg)
        current = self.tracking_store.load(collection_path) or tracking
        cc_current = current.setdefault("complete_collection", {})
        cc_current["status"] = "failed"
        cc_current["error"] = error_msg
        self.tracking_store.save(collection_path, current)
        logger.error(f"❌ Complete Collection 失敗: {error_msg}")
        return {"action": "complete_collection_failed", "details": {"error": error_msg}}


__all__ = ["CompleteCollectionExecutor"]
