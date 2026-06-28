"""Suno downloaded artifact helpers.

互換 facade。実処理は payload / archive / workflow_state / apply の各 module に分ける。
"""

from __future__ import annotations

from youtube_automation.utils.suno_downloaded_apply import apply_downloaded_artifacts
from youtube_automation.utils.suno_downloaded_archive import (
    commit_staged_music_files,
    count_audio_files,
    extract_and_rename_music,
    extract_downloaded_archive,
)
from youtube_automation.utils.suno_downloaded_payload import (
    DownloadedArtifactError,
    DownloadedPayload,
    DownloadedPayloadError,
    parse_downloaded_payload,
)
from youtube_automation.utils.suno_downloaded_workflow_state import (
    AtomicJsonWriter,
    expected_download_count,
    read_pattern_count,
    update_workflow_state_downloaded,
)

__all__ = [
    "AtomicJsonWriter",
    "DownloadedArtifactError",
    "DownloadedPayload",
    "DownloadedPayloadError",
    "apply_downloaded_artifacts",
    "commit_staged_music_files",
    "count_audio_files",
    "expected_download_count",
    "extract_and_rename_music",
    "extract_downloaded_archive",
    "parse_downloaded_payload",
    "read_pattern_count",
    "update_workflow_state_downloaded",
]
