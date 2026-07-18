"""``yt-channel list`` CLI の契約テスト."""

from __future__ import annotations

import tomllib
from pathlib import Path

from youtube_automation import cli_entrypoints
from youtube_automation.cli import channel
from youtube_automation.utils.config import loader


def _make_channel(workspace: Path, slug: str) -> Path:
    config_dir = workspace / "channels" / slug / "config" / "channel"
    config_dir.mkdir(parents=True)
    return config_dir.parents[1]


def test_list_prints_valid_slugs_one_per_line_in_stable_order(tmp_path, monkeypatch, capsys):
    _make_channel(tmp_path, "zeta")
    _make_channel(tmp_path, "alpha")
    (tmp_path / "channels" / "not-a-channel").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    rc = channel.main(["list"])

    captured = capsys.readouterr()
    assert rc == channel.EXIT_OK
    assert captured.out == "alpha\nzeta\n"
    assert captured.err == ""


def test_list_from_channel_descendant_finds_workspace(tmp_path, monkeypatch, capsys):
    channel_dir = _make_channel(tmp_path, "ambient")
    working_dir = channel_dir / "collections" / "planning"
    working_dir.mkdir(parents=True)
    monkeypatch.chdir(working_dir)

    assert channel.main(["list"]) == channel.EXIT_OK
    assert capsys.readouterr().out == "ambient\n"


def test_empty_workspace_has_distinct_exit_code_and_actionable_error(tmp_path, monkeypatch, capsys):
    (tmp_path / "channels").mkdir()
    monkeypatch.chdir(tmp_path)

    rc = channel.main(["list"])

    captured = capsys.readouterr()
    assert rc == channel.EXIT_EMPTY_WORKSPACE
    assert captured.out == ""
    assert "channel がありません" in captured.err
    assert "channels/<slug>/config/channel/" in captured.err


def test_outside_workspace_has_distinct_exit_code_and_actionable_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    rc = channel.main(["list"])

    captured = capsys.readouterr()
    assert rc == channel.EXIT_OUTSIDE_WORKSPACE
    assert captured.out == ""
    assert "workspace が見つかりません" in captured.err
    assert "channels/<slug>/config/channel/" in captured.err


def test_unreadable_channel_directory_has_distinct_exit_code(tmp_path, monkeypatch, capsys):
    _make_channel(tmp_path, "ambient")
    monkeypatch.chdir(tmp_path)

    def unreadable(_workspace_root: Path) -> None:
        raise PermissionError("channels/ambient: permission denied")

    monkeypatch.setattr(channel, "_assert_channel_directories_readable", unreadable)

    rc = channel.main(["list"])

    captured = capsys.readouterr()
    assert rc == channel.EXIT_UNREADABLE
    assert captured.out == ""
    assert "読み取れません" in captured.err
    assert "権限" in captured.err


def test_list_does_not_switch_config_singleton(tmp_path, monkeypatch, capsys):
    _make_channel(tmp_path, "ambient")
    monkeypatch.chdir(tmp_path)
    sentinel_instance = object()
    sentinel_dir = tmp_path / "already-selected"
    monkeypatch.setattr(loader, "_instance", sentinel_instance)
    monkeypatch.setattr(loader, "_channel_dir", sentinel_dir)

    assert channel.main(["list"]) == channel.EXIT_OK
    capsys.readouterr()
    assert loader._instance is sentinel_instance
    assert loader._channel_dir == sentinel_dir


def test_help_documents_discovery_and_output_format(capsys):
    try:
        channel.main(["list", "--help"])
    except SystemExit as error:
        assert error.code == 0

    output = capsys.readouterr().out
    assert "channels/<slug>/config/channel/" in output
    assert "1 行 1 件" in output
    assert "祖先" in output


def test_pyproject_registers_yt_channel_entrypoint():
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)

    assert config["project"]["scripts"]["yt-channel"] == "youtube_automation.cli_entrypoints:yt_channel"


def test_entrypoint_does_not_consume_common_channel_selection_option():
    assert "youtube_automation.cli.channel" in cli_entrypoints._CHANNEL_OPTION_CONFLICTS
