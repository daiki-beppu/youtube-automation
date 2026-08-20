from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from youtube_automation.commands.media import check_raw_master, master_adjust
from youtube_automation.commands.media.master_adjust import adjust_master, build_filter
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media.audio_adjustments import replace_master_adjustments
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths


def _settings(*, gain: float = -2.0) -> dict[str, object]:
    return {
        "eq": {
            "enabled": True,
            "muddiness_freq_hz": 350,
            "muddiness_gain_db": gain,
            "harshness_freq_hz": 8000,
            "harshness_gain_db": -1.5,
        },
        "loudnorm": {"enabled": True, "I": -14.0, "LRA": 11.0, "TP": -1.5},
        "limiter": {"enabled": True, "limit": 0.95},
    }


def _collection(tmp_path: Path, *, with_master: bool = True) -> Path:
    collection = tmp_path / "20260820-clm-master-adjust"
    (collection / "01-master").mkdir(parents=True)
    (collection / "20-documentation").mkdir()
    if with_master:
        (collection / "01-master/master.mp3").write_bytes(b"original-master")
    return collection


def _prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(master_adjust.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(master_adjust, "load_skill_config", lambda *_args, **_kwargs: {"audio": {"bitrate": "256k"}})


def test_build_filter_contains_eq_loudnorm_then_limiter() -> None:
    expression = build_filter(_settings(gain=-4.0))

    assert expression.split(",") == [
        "equalizer=f=350:t=q:w=1:g=-4",
        "equalizer=f=8000:t=q:w=1:g=-1.5",
        "loudnorm=I=-14:LRA=11:TP=-1.5",
        "alimiter=limit=0.95",
    ]


def test_adjust_master_reuses_original_backup_on_every_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    paths = CollectionPaths(collection)
    paths.workflow_state_path.write_text(
        json.dumps(
            {
                "collection_name": collection.name,
                "updated_at": "2026-08-20T00:00:00.000Z",
                "phase": "prepared",
                "assets": {"raw_master": "master.mp3", "master_audio": None},
            }
        ),
        encoding="utf-8",
    )
    replace_master_adjustments(paths.audio_adjustments_path, _settings())
    _prepare(monkeypatch)
    inputs: list[bytes] = []
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        source = Path(command[3])
        inputs.append(source.read_bytes())
        Path(command[-1]).write_bytes(f"adjusted-{len(inputs)}".encode())
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(master_adjust.subprocess, "run", fake_run)

    assert adjust_master(collection, quiet=True) == paths.master_audio_path
    replace_master_adjustments(paths.audio_adjustments_path, _settings(gain=-6.0))
    assert adjust_master(collection, quiet=True) == paths.master_audio_path

    assert inputs == [b"original-master", b"original-master"]
    assert Path(commands[0][3]) == paths.master_audio_path
    assert Path(commands[1][3]) == paths.master_adjustment_backup_path
    assert paths.master_adjustment_backup_path.read_bytes() == b"original-master"
    assert paths.master_audio_path.read_bytes() == b"adjusted-2"
    assert commands[0][-3:-1] == ["-b:a", "256k"]
    assert check_raw_master.check_raw_master(collection).is_consistent


def test_adjust_master_ffmpeg_failure_preserves_master_and_creates_no_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    paths = CollectionPaths(collection)
    replace_master_adjustments(paths.audio_adjustments_path, _settings())
    _prepare(monkeypatch)
    monkeypatch.setattr(
        master_adjust.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", "decode failed"),
    )

    with pytest.raises(ValidationError, match="ffmpeg"):
        adjust_master(collection, quiet=True)

    assert paths.master_audio_path.read_bytes() == b"original-master"
    assert not paths.master_adjustment_backup_path.exists()
    assert not paths.master_audio_path.with_name("master.tmp.mp3").exists()


def test_adjust_master_replace_failure_rolls_back_first_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    paths = CollectionPaths(collection)
    replace_master_adjustments(paths.audio_adjustments_path, _settings())
    _prepare(monkeypatch)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"adjusted")
        return subprocess.CompletedProcess(command, 0, "", "")

    real_replace = master_adjust.os.replace
    replacement_attempts = 0

    def fail_output_replace(source: Path, destination: Path) -> None:
        nonlocal replacement_attempts
        if source == paths.master_audio_path.with_name("master.tmp.mp3"):
            replacement_attempts += 1
            raise OSError("simulated replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(master_adjust.subprocess, "run", fake_run)
    monkeypatch.setattr(master_adjust.os, "replace", fail_output_replace)

    with pytest.raises(ValidationError, match="置換できません"):
        adjust_master(collection, quiet=True)

    assert replacement_attempts == 1
    assert paths.master_audio_path.read_bytes() == b"original-master"
    assert not paths.master_adjustment_backup_path.exists()
    assert not paths.master_audio_path.with_name("master.tmp.mp3").exists()


def test_adjust_master_rejects_backup_directory_symlink_outside_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    paths = CollectionPaths(collection)
    replace_master_adjustments(paths.audio_adjustments_path, _settings())
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        paths.master_adjustment_backup_path.parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink is unavailable")
    _prepare(monkeypatch)

    with pytest.raises(ValidationError, match="collection 外"):
        adjust_master(collection, quiet=True)

    assert paths.master_audio_path.read_bytes() == b"original-master"
    assert not (outside / "master.mp3").exists()


@pytest.mark.parametrize("missing", ["master", "settings"])
def test_adjust_master_requires_master_and_saved_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    collection = _collection(tmp_path, with_master=missing != "master")
    paths = CollectionPaths(collection)
    if missing != "settings":
        replace_master_adjustments(paths.audio_adjustments_path, _settings())
    _prepare(monkeypatch)

    with pytest.raises(ValidationError):
        adjust_master(collection, quiet=True)


def test_cli_returns_nonzero_for_missing_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _collection(tmp_path, with_master=False)

    assert master_adjust.main([str(collection), "--quiet"]) == 1
