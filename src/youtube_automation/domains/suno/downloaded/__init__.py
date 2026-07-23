"""Downloaded-artifact operations and their value contracts."""

from youtube_automation.domains.suno.downloaded.apply import apply_downloaded_artifacts
from youtube_automation.domains.suno.downloaded.archive import count_audio_files
from youtube_automation.domains.suno.downloaded.models import (
    DownloadedArtifactError,
    DownloadedPayload,
    DownloadedPayloadError,
    parse_downloaded_payload,
)
from youtube_automation.domains.suno.downloaded.workflow import expected_download_count, read_pattern_count

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
