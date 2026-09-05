from __future__ import annotations

import json
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
