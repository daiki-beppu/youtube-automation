"""yt-suno-verify CLI 配線の契約テスト."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from tests.helpers.suno_verify import load_suno_verify_module


def test_pyproject_registers_yt_suno_verify_script():
    """Given pyproject.toml
    When project.scripts を読む
    Then yt-suno-verify が集約 entrypoint に登録されている。
    """
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["scripts"].get("yt-suno-verify") == ("youtube_automation.cli_entrypoints:yt_suno_verify")


def test_cli_entrypoint_routes_to_suno_verify_module(monkeypatch):
    """Given cli_entrypoints の yt_suno_verify
    When console script wrapper を呼ぶ
    Then suno_verify module の main へ委譲する。
    """
    from youtube_automation import cli_entrypoints

    seen: dict[str, str] = {}

    def fake_run(module_path: str, function_name: str = "main") -> str:
        seen["module_path"] = module_path
        seen["function_name"] = function_name
        return "called"

    monkeypatch.setattr(cli_entrypoints, "_run", fake_run)

    assert cli_entrypoints.yt_suno_verify() == "called"
    assert seen == {
        "module_path": "youtube_automation.scripts.suno_verify",
        "function_name": "main",
    }


def test_help_flag_shows_usage_and_exits_zero(monkeypatch, capsys):
    """Given --help
    When yt-suno-verify を起動する
    Then usage を表示して exit 0 する。
    """
    module = load_suno_verify_module()
    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()
