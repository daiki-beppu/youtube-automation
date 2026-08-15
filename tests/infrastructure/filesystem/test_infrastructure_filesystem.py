"""Filesystem wrapper の観測可能な I/O 契約テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.infrastructure import filesystem


def test_path_queries_directory_listing_and_glob(tmp_path: Path) -> None:
    directory = tmp_path / "nested" / "files"
    filesystem.make_directory(directory, parents=True)
    text_file = directory / "alpha.txt"
    json_file = directory / "beta.json"
    filesystem.write_file_text(text_file, "hello")
    filesystem.write_json(json_file, {"value": "日本語"})
    symlink = directory / "alpha-link"
    symlink.symlink_to(text_file)

    assert filesystem.path_exists(text_file) is True
    assert filesystem.path_is_directory(directory) is True
    assert filesystem.path_is_file(text_file) is True
    assert filesystem.path_is_symlink(symlink) is True
    assert set(filesystem.list_directory(directory)) == {text_file, json_file, symlink}
    assert filesystem.glob_files(directory, "*.json") == [json_file]


def test_text_and_json_read_write_preserve_content_and_size(tmp_path: Path) -> None:
    text_file = tmp_path / "message.txt"
    json_file = tmp_path / "payload.json"

    filesystem.write_file_text(text_file, "café", encoding="utf-8")
    filesystem.write_json(json_file, {"items": [1, True, None], "label": "雨"})

    assert filesystem.read_file_text(text_file) == "café"
    assert filesystem.file_size(text_file) == len("café".encode())
    assert filesystem.read_json(json_file) == {"items": [1, True, None], "label": "雨"}
    assert json_file.read_bytes().endswith(b"\n")


def test_rename_remove_and_replace_update_paths_and_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    renamed = tmp_path / "renamed.txt"
    replacement = tmp_path / "replacement.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"source")
    replacement.write_bytes(b"new")
    destination.write_bytes(b"old")

    filesystem.rename_path(source, renamed)
    assert not source.exists()
    assert renamed.read_bytes() == b"source"

    filesystem.remove_file(renamed)
    assert not renamed.exists()

    filesystem.replace_file(replacement, destination)
    assert not replacement.exists()
    assert destination.read_bytes() == b"new"


def test_current_working_directory_reflects_process_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert filesystem.current_working_directory() == tmp_path


def test_verified_transaction_rolls_back_all_targets_when_verification_fails(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"old-first")
    second.write_bytes(b"old-second")

    def reject_publication() -> None:
        assert first.read_bytes() == b"new-first"
        assert second.read_bytes() == b"new-second"
        raise ValueError("verification failed")

    with pytest.raises(ValueError, match="verification failed"):
        filesystem.write_verified_text_files_transactionally(
            {first: "new-first", second: "new-second"}, reject_publication
        )

    assert first.read_bytes() == b"old-first"
    assert second.read_bytes() == b"old-second"
