"""``yt-channel-import`` のコピー・検証・rollback 契約テスト。"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from youtube_automation import cli_entrypoints
from youtube_automation.cli import channel_import


def _write_source(root: Path, *, handle: str = "@ambient-island") -> Path:
    source = root / "legacy-channel"
    sections = {
        "meta.json": {
            "channel": {
                "name": "Ambient Island",
                "short": "AI",
                "youtube_handle": handle,
                "url": f"https://youtube.com/{handle}",
                "tagline": "quiet",
            }
        },
        "content.json": {
            "genre": {"primary": "ambient", "style": "soft", "context": "focus"},
            "tags": {"base": ["ambient"], "themes": {}},
            "descriptions": {"opening": "quiet", "perfect_for": ["focus"], "hashtags": ["#ambient"]},
            "title": {"template": "{theme}"},
        },
        "youtube.json": {"youtube": {"category_id": "10", "privacy_status": "private", "language": "en"}},
    }
    for name, data in sections.items():
        path = source / "config" / "channel" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    for relative in (
        "auth/token.json",
        "auth/client_secrets.json",
        "data/analytics.json",
        "collections/planning/demo/workflow-state.json",
        "assets/stock/track.mp3",
        "branding/logo.png",
        "research/notes.md",
        "docs/channel/positioning.md",
        "docs/benchmarks/summary.md",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "source", encoding="utf-8")
    (source / ".claude" / "skills").mkdir(parents=True)
    (source / ".claude" / "skills" / "must-not-copy.md").write_text("shared", encoding="utf-8")
    return source


def test_import_copies_only_per_channel_paths_and_leaves_source_untouched(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    before = (source / "config" / "channel" / "meta.json").read_bytes()

    rc = channel_import.main([str(source), "--slug", "ambient-island"])

    target = workspace / "channels" / "ambient-island"
    assert rc == channel_import.EXIT_OK
    for relative in (
        "config/channel/meta.json",
        "auth/token.json",
        "data/analytics.json",
        "collections/planning/demo/workflow-state.json",
        "assets/stock/track.mp3",
        "branding/logo.png",
        "research/notes.md",
        "docs/channel/positioning.md",
        "docs/benchmarks/summary.md",
    ):
        assert (target / relative).is_file()
    assert not (target / ".claude").exists()
    assert (source / "config" / "channel" / "meta.json").read_bytes() == before
    assert (source / "assets" / "stock" / "track.mp3").is_file()
    output = capsys.readouterr().out
    assert "config load: OK" in output
    assert "yt-skills sync" in output


def test_import_scaffolds_workspace_gitignore_media_policy(tmp_path, monkeypatch):
    source = _write_source(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    assert channel_import.main([str(source), "--slug", "ambient-island"]) == channel_import.EXIT_OK

    ignore = (workspace / ".gitignore").read_text(encoding="utf-8")
    assert "channels/*/collections/**/*.mp3" in ignore
    assert "channels/*/collections/**/*.mp4" in ignore
    assert "channels/*/collections/**/*.png" in ignore
    assert "channels/*/assets/stock/**/*.mp3" in ignore
    assert "channels/*/auth/token*.json" in ignore


def test_existing_gitignore_is_appended_without_losing_content(tmp_path, monkeypatch):
    source = _write_source(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("custom-rule\n", encoding="utf-8")
    monkeypatch.chdir(workspace)

    assert channel_import.main([str(source), "--slug", "ambient-island"]) == channel_import.EXIT_OK

    ignore = (workspace / ".gitignore").read_text(encoding="utf-8")
    assert ignore.startswith("custom-rule\n")
    assert ignore.count(channel_import.GITIGNORE_MARKER) == 1


def test_slug_is_proposed_from_meta_handle_and_requires_confirmation(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    assert channel_import.main([str(source)]) == channel_import.EXIT_OK
    assert (workspace / "channels" / "ambient-island").is_dir()
    assert "ambient-island" in capsys.readouterr().out


def test_declined_slug_does_not_create_workspace_files(tmp_path, monkeypatch):
    source = _write_source(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    assert channel_import.main([str(source)]) == channel_import.EXIT_USAGE
    assert not (workspace / "channels").exists()
    assert not (workspace / ".gitignore").exists()


@pytest.mark.parametrize("slug", ["../escape", "UPPER", "two words", "", ".hidden"])
def test_invalid_explicit_slug_is_rejected(tmp_path, monkeypatch, slug):
    source = _write_source(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    assert channel_import.main([str(source), "--slug", slug]) == channel_import.EXIT_USAGE
    assert not (workspace / "channels").exists()


def test_invalid_config_rolls_back_target(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    (source / "config" / "channel" / "content.json").unlink()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    rc = channel_import.main([str(source), "--slug", "ambient-island"])

    assert rc == channel_import.EXIT_VALIDATION
    assert not (workspace / "channels" / "ambient-island").exists()
    assert "content.json" in capsys.readouterr().err


def test_config_load_error_is_reported_and_rolled_back(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    (source / "config" / "channel" / "content.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    rc = channel_import.main([str(source), "--slug", "ambient-island"])

    assert rc == channel_import.EXIT_VALIDATION
    assert not (workspace / "channels" / "ambient-island").exists()
    assert "必須キー" in capsys.readouterr().err


def test_existing_target_is_never_overwritten(tmp_path, monkeypatch):
    source = _write_source(tmp_path)
    workspace = tmp_path / "workspace"
    existing = workspace / "channels" / "ambient-island"
    existing.mkdir(parents=True)
    marker = existing / "owned.txt"
    marker.write_text("keep", encoding="utf-8")
    monkeypatch.chdir(workspace)

    assert channel_import.main([str(source), "--slug", "ambient-island"]) == channel_import.EXIT_CONFLICT
    assert marker.read_text(encoding="utf-8") == "keep"


def test_source_env_and_channel_dir_residue_are_warned_but_not_copied(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    (source / ".env").write_text(f"CHANNEL_DIR={source}\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("CHANNEL_DIR", str(source))

    assert channel_import.main([str(source), "--slug", "ambient-island"]) == channel_import.EXIT_OK

    captured = capsys.readouterr()
    assert ".env" in captured.err
    assert "CHANNEL_DIR" in captured.err
    assert not (workspace / "channels" / "ambient-island" / ".env").exists()


def test_symlink_in_copy_tree_is_rejected_and_rolled_back(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    external = tmp_path / "external-secret"
    external.write_text("secret", encoding="utf-8")
    (source / "data" / "linked.json").symlink_to(external)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    assert channel_import.main([str(source), "--slug", "ambient-island"]) == channel_import.EXIT_VALIDATION
    assert not (workspace / "channels" / "ambient-island").exists()
    assert "symlink" in capsys.readouterr().err


def test_symlinked_parent_of_selected_path_is_rejected(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    shutil_docs = source / "docs"
    external_docs = tmp_path / "external-docs"
    shutil_docs.rename(external_docs)
    shutil_docs.symlink_to(external_docs, target_is_directory=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    assert channel_import.main([str(source), "--slug", "ambient-island"]) == channel_import.EXIT_VALIDATION
    assert not (workspace / "channels" / "ambient-island").exists()
    assert "symlink" in capsys.readouterr().err


def test_symlinked_workspace_channels_directory_is_rejected(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external-channels"
    external.mkdir()
    (workspace / "channels").symlink_to(external, target_is_directory=True)
    monkeypatch.chdir(workspace)

    assert channel_import.main([str(source), "--slug", "ambient-island"]) == channel_import.EXIT_VALIDATION
    assert not (external / "ambient-island").exists()
    assert "symlink" in capsys.readouterr().err


def test_running_from_inside_source_is_rejected_to_keep_source_untouched(tmp_path, monkeypatch, capsys):
    source = _write_source(tmp_path)
    monkeypatch.chdir(source)

    assert channel_import.main([str(source), "--slug", "ambient-island"]) == channel_import.EXIT_USAGE
    assert not (source / "channels").exists()
    assert not (source / ".gitignore").exists()
    assert "workspace" in capsys.readouterr().err


def test_entrypoint_is_registered_and_does_not_consume_channel_selection():
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)

    assert config["project"]["scripts"]["yt-channel-import"] == "youtube_automation.cli_entrypoints:yt_channel_import"
    assert "youtube_automation.cli.channel_import" in cli_entrypoints._CHANNEL_OPTION_CONFLICTS
