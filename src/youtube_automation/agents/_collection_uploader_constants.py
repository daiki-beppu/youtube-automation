"""``CollectionUploader`` 周辺で共有される定数。

責務分割（Issue #465）の一環で ``collection_uploader.py`` から外出しした。
"""

from __future__ import annotations

ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED = "complete_collection_dedup_skipped"
ACTION_COMPLETE_COLLECTION_UPLOADED = "complete_collection_uploaded"
ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED = "complete_collection_quota_exhausted"
TRACKING_STATUS_COMPLETED = "completed"
WORKFLOW_PHASE_COMPLETE = "complete"
WORKFLOW_STAGE_LIVE = "live"

__all__ = [
    "ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED",
    "ACTION_COMPLETE_COLLECTION_UPLOADED",
    "ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED",
    "TRACKING_STATUS_COMPLETED",
    "WORKFLOW_PHASE_COMPLETE",
    "WORKFLOW_STAGE_LIVE",
]
