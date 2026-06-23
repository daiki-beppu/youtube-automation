"""scripts.fix_per_theme_timestamps の ffprobe argv と音声入力契約の検証.

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


def test_collect_timestamp_audio_files_accepts_mp3_m4a_wav(tmp_path) -> None:
    fix_per_theme_timestamps = _import_module()
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / "03-pattern-c-night.wav").write_bytes(b"wav")
    (music_dir / "01-pattern-a-rain.mp3").write_bytes(b"mp3")
    (music_dir / "02-pattern-b-window.m4a").write_bytes(b"m4a")
    (music_dir / "notes.txt").write_text("ignore", encoding="utf-8")

    files = fix_per_theme_timestamps.collect_timestamp_audio_files(music_dir)

    assert [p.name for p in files] == [
        "01-pattern-a-rain.mp3",
        "02-pattern-b-window.m4a",
        "03-pattern-c-night.wav",
    ]


def test_compute_pattern_starts_uses_m4a_and_wav_inputs(tmp_path, monkeypatch) -> None:
    fix_per_theme_timestamps = _import_module()
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / "01-pattern-a-rain.m4a").write_bytes(b"m4a")
    (music_dir / "02-pattern-b-window.wav").write_bytes(b"wav")

    durations = {
        "01-pattern-a-rain.m4a": 10.0,
        "02-pattern-b-window.wav": 20.0,
    }

    def fake_duration(path: Path) -> float:
        return durations[path.name]

    monkeypatch.setattr(fix_per_theme_timestamps, "get_duration", fake_duration)

    result = fix_per_theme_timestamps.compute_pattern_starts(
        music_dir,
        {"a": "Rain", "b": "Window"},
    )

    assert result == [("Rain", 0), ("Window", 7)]
