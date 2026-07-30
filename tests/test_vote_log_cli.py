"""``yt-vote-log`` CLI のテスト (#509)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.commands.collections import vote_log as cli


@pytest.fixture
def channel_dir_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    yield tmp_path


def test_parse_axis_arg_basic():
    axis = cli._parse_axis_arg("rain_window:Rain Window:124")
    assert axis.key == "rain_window"
    assert axis.label == "Rain Window"
    assert axis.votes == 124


def test_parse_axis_arg_label_with_colon():
    axis = cli._parse_axis_arg("a:Title: Sub:42")
    assert axis.key == "a"
    assert axis.label == "Title: Sub"
    assert axis.votes == 42


def test_parse_axis_arg_rejects_bad_format():
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        cli._parse_axis_arg("key:label_only")  # votes 欠落


def test_parse_axis_arg_rejects_negative_votes():
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        cli._parse_axis_arg("a:A:-1")


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (":Rain Window:1", "key が空"),
        ("rain_window::1", "label が空"),
        ("rain_window:Rain Window:not-an-int", "votes が整数ではありません"),
    ],
)
def test_parse_axis_arg_rejects_empty_fields_and_non_integer_votes(value: str, message: str):
    """REQ-2804-01: axis の空 key/label と非整数 votes を個別拒否する."""
    import argparse

    with pytest.raises(argparse.ArgumentTypeError, match=message):
        cli._parse_axis_arg(value)


def test_cli_append_then_show(channel_dir_env: Path, capsys: pytest.CaptureFixture[str]):
    rc = cli.main(
        [
            "append",
            "--week-start",
            "2026-05-04",
            "--axis",
            "rain_window:Rain Window:120",
            "--axis",
            "midnight_drive:Midnight Drive:80",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "2026-05-04" in out
    assert "rain_window" in out

    rc = cli.main(["show", "--recent", "1"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["top_axis"] == "rain_window"


def test_cli_weights_outputs_json(channel_dir_env: Path, capsys: pytest.CaptureFixture[str]):
    cli.main(
        [
            "append",
            "--week-start",
            "2026-05-04",
            "--axis",
            "rain_window:Rain Window:50",
        ]
    )
    capsys.readouterr()
    cli.main(
        [
            "append",
            "--week-start",
            "2026-05-11",
            "--axis",
            "rain_window:Rain Window:60",
        ]
    )
    capsys.readouterr()

    rc = cli.main(["weights", "--recent", "4"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["considered_weeks"] == 2
    assert payload["forced_axis"] == "rain_window"
    assert payload["forced_streak"] == 2


def test_cli_validate_when_missing_returns_error(channel_dir_env: Path, capsys: pytest.CaptureFixture[str]):
    rc = cli.main(["validate"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "見つかりません" in err or "ERROR" in err


def test_cli_append_collision_without_replace(channel_dir_env: Path, capsys: pytest.CaptureFixture[str]):
    cli.main(["append", "--week-start", "2026-05-04", "--axis", "a:A:5"])
    capsys.readouterr()
    rc = cli.main(["append", "--week-start", "2026-05-04", "--axis", "b:B:8"])
    assert rc != 0
    assert "衝突" in capsys.readouterr().err
