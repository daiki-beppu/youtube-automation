"""yt-setup-dirs CLI の契約テスト."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from youtube_automation.cli import setup_dirs
from youtube_automation.cli.channel_init_templates import SETUP_DIRECTORIES
from youtube_automation.utils.exceptions import ConfigError


def test_main_creates_setup_directories_with_gitkeep(tmp_path):
    rc = setup_dirs.main(["--target", str(tmp_path)])

    assert rc == 0
    for rel in SETUP_DIRECTORIES:
        directory = tmp_path / rel
        assert directory.is_dir(), f"missing setup directory: {rel}"
        assert (directory / ".gitkeep").is_file(), f"missing .gitkeep in {rel}"


def test_main_does_not_generate_channel_config_or_channel_init_files(tmp_path):
    rc = setup_dirs.main(["--target", str(tmp_path)])

    assert rc == 0
    assert not (tmp_path / "config" / "channel").exists()
    assert not (tmp_path / "config" / "localizations.json").exists()
    assert not (tmp_path / "config" / "schedule_config.json").exists()
    assert not (tmp_path / "config" / "skills").exists()
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / ".gitignore").exists()
    assert not (tmp_path / "auth" / "client_secrets.template.json").exists()


def test_main_is_idempotent_and_skips_existing_directories(tmp_path, capsys):
    assert setup_dirs.main(["--target", str(tmp_path)]) == 0
    capsys.readouterr()

    rc = setup_dirs.main(["--target", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "skipped" in out
    assert "created" not in out


def test_main_adds_gitkeep_when_directory_already_exists(tmp_path):
    (tmp_path / "auth").mkdir()

    rc = setup_dirs.main(["--target", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "auth" / ".gitkeep").is_file()


def test_existing_file_at_setup_directory_path_returns_domain_error(tmp_path, capsys):
    (tmp_path / "auth").write_text("not a directory\n", encoding="utf-8")

    rc = setup_dirs.main(["--target", str(tmp_path)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "auth はディレクトリである必要があります" in err
    assert not (tmp_path / "collections").exists()


def test_existing_file_at_parent_path_returns_domain_error_without_partial_generation(tmp_path, capsys):
    (tmp_path / "docs").write_text("not a directory\n", encoding="utf-8")

    rc = setup_dirs.main(["--target", str(tmp_path)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "親ディレクトリ docs はディレクトリである必要があります" in err
    assert not (tmp_path / "auth").exists()


def test_target_resolves_from_channel_dir_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))

    rc = setup_dirs.main([])

    assert rc == 0
    assert (tmp_path / "auth" / ".gitkeep").is_file()


def test_resolve_target_dir_raises_when_channel_dir_env_missing(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setenv("CHANNEL_DIR", str(missing))

    with pytest.raises(ConfigError):
        setup_dirs._resolve_target_dir(None)


def test_pyproject_registers_yt_setup_dirs_entry_point():
    root = Path(__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    scripts = data["project"]["scripts"]

    assert scripts["yt-setup-dirs"] == "youtube_automation.cli_entrypoints:yt_setup_dirs"
