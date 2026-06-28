"""yt-suno-audio-cleanup CLI boundary tests."""

from __future__ import annotations

from pathlib import Path

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
