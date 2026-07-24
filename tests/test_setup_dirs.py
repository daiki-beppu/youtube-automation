"""yt-setup-dirs CLI の契約テスト."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from youtube_automation.cli import setup_dirs
from youtube_automation.cli.setup_directory_contract import SETUP_DIRECTORIES
from youtube_automation.infrastructure.errors import ConfigError

EXPECTED_SETUP_DIRECTORIES: tuple[str, ...] = (
    "auth",
    "branding",
    "collections",
    "data",
    "docs/channel/personas",
    "docs/benchmarks",
    "research",
)


def _assert_expected_setup_directories(root: Path) -> None:
    for rel in EXPECTED_SETUP_DIRECTORIES:
        directory = root / rel
        assert directory.is_dir(), f"missing setup directory: {rel}"
        assert (directory / ".gitkeep").is_file(), f"missing .gitkeep in {rel}"


def test_setup_directory_contract_matches_expected_directories():
    assert SETUP_DIRECTORIES == EXPECTED_SETUP_DIRECTORIES


def test_main_creates_setup_directories_with_gitkeep(tmp_path):
    rc = setup_dirs.main(["--target", str(tmp_path)])

    assert rc == 0
    _assert_expected_setup_directories(tmp_path)


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


def test_existing_gitkeep_directory_returns_domain_error_without_partial_generation(tmp_path, capsys):
    (tmp_path / "auth" / ".gitkeep").mkdir(parents=True)

    rc = setup_dirs.main(["--target", str(tmp_path)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "auth/.gitkeep は通常ファイルである必要があります" in err
    assert not (tmp_path / "collections").exists()


@pytest.mark.parametrize("target_exists", [True, False])
def test_existing_gitkeep_symlink_returns_domain_error_without_partial_generation(tmp_path, capsys, target_exists):
    outside = tmp_path / "outside-gitkeep"
    if target_exists:
        outside.write_text("external\n", encoding="utf-8")
    (tmp_path / "auth").mkdir()
    (tmp_path / "auth" / ".gitkeep").symlink_to(outside)

    rc = setup_dirs.main(["--target", str(tmp_path)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "auth/.gitkeep は通常ファイルである必要があります" in err
    if target_exists:
        assert outside.read_text(encoding="utf-8") == "external\n"
    else:
        assert not outside.exists()
    assert not (tmp_path / "collections").exists()


def test_existing_setup_directory_symlink_returns_domain_error_without_external_write(tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "auth").symlink_to(outside, target_is_directory=True)

    rc = setup_dirs.main(["--target", str(tmp_path)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "auth は symlink ではなくディレクトリである必要があります" in err
    assert not (outside / ".gitkeep").exists()
    assert not (tmp_path / "collections").exists()


def test_existing_file_at_parent_path_returns_domain_error_without_partial_generation(tmp_path, capsys):
    (tmp_path / "docs").write_text("not a directory\n", encoding="utf-8")

    rc = setup_dirs.main(["--target", str(tmp_path)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "親ディレクトリ docs はディレクトリである必要があります" in err
    assert not (tmp_path / "auth").exists()


def test_existing_parent_symlink_returns_domain_error_without_external_write(tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "docs").symlink_to(outside, target_is_directory=True)

    rc = setup_dirs.main(["--target", str(tmp_path)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "docs は symlink ではなくディレクトリである必要があります" in err
    assert not (outside / "channel" / "personas" / ".gitkeep").exists()
    assert not (tmp_path / "auth").exists()


def test_target_resolves_from_channel_dir_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))

    rc = setup_dirs.main([])

    assert rc == 0
    assert (tmp_path / "auth" / ".gitkeep").is_file()


def test_target_argument_takes_precedence_over_channel_dir_env_var(tmp_path, monkeypatch):
    env_target = tmp_path / "env"
    arg_target = tmp_path / "arg"
    env_target.mkdir()
    arg_target.mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(env_target))

    rc = setup_dirs.main(["--target", str(arg_target)])

    assert rc == 0
    _assert_expected_setup_directories(arg_target)
    assert not (env_target / "auth").exists()


def test_target_resolves_from_cwd_when_target_and_env_omitted(tmp_path, monkeypatch):
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = setup_dirs.main([])

    assert rc == 0
    _assert_expected_setup_directories(tmp_path)


def test_main_returns_error_when_channel_dir_env_missing(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "missing-env"
    monkeypatch.setenv("CHANNEL_DIR", str(missing))

    rc = setup_dirs.main([])
    err = capsys.readouterr().err

    assert rc == 1
    assert "CHANNEL_DIR で指定されたディレクトリが存在しません" in err
    assert not (missing / "auth").exists()


def test_main_returns_error_when_target_path_missing(tmp_path, capsys):
    missing = tmp_path / "missing-target"

    rc = setup_dirs.main(["--target", str(missing)])
    err = capsys.readouterr().err

    assert rc == 1
    assert "--target で指定されたディレクトリが存在しません" in err
    assert not (missing / "auth").exists()


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
