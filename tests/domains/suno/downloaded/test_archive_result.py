"""Suno downloaded ZIP archive result contract tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from youtube_automation.domains.suno.downloaded.archive import (
    DownloadedArchiveResult,
    extract_downloaded_archive,
    extract_downloaded_archive_detailed,
)
from youtube_automation.domains.suno.downloaded.models import (
    DownloadedArtifactError,
    PromptEntriesReader,
)


def _prepare_collection(collection_dir: Path, entries: list[dict[str, str]]) -> PromptEntriesReader:
    documentation_dir = collection_dir / "20-documentation"
    documentation_dir.mkdir()
    (documentation_dir / "suno-prompts.json").write_text("[]", encoding="utf-8")
    return lambda _collection_dir: entries


def _write_archive(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def test_detailed_extraction_reports_archive_audio_and_placed_counts(tmp_path: Path) -> None:
    """Given matched/unmatched 音声を含む ZIP
    When detailed API で展開する
    Then archive 内音声総数と実配置数を別々に返す。
    """
    read_entries = _prepare_collection(tmp_path, [{"name": "既知 — Known"}])
    archive = _write_archive(
        tmp_path / "download.zip",
        {"Known.mp3": b"matched", "Unknown.mp3": b"unmatched"},
    )

    result = extract_downloaded_archive_detailed(
        tmp_path,
        str(archive),
        prompt_entries_reader=read_entries,
    )

    assert result == DownloadedArchiveResult(audio_count=2, placed_count=1)
    assert [path.name for path in (tmp_path / "02-Individual-music").iterdir()] == ["01a-Known.mp3"]


def test_legacy_extraction_returns_placed_count(tmp_path: Path) -> None:
    """Given matched/unmatched 音声を含む ZIP
    When 現行 API で展開する
    Then 従来どおり実配置数だけを返す。
    """
    read_entries = _prepare_collection(tmp_path, [{"name": "既知 — Known"}])
    archive = _write_archive(
        tmp_path / "download.zip",
        {"Known.mp3": b"matched", "Unknown.mp3": b"unmatched"},
    )

    placed_count = extract_downloaded_archive(
        tmp_path,
        str(archive),
        prompt_entries_reader=read_entries,
    )

    assert placed_count == 1


def test_detailed_extraction_keeps_zip_slip_validation(tmp_path: Path) -> None:
    """Given safe/unsafe 音声 entry を含む ZIP
    When detailed API で展開する
    Then unsafe entry を配置せず archive 内音声総数には含める。
    """
    read_entries = _prepare_collection(tmp_path, [{"name": "既知 — Known"}])
    archive = _write_archive(
        tmp_path / "download.zip",
        {"Known.mp3": b"safe", "../Known_1.mp3": b"unsafe"},
    )

    result = extract_downloaded_archive_detailed(
        tmp_path,
        str(archive),
        prompt_entries_reader=read_entries,
    )

    assert result == DownloadedArchiveResult(audio_count=2, placed_count=1)
    assert not (tmp_path.parent / "Known_1.mp3").exists()


def test_detailed_extraction_fails_when_no_audio_is_placed(tmp_path: Path) -> None:
    """Given prompts に一致しない音声だけの ZIP
    When detailed API で展開する
    Then 配置0件を fail-loud にする。
    """
    read_entries = _prepare_collection(tmp_path, [{"name": "既知 — Known"}])
    archive = _write_archive(tmp_path / "download.zip", {"Unknown.mp3": b"unmatched"})

    with pytest.raises(DownloadedArtifactError, match="0 audio files placed"):
        extract_downloaded_archive_detailed(
            tmp_path,
            str(archive),
            prompt_entries_reader=read_entries,
        )

    assert not (tmp_path / "02-Individual-music").exists()
