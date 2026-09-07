from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from youtube_automation.commands.channel import channel_export
from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.analytics.channel_registry import ChannelRegistryUpdate


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(channel_export, "DEFAULT_CHANNEL_REGISTRY", tmp_path / "registry/channels.json")


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    source = workspace / "channels" / "demo"
    config = source / "config" / "channel"
    config.mkdir(parents=True)
    (config / "meta.json").write_text(
        json.dumps(
            {
                "channel": {
                    "name": "Demo",
                    "short": "demo",
                    "youtube_handle": "@demo",
                    "url": "https://youtube.com/@demo",
                    "tagline": "Demo",
                }
            }
        ),
        encoding="utf-8",
    )
    (config / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "ambient", "style": "calm", "context": "focus"},
                "tags": {"base": [], "themes": {}},
                "descriptions": {"opening": "x", "perfect_for": [], "hashtags": []},
                "title": {"template": "{theme}"},
            }
        ),
        encoding="utf-8",
    )
    (config / "youtube.json").write_text(
        json.dumps({"youtube": {"category_id": "10", "privacy_status": "private", "language": "ja"}}), encoding="utf-8"
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    return workspace, source


def test_export_copies_full_disk_image_and_materializes_internal_symlink(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    media = source / "media/song.mp3"
    media.parent.mkdir()
    media.write_bytes(b"audio")
    (source / "song-link.mp3").symlink_to(media)
    (workspace / ".git/info/exclude").write_text("channels/demo/media/\nchannels/demo/song-link.mp3\n")
    destination = tmp_path / "exported"

    assert channel_export.export_channel("demo", destination, workspace=workspace) == channel_export.EXIT_OK
    assert (destination / "media/song.mp3").read_bytes() == b"audio"
    assert (destination / "song-link.mp3").read_bytes() == b"audio"
    assert not (destination / "song-link.mp3").is_symlink()


def test_export_refuses_dirty_source_unless_allowed(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    (source / "dirty.txt").write_text("dirty", encoding="utf-8")

    assert channel_export.export_channel("demo", tmp_path / "blocked", workspace=workspace) == channel_export.EXIT_USAGE
    assert (
        channel_export.export_channel("demo", tmp_path / "allowed", workspace=workspace, allow_dirty=True)
        == channel_export.EXIT_OK
    )


def test_export_copies_auth_excludes_runtime_files_and_writes_templates(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    (source / "auth").mkdir()
    (source / "auth/token.json").write_text("secret", encoding="utf-8")
    (source / ".env").write_text("SECRET=value", encoding="utf-8")
    (source / ".tmp").mkdir()
    (source / ".tmp/partial").write_text("x", encoding="utf-8")
    destination = tmp_path / "exported"

    assert (
        channel_export.export_channel("demo", destination, workspace=workspace, allow_dirty=True)
        == channel_export.EXIT_OK
    )
    assert (destination / "auth/token.json").read_text(encoding="utf-8") == "secret"
    assert not (destination / ".env").exists()
    assert not (destination / ".tmp").exists()
    assert (destination / ".gitignore").is_file()
    assert (destination / "auth/client_secrets.template.json").is_file()


def test_export_refuses_nonempty_destination_and_dry_run_writes_nothing(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("keep", encoding="utf-8")
    assert channel_export.export_channel("demo", occupied, workspace=workspace) == channel_export.EXIT_CONFLICT
    destination = tmp_path / "dry-run"
    assert (
        channel_export.export_channel("demo", destination, workspace=workspace, dry_run=True) == channel_export.EXIT_OK
    )
    assert not destination.exists()


@pytest.mark.parametrize("error_type", [ConfigError, OSError, ValueError])
def test_export_validation_failure_rolls_back_without_touching_source(tmp_path: Path, monkeypatch, error_type) -> None:
    workspace, source = _workspace(tmp_path)
    before = subprocess.run(
        ["git", "status", "--porcelain"], cwd=workspace, check=True, capture_output=True, text=True
    ).stdout
    monkeypatch.setattr(
        channel_export, "_validate_config", lambda _path: (_ for _ in ()).throw(error_type("bad config"))
    )
    destination = tmp_path / "exported"
    assert channel_export.export_channel("demo", destination, workspace=workspace) == channel_export.EXIT_VALIDATION
    assert not destination.exists()
    assert not list(tmp_path.glob(".channel-export-*"))
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=workspace, check=True, capture_output=True, text=True
        ).stdout
        == before
    )
    assert source.exists()


@pytest.mark.parametrize("slug", ["../escape", "UPPER", "two words", "", ".hidden"])
def test_export_rejects_invalid_slug(tmp_path: Path, slug: str) -> None:
    workspace, _ = _workspace(tmp_path)
    destination = tmp_path / "exported"

    assert channel_export.export_channel(slug, destination, workspace=workspace) == channel_export.EXIT_USAGE
    assert not destination.exists()


def test_export_missing_required_config_rolls_back_with_missing_name(tmp_path: Path, capsys) -> None:
    workspace, source = _workspace(tmp_path)
    (source / "config/channel/content.json").unlink()
    destination = tmp_path / "exported"

    assert (
        channel_export.export_channel("demo", destination, workspace=workspace, allow_dirty=True)
        == channel_export.EXIT_VALIDATION
    )
    assert not destination.exists()
    assert not list(tmp_path.glob(".channel-export-*"))
    captured = capsys.readouterr().err
    assert "必須 config が不足しています" in captured
    assert "content.json" in captured


def test_export_config_load_error_rolls_back(tmp_path: Path, capsys) -> None:
    workspace, source = _workspace(tmp_path)
    (source / "config/channel/content.json").write_text("{}", encoding="utf-8")
    destination = tmp_path / "exported"

    assert (
        channel_export.export_channel("demo", destination, workspace=workspace, allow_dirty=True)
        == channel_export.EXIT_VALIDATION
    )
    assert not destination.exists()
    assert not list(tmp_path.glob(".channel-export-*"))
    assert "必須キー" in capsys.readouterr().err


def test_workspace_root_prefers_detected_workspace(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)

    assert channel_export._workspace_root(source / "config") == workspace.resolve()


def test_workspace_root_falls_back_to_channels_directory_ancestor(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "channels").mkdir(parents=True)
    nested = workspace / "channels" / "empty" / "deep"
    nested.mkdir(parents=True)

    assert channel_export._workspace_root(nested) == workspace.resolve()


def test_workspace_root_falls_back_to_start_without_channels_directory(tmp_path: Path) -> None:
    start = tmp_path / "no-workspace"
    start.mkdir()

    assert channel_export._workspace_root(start) == start.resolve()


def test_initial_commit_excludes_copied_secrets_and_media(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    ignored = ["auth/client_secrets.json", "auth/token.json", "auth/backups/old-token.json"]
    audio = ("mp3", "m4a", "wav", "flac", "aac", "ogg")
    media = (*audio, "mp4", "mov", "webm", "mkv", "png", "jpg", "jpeg", "webp", "gif", "zip")
    ignored.extend(f"collections/live/demo/10-assets/file.{suffix}" for suffix in media)
    ignored.extend(f"assets/stock/demo/file.{suffix}" for suffix in audio)
    tracked = "collections/live/demo/workflow-state.json"
    for relative in [*ignored, tracked]:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    destination = tmp_path / "exported"
    assert channel_export.export_channel("demo", destination, workspace=workspace, allow_dirty=True) == 0
    for relative in ignored:
        assert (destination / relative).is_file()
    subprocess.run(["git", "init", "-b", "main"], cwd=destination, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=destination, check=True)
    staged = subprocess.run(
        ["git", "ls-files", "-z"], cwd=destination, check=True, capture_output=True, text=True
    ).stdout.split("\0")
    assert not set(ignored).intersection(staged)
    assert tracked in staged
    assert "auth/client_secrets.template.json" in staged


def test_export_cli_finds_workspace_from_channel_subdirectory(tmp_path: Path, monkeypatch) -> None:
    _, source = _workspace(tmp_path)
    monkeypatch.chdir(source / "config")
    destination = tmp_path / "exported"
    assert channel_export.main(["demo", str(destination), "--dry-run"]) == 0
    assert not destination.exists()


def test_export_replaces_workspace_registry_entry_and_dry_run_only_reports_plan(tmp_path: Path, capsys) -> None:
    workspace, source = _workspace(tmp_path)
    other = tmp_path / "other"
    destination = tmp_path / "exported"
    registry = tmp_path / "channels.json"
    registry.write_text(json.dumps([str(other), str(source)]), encoding="utf-8")

    assert (
        channel_export.export_channel("demo", destination, workspace=workspace, registry=registry, dry_run=True)
        == channel_export.EXIT_OK
    )
    assert json.loads(registry.read_text(encoding="utf-8")) == [str(other), str(source)]
    assert "registry plan: replace index=1" in capsys.readouterr().out

    assert channel_export.export_channel("demo", destination, workspace=workspace, registry=registry) == 0
    assert json.loads(registry.read_text(encoding="utf-8")) == [str(other), str(destination)]


def test_registry_write_failure_keeps_export_and_prints_manual_document(tmp_path: Path, monkeypatch, capsys) -> None:
    workspace, _ = _workspace(tmp_path)
    destination = tmp_path / "exported"
    registry = tmp_path / "channels.json"

    def fail_write(_update) -> None:
        raise OSError("read only")

    monkeypatch.setattr(ChannelRegistryUpdate, "write", fail_write)
    assert (
        channel_export.export_channel("demo", destination, workspace=workspace, registry=registry)
        == channel_export.EXIT_VALIDATION
    )
    assert destination.is_dir()
    captured = capsys.readouterr()
    assert "手動更新" in captured.out
    assert str(destination) in captured.out
