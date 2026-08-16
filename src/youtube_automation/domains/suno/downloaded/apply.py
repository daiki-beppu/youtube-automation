"""Suno downloaded artifact の適用 transaction。"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from youtube_automation.core.adapters.media import CollectionPaths
from youtube_automation.domains.suno.downloaded.archive import extract_downloaded_archive_detailed
from youtube_automation.domains.suno.downloaded.models import (
    DownloadedArtifactError,
    DownloadedPayload,
    PromptEntriesReader,
)
from youtube_automation.domains.suno.downloaded.workflow import (
    expected_download_count,
    read_pattern_count,
    update_workflow_state_downloaded,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DownloadedApplyResult:
    expected_count: int
    audio_count: int
    placed_count: int
    suno_unfulfilled: int
    apply_skipped: int

    @classmethod
    def from_counts(cls, *, expected_count: int, audio_count: int, placed_count: int) -> DownloadedApplyResult:
        return cls(
            expected_count=expected_count,
            audio_count=audio_count,
            placed_count=placed_count,
            suno_unfulfilled=max(expected_count - audio_count, 0),
            apply_skipped=max(audio_count - placed_count, 0),
        )

    @property
    def missing_reasons(self) -> dict[str, int]:
        return {
            "suno_unfulfilled": self.suno_unfulfilled,
            "apply_skipped": self.apply_skipped,
        }


def _restore_downloaded_transaction(
    *,
    music_dir: Path,
    music_backup_dir: Path | None,
    restore_music: bool,
) -> None:
    if restore_music:
        shutil.rmtree(music_dir, ignore_errors=True)
        if music_backup_dir is not None:
            restored = music_backup_dir / "02-Individual-music"
            if restored.exists():
                shutil.copytree(restored, music_dir)


def apply_downloaded_artifacts_detailed(
    coll_dir: Path,
    payload: DownloadedPayload,
    *,
    prompt_entries_reader: PromptEntriesReader,
    defer_archive_cleanup: bool = False,
) -> DownloadedApplyResult:
    pattern_count = read_pattern_count(coll_dir, prompt_entries_reader=prompt_entries_reader, default=0)
    expected_count = cast(int, expected_download_count(pattern_count, payload.expected_file_count))
    audio_count = payload.file_count
    placed_count = payload.file_count
    paths = CollectionPaths(coll_dir)
    music_dir = paths.music_dir
    music_backup_dir: Path | None = None
    restore_music_on_error = False

    try:
        if payload.download_path:
            if music_dir.exists():
                music_backup_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-apply-backup-"))
                shutil.copytree(music_dir, music_backup_dir / "02-Individual-music")
            restore_music_on_error = True
            archive_result = extract_downloaded_archive_detailed(
                coll_dir, payload.download_path, prompt_entries_reader=prompt_entries_reader
            )
            audio_count = archive_result.audio_count
            placed_count = archive_result.placed_count

        result = DownloadedApplyResult.from_counts(
            expected_count=expected_count,
            audio_count=audio_count,
            placed_count=placed_count,
        )

        update_workflow_state_downloaded(
            coll_dir,
            file_count=result.placed_count,
            suno_playlist_url=payload.suno_playlist_url,
            expected_file_count=result.expected_count,
            missing_reasons=result.missing_reasons,
            prompt_entries_reader=prompt_entries_reader,
        )
    except DownloadedArtifactError:
        _restore_downloaded_transaction(
            music_dir=music_dir,
            music_backup_dir=music_backup_dir,
            restore_music=restore_music_on_error,
        )
        raise
    except (OSError, ValueError, shutil.Error) as exc:
        _restore_downloaded_transaction(
            music_dir=music_dir,
            music_backup_dir=music_backup_dir,
            restore_music=restore_music_on_error,
        )
        raise DownloadedArtifactError(str(exc)) from exc
    finally:
        if music_backup_dir is not None:
            shutil.rmtree(music_backup_dir, ignore_errors=True)
    if not defer_archive_cleanup:
        cleanup_downloaded_archive(payload)
    return result


def cleanup_downloaded_archive(payload: DownloadedPayload) -> None:
    if payload.download_path:
        try:
            Path(payload.download_path).unlink()
        except OSError as exc:
            logger.warning("Suno download ZIP cleanup failed for %s: %s", payload.download_path, exc)


def apply_downloaded_artifacts(
    coll_dir: Path,
    payload: DownloadedPayload,
    *,
    prompt_entries_reader: PromptEntriesReader,
) -> int:
    return apply_downloaded_artifacts_detailed(
        coll_dir,
        payload,
        prompt_entries_reader=prompt_entries_reader,
    ).placed_count
