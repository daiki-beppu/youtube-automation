"""承認済みサムネイルの opt-in ギャラリー保存を公開 CLI 境界で検証する。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from youtube_automation.utils import thumbnail_archive
from youtube_automation.utils.exceptions import ValidationError


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / ".claude" / "skills" / "thumbnail" / "references" / "archive-approved-thumbnail.py"


def _channel(tmp_path: Path, *, archive_enabled: object | None = None) -> Path:
    channel = tmp_path / "channel"
    (channel / "config" / "skills").mkdir(parents=True)
    if archive_enabled is not None:
        config = {"archive": {"enabled": archive_enabled}}
        (channel / "config" / "skills" / "thumbnail.yaml").write_text(
            yaml.safe_dump(config),
            encoding="utf-8",
        )
    return channel


def _collection(channel: Path, name: str, *, extension: str = "jpg", content: bytes = b"approved") -> Path:
    collection = channel / "collections" / "planning" / name
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    (assets / f"thumbnail.{extension}").write_bytes(content)
    return collection


def _run(channel: Path, collection: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CHANNEL_DIR"] = str(channel)
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(_script_path()), str(collection)],
        cwd=_repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_default_disabled_does_not_create_gallery(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    collection = _collection(channel, "20260717-tst-default")

    result = _run(channel, collection)

    assert result.returncode == 0
    assert "disabled" in result.stdout
    assert not (channel / "assets" / "thumbnail-gallery").exists()


def test_enabled_copies_jpg_without_changing_source(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-jpg", content=b"jpeg-original-bytes")
    source = collection / "10-assets" / "thumbnail.jpg"

    result = _run(channel, collection)

    archived = channel / "assets" / "thumbnail-gallery" / "20260717-tst-jpg.jpg"
    assert result.returncode == 0
    assert str(archived) in result.stdout
    assert archived.read_bytes() == b"jpeg-original-bytes"
    assert source.read_bytes() == b"jpeg-original-bytes"


def test_enabled_preserves_png_extension_and_bytes(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-png", extension="png", content=b"png-original-bytes")

    result = _run(channel, collection)

    archived = channel / "assets" / "thumbnail-gallery" / "20260717-tst-png.png"
    assert result.returncode == 0
    assert archived.read_bytes() == b"png-original-bytes"
    assert not archived.with_suffix(".jpg").exists()


def test_enabled_accumulates_distinct_collections(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    first = _collection(channel, "20260717-tst-first", content=b"first")
    second = _collection(channel, "20260717-tst-second", content=b"second")

    first_result = _run(channel, first)
    second_result = _run(channel, second)

    gallery = channel / "assets" / "thumbnail-gallery"
    assert first_result.returncode == 0
    assert second_result.returncode == 0
    assert (gallery / "20260717-tst-first.jpg").read_bytes() == b"first"
    assert (gallery / "20260717-tst-second.jpg").read_bytes() == b"second"


def test_reapproval_replaces_same_collection_archive(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-reapproval", content=b"first-approval")
    source = collection / "10-assets" / "thumbnail.jpg"

    first_result = _run(channel, collection)
    source.write_bytes(b"second-approval")
    second_result = _run(channel, collection)

    archived = channel / "assets" / "thumbnail-gallery" / "20260717-tst-reapproval.jpg"
    assert first_result.returncode == 0
    assert second_result.returncode == 0
    assert archived.read_bytes() == b"second-approval"


def test_reapproval_with_new_extension_removes_stale_archive(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-new-extension", extension="png", content=b"first-png")

    first_result = _run(channel, collection)
    (collection / "10-assets" / "thumbnail.png").unlink()
    (collection / "10-assets" / "thumbnail.jpg").write_bytes(b"second-jpg")
    second_result = _run(channel, collection)

    gallery = channel / "assets" / "thumbnail-gallery"
    assert first_result.returncode == 0
    assert second_result.returncode == 0
    assert (gallery / "20260717-tst-new-extension.jpg").read_bytes() == b"second-jpg"
    assert not (gallery / "20260717-tst-new-extension.png").exists()


def test_reapproval_extension_cleanup_failure_preserves_previous_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(
        channel,
        "20260717-tst-cleanup-failure",
        extension="png",
        content=b"first-png",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel))
    thumbnail_archive.archive_approved_thumbnail(collection)
    source = collection / "10-assets" / "thumbnail.png"
    source.unlink()
    source.with_suffix(".jpg").write_bytes(b"second-jpg")
    gallery = channel / "assets" / "thumbnail-gallery"
    previous_archive = gallery / "20260717-tst-cleanup-failure.png"
    new_archive = previous_archive.with_suffix(".jpg")
    real_unlink = Path.unlink

    def fail_previous_archive_unlink(path: Path, **kwargs) -> None:
        if path == previous_archive:
            raise OSError("forced stale archive cleanup failure")
        real_unlink(path, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_previous_archive_unlink)

    with pytest.raises(ValidationError, match="forced stale archive cleanup failure"):
        thumbnail_archive.archive_approved_thumbnail(collection)

    assert previous_archive.read_bytes() == b"first-png"
    assert not new_archive.exists()
    assert list(gallery.glob(".20260717-tst-cleanup-failure-*")) == []


def test_archive_snapshot_read_failure_is_validation_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-snapshot-failure", content=b"first")
    monkeypatch.setenv("CHANNEL_DIR", str(channel))
    thumbnail_archive.archive_approved_thumbnail(collection)
    archived = channel / "assets" / "thumbnail-gallery" / "20260717-tst-snapshot-failure.jpg"
    real_read_bytes = Path.read_bytes

    def fail_archive_read(path: Path) -> bytes:
        if path == archived:
            raise OSError("forced archive snapshot failure")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_archive_read)

    with pytest.raises(ValidationError, match="forced archive snapshot failure"):
        thumbnail_archive.archive_approved_thumbnail(collection)


def test_temporary_cleanup_failure_is_validation_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-temp-cleanup", content=b"approved")
    monkeypatch.setenv("CHANNEL_DIR", str(channel))
    real_unlink = Path.unlink
    temporary_path = None

    def fail_copy(_source, destination):
        nonlocal temporary_path
        temporary_path = Path(destination)
        raise OSError("forced copy failure")

    def fail_temporary_unlink(path: Path, **kwargs) -> None:
        if path == temporary_path:
            raise OSError("forced temporary cleanup failure")
        real_unlink(path, **kwargs)

    monkeypatch.setattr(thumbnail_archive.shutil, "copyfile", fail_copy)
    monkeypatch.setattr(Path, "unlink", fail_temporary_unlink)

    with pytest.raises(ValidationError, match="forced temporary cleanup failure"):
        thumbnail_archive.archive_approved_thumbnail(collection)

    assert temporary_path is not None
    real_unlink(temporary_path)


def test_temporary_cleanup_and_rollback_failures_are_aggregated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-combined-cleanup", content=b"approved")
    monkeypatch.setenv("CHANNEL_DIR", str(channel))
    gallery = channel / "assets" / "thumbnail-gallery"
    archive_target = gallery / "20260717-tst-combined-cleanup.jpg"
    real_unlink = Path.unlink
    real_rmdir = Path.rmdir
    temporary_path = None

    def fail_copy(_source, destination):
        nonlocal temporary_path
        temporary_path = Path(destination)
        raise OSError("forced copy failure")

    def fail_temporary_unlink(path: Path, **kwargs) -> None:
        if path == temporary_path:
            raise OSError("forced temporary cleanup failure")
        if path == archive_target:
            raise OSError("forced archive rollback failure")
        real_unlink(path, **kwargs)

    monkeypatch.setattr(thumbnail_archive.shutil, "copyfile", fail_copy)
    monkeypatch.setattr(Path, "unlink", fail_temporary_unlink)

    with pytest.raises(ValidationError) as error:
        thumbnail_archive.archive_approved_thumbnail(collection)

    message = str(error.value)
    assert "forced copy failure" in message
    assert "forced temporary cleanup failure" in message
    assert "forced archive rollback failure" in message
    assert temporary_path is not None
    real_unlink(temporary_path)
    real_rmdir(gallery)
    real_rmdir(gallery.parent)


def test_non_boolean_enabled_fails_without_gallery(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled="true")
    collection = _collection(channel, "20260717-tst-invalid-config")

    result = _run(channel, collection)

    assert result.returncode == 1
    assert "archive.enabled は boolean" in result.stderr
    assert not (channel / "assets" / "thumbnail-gallery").exists()


def test_non_mapping_archive_config_fails_without_gallery(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    config_path = channel / "config" / "skills" / "thumbnail.yaml"
    config_path.write_text(yaml.safe_dump({"archive": []}), encoding="utf-8")
    collection = _collection(channel, "20260717-tst-invalid-archive")

    result = _run(channel, collection)

    assert result.returncode == 1
    assert "thumbnail.archive は mapping" in result.stderr
    assert not (channel / "assets" / "thumbnail-gallery").exists()


def test_enabled_missing_thumbnail_fails_without_gallery(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = channel / "collections" / "planning" / "20260717-tst-missing"
    (collection / "10-assets").mkdir(parents=True)

    result = _run(channel, collection)

    assert result.returncode == 1
    assert "確定済みサムネイル" in result.stderr
    assert not (channel / "assets" / "thumbnail-gallery").exists()


def test_enabled_rejects_collection_outside_channel(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    outside_collection = tmp_path / "outside-collection"
    assets = outside_collection / "10-assets"
    assets.mkdir(parents=True)
    (assets / "thumbnail.jpg").write_bytes(b"outside")

    result = _run(channel, outside_collection)

    assert result.returncode == 1
    assert "CHANNEL_DIR 配下" in result.stderr
    assert not (channel / "assets" / "thumbnail-gallery").exists()


def test_enabled_rejects_thumbnail_symlink_without_gallery(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = channel / "collections" / "planning" / "20260717-tst-source-link"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    try:
        (assets / "thumbnail.jpg").symlink_to(outside)
    except OSError as exc:
        import pytest

        pytest.skip(f"symlink creation is unavailable: {exc}")

    result = _run(channel, collection)

    assert result.returncode == 1
    assert "シンボリックリンク" in result.stderr
    assert not (channel / "assets" / "thumbnail-gallery").exists()
    assert outside.read_bytes() == b"outside"


def test_enabled_rejects_assets_directory_symlink_without_gallery(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = channel / "collections" / "planning" / "20260717-tst-assets-link"
    collection.mkdir(parents=True)
    outside = tmp_path / "outside-assets"
    outside.mkdir()
    (outside / "thumbnail.jpg").write_bytes(b"outside")
    try:
        (collection / "10-assets").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    result = _run(channel, collection)

    assert result.returncode == 1
    assert "10-assets" in result.stderr
    assert "シンボリックリンク" in result.stderr
    assert not (channel / "assets" / "thumbnail-gallery").exists()
    assert (outside / "thumbnail.jpg").read_bytes() == b"outside"


def test_enabled_rejects_gallery_symlink_without_writing_outside(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-gallery-link")
    outside = tmp_path / "outside-gallery"
    outside.mkdir()
    gallery = channel / "assets" / "thumbnail-gallery"
    gallery.parent.mkdir(parents=True)
    try:
        gallery.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        import pytest

        pytest.skip(f"symlink creation is unavailable: {exc}")

    result = _run(channel, collection)

    assert result.returncode == 1
    assert "シンボリックリンク" in result.stderr
    assert list(outside.iterdir()) == []


def test_destination_write_failure_is_nonzero_and_cleans_temporary_file(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    collection = _collection(channel, "20260717-tst-copy-failure", content=b"approved")
    gallery = channel / "assets" / "thumbnail-gallery"
    target = gallery / "20260717-tst-copy-failure.jpg"
    target.mkdir(parents=True)

    result = _run(channel, collection)

    assert result.returncode == 1
    assert "アーカイブできません" in result.stderr
    assert target.is_dir()
    assert list(gallery.glob(".20260717-tst-copy-failure-*")) == []
    assert (collection / "10-assets" / "thumbnail.jpg").read_bytes() == b"approved"


def test_invalid_collection_is_input_error(tmp_path: Path) -> None:
    channel = _channel(tmp_path, archive_enabled=True)
    missing = channel / "collections" / "planning" / "missing"

    result = _run(channel, missing)

    assert result.returncode == 2
    assert "コレクションディレクトリではありません" in result.stderr
    assert not (channel / "assets" / "thumbnail-gallery").exists()
