"""Suno downloaded artifact helpers.

互換 facade。実処理は payload / archive / workflow_state / apply の各 module に分ける。
"""

from __future__ import annotations

from youtube_automation.utils.suno_downloaded_apply import _apply_downloaded_artifacts, apply_downloaded_artifacts
from youtube_automation.utils.suno_downloaded_archive import (
    _commit_staged_music_files,
    _count_audio_files,
    _extract_and_rename_music,
    _extract_downloaded_archive,
    commit_staged_music_files,
    count_audio_files,
    extract_and_rename_music,
    extract_downloaded_archive,
)
from youtube_automation.utils.suno_downloaded_payload import (
    DownloadedArtifactError,
    DownloadedPayload,
    DownloadedPayloadError,
    _parse_downloaded_payload,
    parse_downloaded_payload,
)
from youtube_automation.utils.suno_downloaded_workflow_state import (
    AtomicJsonWriter,
    _expected_download_count,
    _read_pattern_count,
    _update_workflow_state_downloaded,
    expected_download_count,
    read_pattern_count,
    update_workflow_state_downloaded,
)

__all__ = [
    "AtomicJsonWriter",
    "DownloadedArtifactError",
    "DownloadedPayload",
    "DownloadedPayloadError",
    "_apply_downloaded_artifacts",
    "_commit_staged_music_files",
    "_count_audio_files",
    "_expected_download_count",
    "_extract_and_rename_music",
    "_extract_downloaded_archive",
    "_parse_downloaded_payload",
    "_read_pattern_count",
    "_update_workflow_state_downloaded",
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
