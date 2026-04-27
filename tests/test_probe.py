"""utils.probe.probe_duration の挙動検証."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from youtube_automation.utils import probe


def test_returns_float_on_success(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="123.45\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_duration(Path("/fake.mp3")) == 123.45


def test_returns_none_when_ffprobe_missing(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("ffprobe not found")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_duration(Path("/fake.mp3")) is None


def test_returns_none_on_subprocess_error(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_duration(Path("/fake.mp3")) is None


def test_returns_none_on_unparseable_stdout(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="not a number\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_duration(Path("/fake.mp3")) is None
