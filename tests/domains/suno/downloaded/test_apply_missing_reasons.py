"""Suno downloaded apply missing-reason contract tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from youtube_automation.domains.suno.downloaded.apply import (
    DownloadedApplyResult,
    apply_downloaded_artifacts,
    apply_downloaded_artifacts_detailed,
)
from youtube_automation.domains.suno.downloaded.models import (
    DownloadedArtifactError,
    DownloadedPayload,
    PromptEntriesReader,
)


def _prepare_collection(collection_dir: Path) -> PromptEntriesReader:
    documentation_dir = collection_dir / "20-documentation"
    documentation_dir.mkdir()
    (documentation_dir / "suno-prompts.json").write_text("[]", encoding="utf-8")
    return lambda _collection_dir: [{"name": "既知 — Known"}]


def _write_archive(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def _payload(archive: Path, *, expected_count: int) -> DownloadedPayload:
    return DownloadedPayload(
        file_count=0,
        format="mp3",
        expected_file_count=expected_count,
        download_path=str(archive),
    )


def test_detailed_apply_calculates_and_persists_missing_reasons(tmp_path: Path) -> None:
    read_entries = _prepare_collection(tmp_path)
    archive = _write_archive(
        tmp_path / "download.zip",
        {
            "Known.mp3": b"matched-a",
            "Known_1.mp3": b"matched-b",
            "Unknown.mp3": b"unmatched",
        },
    )

    result = apply_downloaded_artifacts_detailed(
        tmp_path,
        _payload(archive, expected_count=4),
        prompt_entries_reader=read_entries,
    )

    assert result == DownloadedApplyResult(
        expected_count=4,
        audio_count=3,
        placed_count=2,
        suno_unfulfilled=1,
        apply_skipped=1,
    )
    state = json.loads((tmp_path / "workflow-state.json").read_text(encoding="utf-8"))
    assert state["planning"]["music"]["missing_reasons"] == result.missing_reasons


def test_detailed_apply_clamps_unfulfilled_when_archive_exceeds_expected(tmp_path: Path) -> None:
    read_entries = _prepare_collection(tmp_path)
    archive = _write_archive(
        tmp_path / "download.zip",
        {"Known.mp3": b"matched-a", "Known_1.mp3": b"matched-b"},
    )

    result = apply_downloaded_artifacts_detailed(
        tmp_path,
        _payload(archive, expected_count=1),
        prompt_entries_reader=read_entries,
    )

    assert result.suno_unfulfilled == 0
    assert result.apply_skipped == 0


def test_legacy_apply_still_returns_placed_count(tmp_path: Path) -> None:
    read_entries = _prepare_collection(tmp_path)
    archive = _write_archive(
        tmp_path / "download.zip",
        {"Known.mp3": b"matched", "Unknown.mp3": b"unmatched"},
    )

    placed_count = apply_downloaded_artifacts(
        tmp_path,
        _payload(archive, expected_count=2),
        prompt_entries_reader=read_entries,
    )

    assert placed_count == 1


def test_detailed_apply_keeps_zero_placed_fail_loud(tmp_path: Path) -> None:
    read_entries = _prepare_collection(tmp_path)
    archive = _write_archive(tmp_path / "download.zip", {"Unknown.mp3": b"unmatched"})

    with pytest.raises(DownloadedArtifactError, match="0 audio files placed"):
        apply_downloaded_artifacts_detailed(
            tmp_path,
            _payload(archive, expected_count=2),
            prompt_entries_reader=read_entries,
        )

    assert archive.exists()
    assert not (tmp_path / "02-Individual-music").exists()
    assert not (tmp_path / "workflow-state.json").exists()
