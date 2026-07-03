"""Suno downloaded artifact helpers.

互換 facade。実処理は payload / archive / workflow_state / apply の各 module に分ける。
"""

from __future__ import annotations

from youtube_automation.utils.suno_downloaded_apply import apply_downloaded_artifacts
from youtube_automation.utils.suno_downloaded_archive import count_audio_files
from youtube_automation.utils.suno_downloaded_payload import (
    DownloadedArtifactError,
    DownloadedPayload,
    DownloadedPayloadError,
    parse_downloaded_payload,
)
from youtube_automation.utils.suno_downloaded_workflow_state import (
    expected_download_count,
    read_pattern_count,
)

__all__ = [
    "DownloadedArtifactError",
    "DownloadedPayload",
    "DownloadedPayloadError",
    "apply_downloaded_artifacts",
    "count_audio_files",
    "expected_download_count",
    "parse_downloaded_payload",
    "read_pattern_count",
]
