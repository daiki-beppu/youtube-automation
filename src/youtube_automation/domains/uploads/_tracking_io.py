"""tracking JSON / workflow-state JSON の I/O を提供する mixin。

責務分割（Issue #465）の一環で ``collection_uploader.py`` から分離した。
挙動は分割前と同一で、``self.config`` / ``self.collections_root`` 等は
合成先クラス（``CollectionUploader`` 本体）が提供する。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from youtube_automation.domains.uploads._collection_uploader_constants import (
    TRACKING_STATUS_COMPLETED,
    WORKFLOW_PHASE_COMPLETE,
    WORKFLOW_STAGE_LIVE,
)
from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.infrastructure.filesystem import (
    make_directory,
    path_exists,
    read_file_text,
    replace_file,
    write_file_text,
)
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.schedule import now_in_schedule_tz

logger = logging.getLogger(__name__)


class TrackingIOMixin:
    """tracking JSON / workflow-state JSON の I/O を提供する mixin。"""

    def _get_tracking_path(self, collection_path: Path) -> Path:
        return CollectionPaths(collection_path).tracking_path

    def _load_tracking(self, collection_path: Path) -> dict | None:
        """tracking ファイル読み込み"""
        tracking_file = self._get_tracking_path(collection_path)
        if not path_exists(tracking_file):
            return None

        try:
            return json.loads(read_file_text(tracking_file))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # 破損ファイルを退避してから None を返す（無言で消さず証拠を保全）。
            # 呼び出し側は None を「tracking なし」として扱い dedup 探索が働く。
            corrupt_path = tracking_file.with_suffix(".json.corrupt")
            replace_file(tracking_file, corrupt_path)
            logger.error(f"❌ tracking 破損を検出、{corrupt_path} へ退避しました（原因: {e}）")
            return None

    def _save_tracking(self, collection_path: Path, tracking: dict):
        """tracking 保存"""
        tracking_file = self._get_tracking_path(collection_path)
        make_directory(tracking_file.parent, exist_ok=True)
        try:
            text = json.dumps(tracking, indent=2, ensure_ascii=False)
            # 途中断絶時の tracking 破損を防ぐため tmp に書いてから rename で差し替える
            tmp_path = tracking_file.with_suffix(tracking_file.suffix + ".tmp")
            write_file_text(tmp_path, text)
            replace_file(tmp_path, tracking_file)
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"❌ 追跡ファイル保存エラー: {tracking_file}: {e}")

    def _completed_tracking_record(self, complete_video: dict, publish_at: str | None) -> dict:
        record = {
            "video_id": complete_video["video_id"],
            "video_url": complete_video["video_url"],
            "upload_time": now_in_schedule_tz(self.config).isoformat(),
            "publish_at": publish_at,
            "status": TRACKING_STATUS_COMPLETED,
        }
        if complete_video.get("upload_source"):
            record["upload_source"] = complete_video["upload_source"]
        return record

    def _update_workflow_upload(self, collection_path: Path, complete_video: dict, publish_at: str | None) -> None:
        ws_path = CollectionPaths(collection_path).workflow_state_path
        if not path_exists(ws_path):
            return

        state = json.loads(read_file_text(ws_path))
        upload = state.get("upload")
        if not isinstance(upload, dict):
            raise ValidationError(f"workflow-state.json upload must be object: {ws_path}")

        updated_upload = {
            **upload,
            "video_id": complete_video["video_id"],
            "video_url": complete_video["video_url"],
            "publish_at": publish_at,
        }
        updated_state = {
            **state,
            "upload": updated_upload,
            "updated_at": now_in_schedule_tz(self.config).isoformat(),
        }
        if collection_path.parent.name == WORKFLOW_STAGE_LIVE:
            updated_state = {
                **updated_state,
                "stage": WORKFLOW_STAGE_LIVE,
                "phase": WORKFLOW_PHASE_COMPLETE,
            }
        write_file_text(ws_path, json.dumps(updated_state, indent=2, ensure_ascii=False))

    def _initialize_tracking(self, collection_path: Path) -> dict:
        """tracking を初期化"""
        tracking = {
            "schema_version": 3,
            "collection_name": collection_path.name,
            "status": "in_progress",
            "complete_collection": {"status": "pending"},
        }

        self._save_tracking(collection_path, tracking)
        return tracking


__all__ = ["TrackingIOMixin"]
