"""yt-suno-audio-cleanup CLI boundary tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from youtube_automation.scripts import suno_audio_cleanup as cli


def test_plan_subcommand_passes_apply_false(monkeypatch, tmp_path):
    collection = tmp_path / "collection"
    resolved = collection.resolve()
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "resolve_collection_dir", lambda value: resolved)

    def fake_cleanup_collection(collection_dir: Path, *, apply: bool, force: bool, quiet: bool) -> int:
        captured.update(collection_dir=collection_dir, apply=apply, force=force, quiet=quiet)
        return 0

    monkeypatch.setattr(cli, "cleanup_collection", fake_cleanup_collection)

    rc = cli.main(["plan", str(collection)])

    assert rc == 0
    assert captured == {"collection_dir": resolved, "apply": False, "force": False, "quiet": False}


def test_apply_subcommand_passes_force_and_quiet(monkeypatch, tmp_path):
    collection = tmp_path / "collection"
    resolved = collection.resolve()
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "resolve_collection_dir", lambda value: resolved)

    def fake_cleanup_collection(collection_dir: Path, *, apply: bool, force: bool, quiet: bool) -> int:
        captured.update(collection_dir=collection_dir, apply=apply, force=force, quiet=quiet)
        return 0

    monkeypatch.setattr(cli, "cleanup_collection", fake_cleanup_collection)

    rc = cli.main(["apply", str(collection), "--force", "--quiet"])

    assert rc == 0
    assert captured == {"collection_dir": resolved, "apply": True, "force": True, "quiet": True}


def test_process_file_keeps_original_when_final_replace_fails(monkeypatch, tmp_path):
    """ffmpeg 成功後の最終 replace が失敗しても元音源を欠落させない。"""
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"original")
    cfg = cli.CleanupConfig(enabled=True, backup_originals=True)
    monkeypatch.setattr(cli, "probe_duration", lambda path: 120.0)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/opt/homebrew/bin/ffmpeg")

    def fake_run(cmd, *, capture_output: bool, text: bool):
        Path(cmd[-1]).write_bytes(b"cleaned")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    def fail_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(cli.os, "replace", fail_replace)

    try:
        cli.process_file(audio, cfg, apply=True, force=False, quiet=True)
    except OSError as exc:
        assert "simulated replace failure" in str(exc)
    else:
        raise AssertionError("process_file should fail")

    assert audio.read_bytes() == b"original"
    assert (audio.parent / "originals-pre-cleanup" / "track.mp3").read_bytes() == b"original"
    assert not (audio.parent / ".track.cleanup-tmp.mp3").exists()
