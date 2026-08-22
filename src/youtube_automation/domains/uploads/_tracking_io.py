"""tracking JSON / workflow-state JSON の永続化コラボレータ。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from youtube_automation.core.adapters.media import CollectionPaths
from youtube_automation.core.adapters.runtime import now_in_schedule_tz
from youtube_automation.core.errors import ValidationError, WorkflowStateError, WorkflowStateSectionTypeError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read_or_none as read_workflow_state_or_none
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.uploads._collection_uploader_constants import (
    TRACKING_STATUS_COMPLETED,
    WORKFLOW_PHASE_COMPLETE,
    WORKFLOW_STAGE_LIVE,
)
from youtube_automation.infrastructure.filesystem import (
    make_directory,
    path_exists,
    read_file_text,
    replace_file,
    write_file_text,
)

logger = logging.getLogger(__name__)


class TrackingStore:
    """collection tracking と upload workflow state を永続化する。"""

    def __init__(self, collections_root: Path, config: dict) -> None:
        self.collections_root = collections_root
        self.config = config

    def tracking_path(self, collection_path: Path) -> Path:
        return CollectionPaths(collection_path).tracking_path

    def load(self, collection_path: Path) -> dict | None:
        """tracking ファイル読み込み"""
        tracking_file = self.tracking_path(collection_path)
        if not path_exists(tracking_file):
            return None

        try:
            return self.read(collection_path)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # 破損ファイルを退避してから None を返す（無言で消さず証拠を保全）。
            # 呼び出し側は None を「tracking なし」として扱い dedup 探索が働く。
            corrupt_path = tracking_file.with_suffix(".json.corrupt")
            replace_file(tracking_file, corrupt_path)
            logger.error(f"❌ tracking 破損を検出、{corrupt_path} へ退避しました（原因: {e}）")
            return None

    def read(self, collection_path: Path) -> dict:
        """tracking を読み、欠落・破損時の例外を呼び出し側へ伝える。"""
        return json.loads(read_file_text(self.tracking_path(collection_path)))

    def save(self, collection_path: Path, tracking: dict) -> None:
        """tracking 保存"""
        tracking_file = self.tracking_path(collection_path)
        make_directory(tracking_file.parent, exist_ok=True)
        try:
            text = json.dumps(tracking, indent=2, ensure_ascii=False)
            # 途中断絶時の tracking 破損を防ぐため tmp に書いてから rename で差し替える
            tmp_path = tracking_file.with_suffix(tracking_file.suffix + ".tmp")
            write_file_text(tmp_path, text)
            replace_file(tmp_path, tracking_file)
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"❌ 追跡ファイル保存エラー: {tracking_file}: {e}")

    def completed_record(self, complete_video: dict, publish_at: str | None) -> dict:
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

    def update_workflow_upload(self, collection_path: Path, complete_video: dict, publish_at: str | None) -> None:
        ws_path = CollectionPaths(collection_path).workflow_state_path
        if not path_exists(ws_path):
            return

        def record_upload(state: WorkflowState) -> None:
            state.record_upload(
                video_id=complete_video["video_id"],
                video_url=complete_video["video_url"],
                publish_at=publish_at,
            )
            if collection_path.parent.name == WORKFLOW_STAGE_LIVE:
                state.stage = WORKFLOW_STAGE_LIVE
                state.phase = WORKFLOW_PHASE_COMPLETE

        try:
            update_workflow_state(ws_path, record_upload)
        except WorkflowStateError as error:
            if isinstance(error.__cause__, json.JSONDecodeError):
                raise error.__cause__ from error
            if isinstance(error, WorkflowStateSectionTypeError) and error.section == "upload":
                raise ValidationError(f"workflow-state.json upload must be object: {ws_path}") from error
            raise ValidationError(str(error)) from error

    def load_workflow_state(self, workflow_state_path: Path) -> dict | None:
        """workflow-state を読み、欠落・破損は Shorts の既存 fail-safe に合わせる。"""
        if not path_exists(workflow_state_path):
            return None
        try:
            state = read_workflow_state_or_none(workflow_state_path)
            return state.to_dict() if state is not None else None
        except WorkflowStateError as error:
            logger.warning(f"workflow-state.json 読み込み失敗: {error}")
            return None

    @staticmethod
    def _find_short_entry(shorts: list, short_num: int | None) -> dict | None:
        for entry in shorts:
            if isinstance(entry, dict) and entry.get("short_num") == short_num:
                return entry
        return None

    def read_short_resume_uri(self, workflow_state_path: Path, short_num: int | None) -> str | None:
        state = self.load_workflow_state(workflow_state_path)
        if not state:
            return None
        shorts = (state.get("post_upload") or {}).get("shorts") or []
        entry = self._find_short_entry(shorts, short_num)
        return entry.get("resume_session_uri") if entry else None

    def persist_short_resume_uri(
        self,
        workflow_state_path: Path,
        short_num: int | None,
        uri: str | None,
    ) -> None:
        if not path_exists(workflow_state_path):
            logger.warning(f"workflow-state.json が無いため resume URI 永続化を skip: {workflow_state_path}")
            return

        def persist_resume_uri(state: WorkflowState) -> None:
            post_upload = state.get("post_upload") or {}
            if not isinstance(post_upload, dict):
                post_upload = {}
            shorts = post_upload.get("shorts")
            if not isinstance(shorts, list):
                shorts = []
                post_upload["shorts"] = shorts

            entry = self._find_short_entry(shorts, short_num)
            if entry is None:
                entry = {"short_num": short_num}
                shorts.append(entry)
            if uri is None:
                entry.pop("resume_session_uri", None)
            else:
                entry["resume_session_uri"] = uri
            state["post_upload"] = post_upload

        try:
            update_workflow_state(workflow_state_path, persist_resume_uri)
        except WorkflowStateError as error:
            logger.warning(f"workflow-state.json 読み込み/書き込み失敗: {error}")

    def record_short_upload(
        self,
        collection_path: Path,
        *,
        short_num: int | None,
        video_id: str,
        publish_at: str | None,
    ) -> None:
        workflow_state_path = CollectionPaths(collection_path).workflow_state_path
        if not path_exists(workflow_state_path):
            logger.warning(f"workflow-state.json が無いため short upload 記録を skip: {workflow_state_path}")
            return

        entry = {
            "short_num": short_num,
            "video_id": video_id,
            "uploaded_at": now_in_schedule_tz(self.config).isoformat(),
            "publish_at": publish_at,
        }

        def record_uploaded_short(state: WorkflowState) -> None:
            post_upload = state.get("post_upload") or {}
            if not isinstance(post_upload, dict):
                post_upload = {}
            shorts = post_upload.get("shorts")
            if not isinstance(shorts, list):
                shorts = []
                post_upload["shorts"] = shorts
            for index, existing in enumerate(shorts):
                if existing.get("short_num") == short_num:
                    shorts[index] = entry
                    break
            else:
                shorts.append(entry)
            state["post_upload"] = post_upload

        try:
            update_workflow_state(workflow_state_path, record_uploaded_short)
        except WorkflowStateError as error:
            logger.warning(f"workflow-state.json 読み込み/書き込み失敗: {error}")

    def initialize(self, collection_path: Path) -> dict:
        """tracking を初期化"""
        tracking = {
            "schema_version": 3,
            "collection_name": collection_path.name,
            "status": "in_progress",
            "complete_collection": {"status": "pending"},
        }

        self.save(collection_path, tracking)
        return tracking


__all__ = ["TrackingStore"]
