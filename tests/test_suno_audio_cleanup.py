"""Suno audio cleanup CLI helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from youtube_automation.scripts import suno_audio_cleanup as mod
from youtube_automation.scripts.suno_audio_cleanup import (
    CleanupConfig,
    build_filter,
    cleanup_collection,
    collect_audio_files,
    process_file,
    resolve_cleanup_config,
)
from youtube_automation.utils.exceptions import ConfigError


def _make_collection(tmp_path: Path, names: list[str]) -> Path:
    collection = tmp_path / "collection"
    music = collection / "02-Individual-music"
    music.mkdir(parents=True)
    for name in names:
        (music / name).write_bytes(b"audio")
    return collection


def test_resolve_cleanup_config_defaults_disabled() -> None:
    cfg = resolve_cleanup_config({})
    assert cfg.enabled is False
    assert cfg.target_lufs == -14.0
    assert cfg.backup_originals is True


def test_resolve_cleanup_config_accepts_overrides() -> None:
    cfg = resolve_cleanup_config(
        {
            "audio": {"bitrate": "256k"},
            "post_processing": {
                "suno_audio_cleanup": {
                    "enabled": True,
                    "loudnorm": {"I": -16, "TP": -2},
                    "eq": {"muddiness_gain_db": -3},
                }
            },
        }
    )
    assert cfg.enabled is True
    assert cfg.bitrate == "256k"
    assert cfg.target_lufs == -16.0
    assert cfg.true_peak == -2.0
    assert cfg.muddiness_gain_db == -3.0


def test_resolve_cleanup_config_rejects_bad_shape() -> None:
    with pytest.raises(ConfigError):
        resolve_cleanup_config({"post_processing": {"suno_audio_cleanup": "yes"}})


def test_build_filter_contains_expected_ffmpeg_steps() -> None:
    filt = build_filter(CleanupConfig(enabled=True), duration_sec=120)
    assert "silenceremove" in filt
    assert "equalizer=f=350" in filt
    assert "equalizer=f=8000" in filt
    assert "dynaudnorm" in filt
    assert "alimiter=limit=0.95" in filt
    assert "loudnorm=I=-14" in filt
    assert "afade=t=out:st=117:d=3" in filt


def test_collect_audio_files_uses_supported_extensions(tmp_path: Path) -> None:
    collection = _make_collection(tmp_path, ["02-b.wav", "01-a.mp3", "note.txt"])
    files = collect_audio_files(collection)
    assert [p.name for p in files] == ["01-a.mp3", "02-b.wav"]


def test_cleanup_collection_disabled_is_noop(tmp_path: Path, monkeypatch, capsys) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    monkeypatch.setattr(mod, "load_skill_config", lambda _skill: {})
    rc = cleanup_collection(collection, apply=False)
    assert rc == 0
    assert "enabled=false" in capsys.readouterr().out


def test_process_file_apply_backs_up_original_and_replaces(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    changed = process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    backup = collection / "02-Individual-music" / "originals-pre-cleanup" / "01-a.mp3"
    assert changed is True
    assert backup.read_bytes() == b"audio"
    assert source.read_bytes() == b"cleaned"


@pytest.mark.parametrize(
    ("filename", "expected_codec"),
    [("01-a.m4a", "aac"), ("01-a.wav", "pcm_s16le")],
)
def test_process_file_apply_uses_container_matching_codec(
    tmp_path: Path,
    monkeypatch,
    filename: str,
    expected_codec: str,
) -> None:
    collection = _make_collection(tmp_path, [filename])
    source = collection / "02-Individual-music" / filename
    captured_cmd: list[str] = []

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        captured_cmd.extend(cmd)
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    changed = process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    assert changed is True
    assert source.read_bytes() == b"cleaned"
    assert captured_cmd[captured_cmd.index("-c:a") + 1] == expected_codec


def test_process_file_apply_without_backup_preserves_original_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    def fail_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(mod.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        process_file(
            source,
            CleanupConfig(enabled=True, backup_originals=False),
            apply=True,
            force=False,
            quiet=True,
        )

    assert source.read_bytes() == b"audio"
    assert not (source.parent / ".01-a.cleanup-tmp.mp3").exists()


def test_process_file_apply_with_backup_restores_original_when_final_replace_fails(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"
    tmp_output = source.parent / ".01-a.cleanup-tmp.mp3"
    backup = collection / "02-Individual-music" / "originals-pre-cleanup" / "01-a.mp3"

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    real_replace = mod.os.replace

    def fail_final_replace(src, dst):
        if Path(src) == tmp_output and Path(dst) == source:
            raise OSError("final replace failed")
        real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", fail_final_replace)

    with pytest.raises(OSError, match="final replace failed"):
        process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    assert source.read_bytes() == b"audio"
    assert not backup.exists()
    assert not tmp_output.exists()


def test_process_file_skips_when_backup_exists(tmp_path: Path) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"
    backup = collection / "02-Individual-music" / "originals-pre-cleanup" / "01-a.mp3"
    backup.parent.mkdir()
    backup.write_bytes(b"old")

    changed = process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    assert changed is False
    assert source.read_bytes() == b"audio"
