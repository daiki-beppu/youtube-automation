"""utils.veo_generator の ffprobe argv 構成検証.

Issue #186: `trim_tail` / `smooth_loop` の duration 取得 argv に `"--"` sentinel が
含まれていることを検証する。Issue #167 で `utils/probe.py` に導入した
argv-injection defense-in-depth を `veo_generator.py` へ横展開した
リグレッションガード。
"""

from __future__ import annotations

from pathlib import Path

from youtube_automation.utils import veo_generator


def _install_capture(monkeypatch) -> dict:
    """`subprocess.check_output` を fake 化し、cmd を捕捉して即座に
    `ValueError` を発生させる。`trim_tail` / `smooth_loop` は
    `Exception` 全般を catch して `False` を返すため、これで
    argv 検証だけに絞った最小テストになる。
    """
    captured: dict = {}

    def fake_check_output(cmd, **kwargs):
        captured["cmd"] = cmd
        # float() で ValueError を発生させ、関数を早期 False で抜けさせる。
        return "not-a-number"

    monkeypatch.setattr(veo_generator.subprocess, "check_output", fake_check_output)
    return captured


# ---------- trim_tail ----------


def test_trim_tail_places_sentinel_before_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.trim_tail(Path("/fake.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp4"


def test_trim_tail_keeps_sentinel_for_dash_prefixed_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.trim_tail(Path("-evil.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "-evil.mp4"


# ---------- smooth_loop ----------


def test_smooth_loop_places_sentinel_before_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.smooth_loop(Path("/fake.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp4"


def test_smooth_loop_keeps_sentinel_for_dash_prefixed_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.smooth_loop(Path("-evil.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "-evil.mp4"
