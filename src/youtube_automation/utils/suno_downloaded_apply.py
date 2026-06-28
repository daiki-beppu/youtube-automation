"""Suno downloaded artifact の適用 transaction。"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.suno_downloaded_archive import extract_downloaded_archive
from youtube_automation.utils.suno_downloaded_payload import DownloadedArtifactError, DownloadedPayload
from youtube_automation.utils.suno_downloaded_workflow_state import (
    AtomicJsonWriter,
    expected_download_count,
    read_pattern_count,
    update_workflow_state_downloaded,
)


def apply_downloaded_artifacts(
    coll_dir: Path,
    payload: DownloadedPayload,
    *,
    atomic_json_write: AtomicJsonWriter,
) -> int:
    pattern_count = read_pattern_count(coll_dir, default=0)
    expected_count = expected_download_count(pattern_count, payload.expected_file_count)
    placed_count_for_response = payload.file_count
    file_count = payload.file_count
    paths = CollectionPaths(coll_dir)
    music_dir = paths.music_dir
    workflow_state_path = paths.workflow_state_path
    music_backup_dir: Path | None = None
    workflow_existed = workflow_state_path.exists()
    workflow_backup = workflow_state_path.read_bytes() if workflow_existed else None

    try:
        if payload.download_path:
            if music_dir.exists():
                music_backup_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-apply-backup-"))
                shutil.copytree(music_dir, music_backup_dir / "02-Individual-music")
            placed_count = extract_downloaded_archive(coll_dir, payload.download_path, expected_count)
            placed_count_for_response = placed_count
            file_count = placed_count

        update_workflow_state_downloaded(
            coll_dir,
            file_count=file_count,
            suno_playlist_url=payload.suno_playlist_url,
            expected_file_count=expected_count,
            atomic_json_write=atomic_json_write,
        )
    except Exception as exc:
        if payload.download_path:
            shutil.rmtree(music_dir, ignore_errors=True)
            if music_backup_dir is not None:
                restored = music_backup_dir / "02-Individual-music"
                if restored.exists():
                    shutil.copytree(restored, music_dir)
            if workflow_backup is not None:
                workflow_state_path.parent.mkdir(parents=True, exist_ok=True)
                workflow_state_path.write_bytes(workflow_backup)
            elif not workflow_existed:
                workflow_state_path.unlink(missing_ok=True)
        if isinstance(exc, DownloadedArtifactError):
            raise
        raise DownloadedArtifactError(str(exc)) from exc
    finally:
        if music_backup_dir is not None:
            shutil.rmtree(music_backup_dir, ignore_errors=True)
    return placed_count_for_response
