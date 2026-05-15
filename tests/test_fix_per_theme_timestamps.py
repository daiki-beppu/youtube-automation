"""scripts.fix_per_theme_timestamps の ffprobe argv 構成検証.

Issue #186: `get_duration` の ffprobe argv に `"--"` sentinel が含まれている
ことを検証する。Issue #167 で `utils/probe.py` に導入した argv-injection
defense-in-depth を `fix_per_theme_timestamps.py` へ横展開した
リグレッションガード。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _import_module():
    """`fix_per_theme_timestamps` は import 時に `channel_dir()` を評価する。
    `set_channel_dir` autouse fixture が `CHANNEL_DIR` を設定したあとで
    遅延 import することで、collection 時の `ConfigError` を回避する。
    """
    from youtube_automation.scripts import fix_per_theme_timestamps

    return fix_per_theme_timestamps


def test_get_duration_places_sentinel_before_path(monkeypatch) -> None:
    fix_per_theme_timestamps = _import_module()
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="123.45\n", returncode=0)

    monkeypatch.setattr(fix_per_theme_timestamps.subprocess, "run", fake_run)

    fix_per_theme_timestamps.get_duration(Path("/fake.mp3"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp3"


def test_get_duration_keeps_sentinel_for_dash_prefixed_path(monkeypatch) -> None:
    fix_per_theme_timestamps = _import_module()
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="123.45\n", returncode=0)

    monkeypatch.setattr(fix_per_theme_timestamps.subprocess, "run", fake_run)

    fix_per_theme_timestamps.get_duration(Path("-evil.mp3"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "-evil.mp3"
