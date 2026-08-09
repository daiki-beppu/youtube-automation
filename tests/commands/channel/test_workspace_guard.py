"""``yt-workspace-guard`` CLI の境界判定契約テスト。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation import entrypoints
from youtube_automation.commands.channel import workspace_guard


def _make_channel(workspace: Path, slug: str) -> Path:
    channel = workspace / "channels" / slug
    (channel / "config" / "channel").mkdir(parents=True)
    return channel


def test_check_blocks_path_for_another_channel(tmp_path, monkeypatch, capsys):
    current = _make_channel(tmp_path, "alpha")
    _make_channel(tmp_path, "beta")
    monkeypatch.chdir(current)

    rc = workspace_guard.main(["check", "channels/beta/collections/new"])

    captured = capsys.readouterr()
    assert rc == workspace_guard.EXIT_BLOCKED
    assert captured.out == ""
    assert "channels/beta/collections/new" in captured.err
    assert "alpha" in captured.err
    assert "beta" in captured.err


def test_check_allows_path_for_current_channel(tmp_path, monkeypatch, capsys):
    current = _make_channel(tmp_path, "alpha")
    monkeypatch.chdir(current)

    assert workspace_guard.main(["check", "channels/alpha/collections/new"]) == workspace_guard.EXIT_OK
    assert capsys.readouterr().err == ""


def test_check_allows_channel_path_from_workspace_root(tmp_path, monkeypatch, capsys):
    _make_channel(tmp_path, "alpha")
    monkeypatch.chdir(tmp_path)

    assert workspace_guard.main(["check", "channels/alpha/collections/new"]) == workspace_guard.EXIT_OK
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("layout", ["collections", "config/channel", "assets", "data", "auth"])
def test_check_blocks_workspace_root_channel_layout(tmp_path, layout, monkeypatch, capsys):
    current = _make_channel(tmp_path, "alpha")
    monkeypatch.chdir(current)
    target = tmp_path / layout / "new-file"

    rc = workspace_guard.main(["check", str(target)])

    assert rc == workspace_guard.EXIT_BLOCKED
    assert str(target) in capsys.readouterr().err


def test_check_reports_every_blocked_path(tmp_path, monkeypatch, capsys):
    current = _make_channel(tmp_path, "alpha")
    _make_channel(tmp_path, "beta")
    monkeypatch.chdir(current)
    root_layout = tmp_path / "assets" / "cover.png"

    rc = workspace_guard.main(["check", "channels/beta/config/channel/meta.json", str(root_layout)])

    error = capsys.readouterr().err
    assert rc == workspace_guard.EXIT_BLOCKED
    assert "channels/beta/config/channel/meta.json" in error
    assert str(root_layout) in error


def test_check_always_allows_paths_outside_workspace(tmp_path, monkeypatch, capsys):
    (tmp_path / "config" / "channel").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    assert workspace_guard.main(["check", "collections/new", "/tmp/elsewhere"]) == workspace_guard.EXIT_OK
    assert capsys.readouterr().err == ""


def test_context_prints_workspace_channel_and_path_base(tmp_path, monkeypatch, capsys):
    channel = _make_channel(tmp_path, "alpha")
    working_dir = channel / "collections" / "planning"
    working_dir.mkdir(parents=True)
    monkeypatch.chdir(working_dir)

    assert workspace_guard.main(["context"]) == workspace_guard.EXIT_OK

    output = capsys.readouterr().out
    assert "channel=alpha" in output
    assert f"channel_dir={channel}" in output
    assert "相対パスはこの dir 基準" in output


def test_context_from_workspace_root_prints_unresolved_candidates(tmp_path, monkeypatch, capsys):
    _make_channel(tmp_path, "zeta")
    _make_channel(tmp_path, "alpha")
    monkeypatch.chdir(tmp_path)

    assert workspace_guard.main(["context"]) == workspace_guard.EXIT_OK

    output = capsys.readouterr().out
    assert "チャンネル未確定" in output
    assert "候補: alpha, zeta" in output
    assert "channels/<slug>/" in output


def test_context_in_single_channel_repo_prints_only_channel_dir(tmp_path, monkeypatch, capsys):
    (tmp_path / "config" / "channel").mkdir(parents=True)
    working_dir = tmp_path / "collections" / "planning"
    working_dir.mkdir(parents=True)
    monkeypatch.chdir(working_dir)

    assert workspace_guard.main(["context"]) == workspace_guard.EXIT_OK

    assert capsys.readouterr().out == f"channel_dir={tmp_path}\n"


def test_help_documents_check_and_path_arguments(capsys):
    with pytest.raises(SystemExit, match="0"):
        workspace_guard.main(["--help"])

    output = capsys.readouterr().out
    assert "check" in output
    assert "context" in output
    assert "path" in output
    assert "チャンネル境界" in output


def test_pyproject_registers_workspace_guard_entrypoint():
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)

    assert config["project"]["scripts"]["yt-workspace-guard"] == ("youtube_automation.entrypoints:yt_workspace_guard")
    assert callable(entrypoints.yt_workspace_guard)
