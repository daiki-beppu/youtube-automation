"""generate_suno_prompts CLI の挙動テスト."""

from __future__ import annotations

import sys

import pytest

from youtube_automation.scripts.generate_suno_prompts import main


def test_help_flag_shows_usage_and_exits_zero(monkeypatch, capsys):
    """--help は argparse の usage を表示して exit 0 する."""
    monkeypatch.setattr(sys, "argv", ["yt-generate-suno", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()
