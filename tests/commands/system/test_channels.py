from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from youtube_automation.commands.system.channels import main


def _write_channel(path: Path, source: str, *, git: bool = True) -> None:
    path.mkdir(parents=True)
    if git:
        (path / ".git").mkdir()
    (path / "pyproject.toml").write_text(source, encoding="utf-8")


def _registry(path: Path, channels: list[Path]) -> Path:
    path.write_text(json.dumps([str(channel) for channel in channels]), encoding="utf-8")
    return path


def test_list_classifies_entries_in_registry_order(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    eligible = tmp_path / "eligible"
    workspace = tmp_path / "workspace" / "channels" / "ambient"
    missing = tmp_path / "missing"
    _write_channel(
        eligible,
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        '[tool.uv.sources]\nyoutube-channels-automation={git="https://github.com/daiki-beppu/youtube-automation", '
        'tag="v5.6.0"}\n',
    )
    _write_channel(workspace, '[project]\nname="channel"\n', git=False)
    registry = _registry(tmp_path / "channels.json", [workspace, missing, eligible])

    assert main(["list", "--registry", str(registry)]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[:3] == [
        f"{workspace}\tworkspace\tnone",
        f"{missing}\tmissing\tnone",
        f"{eligible}\teligible\ttag v5.6.0",
    ]
    assert lines[3] == "total=3 eligible=1 workspace=1 missing=1"


def test_list_json_reports_pin_kinds_and_same_summary(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    main_channel = tmp_path / "main"
    sha_channel = tmp_path / "sha"
    sha = "a" * 40
    _write_channel(
        main_channel,
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        '[tool.uv.sources]\nyoutube-channels-automation={git="https://github.com/daiki-beppu/youtube-automation", '
        'branch="main"}\n',
    )
    _write_channel(
        sha_channel,
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        '[tool.uv.sources]\nyoutube-channels-automation={git="https://github.com/daiki-beppu/youtube-automation", '
        f'rev="{sha}"}}\n',
    )
    registry = _registry(tmp_path / "channels.json", [main_channel, sha_channel])

    assert main(["list", "--registry", str(registry), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "channels": [
            {"path": str(main_channel), "status": "eligible", "pin": "main"},
            {"path": str(sha_channel), "status": "eligible", "pin": f"sha {sha[:12]}"},
        ],
        "summary": {"total": 2, "eligible": 2, "workspace": 0, "missing": 0},
    }


def test_list_missing_is_success_and_invalid_registry_is_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    registry = _registry(tmp_path / "channels.json", [tmp_path / "missing"])
    assert main(["list", "--registry", str(registry)]) == 0

    registry.write_text("not json", encoding="utf-8")
    assert main(["list", "--registry", str(registry)]) == 2
    assert "channel registry" in capsys.readouterr().err


def test_list_does_not_depend_on_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    registry = _registry(tmp_path / "channels.json", [tmp_path / "missing"])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert main(["list", "--registry", str(registry), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["missing"] == 1


def _tag_channel(path: Path) -> None:
    _write_channel(
        path,
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        '[tool.uv.sources]\nyoutube-channels-automation={git="https://github.com/daiki-beppu/youtube-automation", '
        'tag="v5.6.0"}\n',
    )


def test_update_is_serial_self_last_and_isolates_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    first, failed, current = (tmp_path / name for name in ("first", "failed", "current"))
    for channel in (first, failed, current):
        _tag_channel(channel)
    registry = _registry(tmp_path / "channels.json", [current, first, failed])
    calls: list[tuple[Path, list[str]]] = []

    def fake_run(command, *, cwd, **kwargs):
        calls.append((cwd, command))
        code = 1 if cwd == failed and "yt-automation-update" in command else 0
        stdout = "error detail" if code else "移行対象はありません"
        return subprocess.CompletedProcess(command, code, stdout, "")

    monkeypatch.chdir(current)
    monkeypatch.setattr("youtube_automation.commands.system.channels.subprocess.run", fake_run)

    assert main(["update", "--registry", str(registry), "--tag", "v5.7.0"]) == 1
    apply_calls = [(cwd, command) for cwd, command in calls if "yt-automation-update" in command]
    assert [cwd for cwd, _ in apply_calls] == [first, failed, current]
    assert all(command[-3:] == ["--tag", "v5.7.0", "--accept-hooks"] for _, command in apply_calls)
    assert "failed=1" in capsys.readouterr().out


def test_update_respects_pin_kind_and_reports_followups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    tag = tmp_path / "tag"
    main_pin = tmp_path / "main"
    sha_pin = tmp_path / "sha"
    _tag_channel(tag)
    _write_channel(
        main_pin,
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        "[tool.uv.sources]\nyoutube-channels-automation="
        '{git="https://github.com/daiki-beppu/youtube-automation", branch="main"}\n',
    )
    _write_channel(
        sha_pin,
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        '[tool.uv.sources]\nyoutube-channels-automation={git="https://github.com/daiki-beppu/youtube-automation", rev="'
        + "a" * 40
        + '"}\n',
    )
    registry = _registry(tmp_path / "channels.json", [main_pin, sha_pin, tag])
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, **kwargs):
        commands.append(command)
        if "yt-automation-update" in command:
            return subprocess.CompletedProcess(command, 0, "Claude Code を再起動", "")
        if "migrate-config" in command:
            return subprocess.CompletedProcess(command, 0, "dry-run 完了: 1 ファイル（変更なし）", "")
        return subprocess.CompletedProcess(command, 1, "stale 1 document pair(s)", "")

    monkeypatch.setattr("youtube_automation.commands.system.channels.subprocess.run", fake_run)
    assert main(["update", "--registry", str(registry), "--tag", "v5.7.0"]) == 0
    output = capsys.readouterr().out
    assert "main pin（--tag は tag pin 専用）" in output
    assert "sha pin（--tag は tag pin 専用）" in output
    assert "要 migrate, 要 render, Claude Code 再起動" not in output
    assert "Claude Code 再起動, 要 migrate, 要 render" in output
    assert sum("yt-automation-update" in command for command in commands) == 1


def test_update_dry_run_and_passthrough_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel = tmp_path / "tag"
    _tag_channel(channel)
    registry = _registry(tmp_path / "channels.json", [channel])
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("youtube_automation.commands.system.channels.subprocess.run", fake_run)
    assert main(["update", "--registry", str(registry), "--tag", "v5.7.0", "--dry-run"]) == 0
    assert commands == [["uv", "run", "yt-automation-update", "check", "--tag", "v5.7.0"]]

    commands.clear()
    assert (
        main(
            [
                "update",
                "--registry",
                str(registry),
                "--tag",
                "v5.7.0",
                "--no-commit",
                "--force-sync",
                "--allow-dirty",
                "--no-accept-hooks",
            ]
        )
        == 0
    )
    assert commands[0] == [
        "uv",
        "run",
        "yt-automation-update",
        "apply",
        "--tag",
        "v5.7.0",
        "--force-sync",
        "--allow-dirty",
    ]
    assert not any("push" in command or "pull" in command for command in commands)


def test_update_without_tag_only_updates_main_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main_pin = tmp_path / "main"
    tag_pin = tmp_path / "tag"
    _write_channel(
        main_pin,
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        "[tool.uv.sources]\nyoutube-channels-automation="
        '{git="https://github.com/daiki-beppu/youtube-automation", branch="main"}\n',
    )
    _tag_channel(tag_pin)
    registry = _registry(tmp_path / "channels.json", [tag_pin, main_pin])
    calls: list[tuple[Path, list[str]]] = []

    def fake_run(command, *, cwd, **kwargs):
        calls.append((cwd, command))
        return subprocess.CompletedProcess(command, 0, "移行対象はありません", "")

    monkeypatch.setattr("youtube_automation.commands.system.channels.subprocess.run", fake_run)
    assert main(["update", "--registry", str(registry)]) == 0
    apply_calls = [(cwd, command) for cwd, command in calls if "yt-automation-update" in command]
    assert apply_calls == [(main_pin, ["uv", "run", "yt-automation-update", "apply", "--commit", "--accept-hooks"])]
