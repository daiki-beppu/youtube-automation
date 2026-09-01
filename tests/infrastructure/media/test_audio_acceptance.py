from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.infrastructure.media.audio_acceptance import (
    FFmpegAudioInspector,
    parse_loudnorm_input_i,
)


def test_parse_loudnorm_input_i_reads_last_ffmpeg_json_object() -> None:
    stderr = 'banner\n{"input_i":"-20.0"}\nnoise\n{"input_i":"-14.25","input_tp":"-1.0"}\n'

    assert parse_loudnorm_input_i(stderr) == -14.25


def test_inspector_returns_duration_and_loudness_from_local_tools(monkeypatch, tmp_path: Path) -> None:
    track = tmp_path / "track.mp3"
    track.write_bytes(b"fixture")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout="180.5\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr='{"input_i":"-14.25"}')

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = FFmpegAudioInspector().inspect(track)

    assert result.duration_seconds == 180.5
    assert result.integrated_lufs == -14.25
    assert [call[0] for call in calls] == ["ffprobe", "ffmpeg"]


def test_inspector_decodes_tool_output_as_utf8_with_replacement(monkeypatch, tmp_path: Path) -> None:
    track = tmp_path / "日本語.mp3"
    track.write_bytes(b"fixture")
    run_kwargs = []

    def fake_run(command, **kwargs):
        run_kwargs.append(kwargs)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout="180.5\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr='{"input_i":"-14.25"}')

    monkeypatch.setattr(subprocess, "run", fake_run)

    FFmpegAudioInspector().inspect(track)

    assert all(kwargs["encoding"] == "utf-8" for kwargs in run_kwargs)
    assert all(kwargs["errors"] == "replace" for kwargs in run_kwargs)


def test_inspector_rejects_unreadable_duration(monkeypatch, tmp_path: Path) -> None:
    track = tmp_path / "track.mp3"
    track.write_bytes(b"fixture")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="invalid media"),
    )

    with pytest.raises(ValidationError, match="track.mp3"):
        FFmpegAudioInspector().inspect(track)


def test_inspector_rejects_symlinked_audio_without_running_tools(monkeypatch, tmp_path: Path) -> None:
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"fixture")
    track = tmp_path / "track.mp3"
    track.symlink_to(outside)
    called = False

    def fake_run(command, **kwargs):
        nonlocal called
        called = True
        return subprocess.CompletedProcess(command, 0, stdout="180", stderr='{"input_i":"-14"}')

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ValidationError, match="通常ファイル"):
        FFmpegAudioInspector().inspect(track)
    assert called is False
