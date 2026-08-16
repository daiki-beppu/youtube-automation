"""utils.probe.probe_duration / probe_bitrate の挙動検証."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.commands.media import generate_master
from youtube_automation.core.errors import ValidationError
from youtube_automation.infrastructure.media import probe


def test_returns_float_on_success(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="123.45\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_duration(Path("/fake.mp3")) == 123.45
    assert captured["kwargs"]["timeout"] == probe.DEFAULT_FFPROBE_TIMEOUT_SECONDS


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


def test_returns_none_on_timeout(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_duration(Path("/fake.mp3")) is None


def test_returns_none_on_unparseable_stdout(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="not a number\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe.probe_duration(Path("/fake.mp3")) is None


@pytest.mark.parametrize("stdout", ["nan\n", "inf\n", "-inf\n"])
def test_probe_duration_returns_none_on_non_finite_stdout(monkeypatch, stdout) -> None:
    monkeypatch.setattr(probe.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout=stdout))

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
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="4000000\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    got = probe.probe_bitrate(Path("/fake.mp4"))
    assert got == 4_000_000.0
    # 正しい ffprobe entry を要求していること
    assert "format=bit_rate" in " ".join(captured["cmd"])
    assert captured["kwargs"]["timeout"] == probe.DEFAULT_FFPROBE_TIMEOUT_SECONDS


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


def test_probe_bitrate_returns_none_on_timeout(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get("timeout"))

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


@pytest.mark.parametrize("stdout", ["nan\n", "inf\n", "-inf\n"])
def test_probe_bitrate_returns_none_on_non_finite_stdout(monkeypatch, stdout) -> None:
    monkeypatch.setattr(probe.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout=stdout))

    assert probe.probe_bitrate(Path("/fake.mp4")) is None


def test_probe_video_reads_duration_resolution_and_codec(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=('{"format":{"duration":"20.5"},"streams":[{"codec_name":"h264","width":1920,"height":1080}]}')
        ),
    )

    assert probe.probe_video(tmp_path / "video.mp4") == probe.VideoProbe(20.5, 1920, 1080, "h264")


def test_probe_video_rejects_invalid_shape(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout='{"streams":[]}'),
    )

    assert probe.probe_video(tmp_path / "video.mp4") is None


def test_generate_master_rejects_non_finite_track_duration(monkeypatch) -> None:
    monkeypatch.setattr(probe.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="nan\n"))
    monkeypatch.setattr(generate_master, "probe_duration", probe.probe_duration)

    with pytest.raises(ValidationError, match="probe に失敗"):
        generate_master._sum_track_duration([Path("/fake.mp3")])


# ---------- argv-injection defense (Issue #167): "--" sentinel ----------


def test_probe_duration_places_sentinel_before_path(monkeypatch) -> None:
    """Given probe_duration が呼ばれる
    When ffprobe argv が組み立てられる
    Then path 引数の直前に "--" sentinel が置かれる (`-` 始まりパスの
    オプション誤解釈を遮断する argv-injection defense)。
    """
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="1.0\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    probe.probe_duration(Path("/fake.mp3"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp3"


def test_probe_bitrate_places_sentinel_before_path(monkeypatch) -> None:
    """Given probe_bitrate が呼ばれる
    When ffprobe argv が組み立てられる
    Then path 引数の直前に "--" sentinel が置かれる。
    """
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="4000000\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    probe.probe_bitrate(Path("/fake.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp4"


def test_probe_duration_keeps_sentinel_for_dash_prefixed_path(monkeypatch) -> None:
    """Given path が `-` で始まる adversarial input ("-evil.mp3")
    When probe_duration を呼ぶ
    Then "--" sentinel が path の直前に保たれ、ffprobe が path をオプションと
    解釈する余地がない (argv-injection defense の意図を adversarial input で固定)。
    """
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="1.0\n")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    probe.probe_duration(Path("-evil.mp3"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "-evil.mp3"
