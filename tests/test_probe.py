"""utils.probe.probe_duration / probe_bitrate の挙動検証."""

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


# ---------- probe_bitrate (Issue #110) ----------


def test_probe_bitrate_returns_bps_on_success(monkeypatch) -> None:
    """Given ffprobe が format=bit_rate を 4000000 で返す
    When probe_bitrate を呼ぶ
    Then 4000000.0 (bps, float) を返す。
    """
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="4000000\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    got = probe.probe_bitrate(Path("/fake.mp4"))
    assert got == 4_000_000.0
    # 正しい ffprobe entry を要求していること
    assert "format=bit_rate" in " ".join(captured["cmd"])


def test_probe_bitrate_returns_none_when_ffprobe_missing(monkeypatch) -> None:
    """Given ffprobe バイナリ未検出
    When probe_bitrate を呼ぶ
    Then None (probe_duration と同じ fail-soft 戦略)。
    """

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("ffprobe not found")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_bitrate(Path("/fake.mp4")) is None


def test_probe_bitrate_returns_none_on_subprocess_error(monkeypatch) -> None:
    """Given ffprobe が非 0 終了
    When probe_bitrate を呼ぶ
    Then None。
    """

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_bitrate(Path("/fake.mp4")) is None


def test_probe_bitrate_returns_none_on_unparseable(monkeypatch) -> None:
    """Given ffprobe stdout が "N/A" (一部コンテナで bit_rate 未取得)
    When probe_bitrate を呼ぶ
    Then None (ValueError ハンドリング)。
    """

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="N/A\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_bitrate(Path("/fake.mp4")) is None
