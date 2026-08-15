"""Contract tests for the music master per-track loudness deviation gate."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

SCRIPT = REPO_ROOT / ".claude" / "skills" / "music" / "references" / "check_loudness_deviation.py"
SKILL = REPO_ROOT / ".claude" / "skills" / "music" / "references" / "master.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_loudness_deviation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return _load_module()


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "collection"
    (collection / "01-master").mkdir(parents=True)
    music = collection / "02-Individual-music"
    music.mkdir()
    for name in ("01-a.mp3", "02-b.mp3", "03-c.wav"):
        (music / name).write_bytes(b"fixture")
    return collection


@pytest.mark.parametrize("nested_channel", (False, True), ids=("single-channel", "nested-channel"))
def test_documented_invocation_resolves_script_from_channel_cwd(tmp_path: Path, nested_channel: bool) -> None:
    """#3210: 配布コマンドは channel CWD を保って workspace 側 script を起動する。"""
    workspace = tmp_path / "workspace with spaces"
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    channel = workspace / "channels" / "focus" if nested_channel else workspace
    collection = channel / "collections" / "planning" / "demo"
    collection.mkdir(parents=True)
    distributed_script = workspace / ".claude" / "skills" / "music" / "references" / SCRIPT.name
    distributed_script.parent.mkdir(parents=True)
    distributed_script.write_text(
        """from pathlib import Path
import json
import sys

print(json.dumps({"cwd": str(Path.cwd()), "script": str(Path(__file__).resolve()), "collection": sys.argv[1]}))
""",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\nset -eu\ntest "$1" = run\nshift\nexec "$@"\n', encoding="utf-8")
    uv.chmod(0o755)
    documented = next(
        line
        for line in SKILL.read_text(encoding="utf-8").splitlines()
        if "uv run python3 " in line and SCRIPT.name in line
    )
    command = documented.replace("<collection-path>", shlex.quote(str(collection)))
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    completed = subprocess.run(
        command,
        shell=True,
        executable="/bin/bash",
        cwd=channel,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload == {
        "cwd": str(channel),
        "script": str(distributed_script),
        "collection": str(collection),
    }


def test_documented_invocation_reports_missing_script_as_startup_error(tmp_path: Path) -> None:
    """#3317: script 不在は逸脱 FAIL ではなく起動エラーとして exit 1 にする。"""
    workspace = tmp_path / "workspace"
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    collection = workspace / "collections" / "planning" / "demo"
    collection.mkdir(parents=True)
    documented = next(
        line
        for line in SKILL.read_text(encoding="utf-8").splitlines()
        if "uv run python3 " in line and SCRIPT.name in line
    )
    command = documented.replace("<collection-path>", shlex.quote(str(collection)))

    completed = subprocess.run(
        command,
        shell=True,
        executable="/bin/bash",
        cwd=workspace,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "ERROR:" in completed.stderr
    assert SCRIPT.name in completed.stderr


def test_parse_loudnorm_input_i_uses_ffmpeg_json(module):
    stderr = 'noise\n[Parsed_loudnorm] {\n  "input_i" : "-14.37",\n  "input_tp" : "-1.20"\n}\n'

    assert module.parse_loudnorm_input_i(stderr) == -14.37


def test_main_passes_when_all_tracks_are_within_two_lu(module, tmp_path, monkeypatch, capsys):
    collection = _collection(tmp_path)
    values = {"01-a.mp3": -14.8, "02-b.mp3": -14.0, "03-c.wav": -13.1}
    monkeypatch.setattr(module, "load_max_deviation_lu", lambda: 2.0)
    monkeypatch.setattr(module, "measure_integrated_lufs", lambda path: values[path.name])

    result = module.main([str(collection)])

    assert result == 0
    output = capsys.readouterr().out
    assert "PASS" in output
    assert "1.70 LU" in output


def test_receipt_records_one_full_scan_and_validates_without_measuring(module, tmp_path, monkeypatch, capsys):
    collection = _collection(tmp_path)
    receipt = collection / "01-master" / ".loudness-receipt.json"
    music = collection / "02-Individual-music"
    for index in range(4, 13):
        (music / f"{index:02d}-fixture.mp3").write_bytes(f"fixture-{index}".encode())
    input_names = sorted(path.name for path in music.iterdir())
    values = {name: -14.8 + index * 0.1 for index, name in enumerate(input_names)}
    measured: list[str] = []
    monkeypatch.setattr(module, "load_max_deviation_lu", lambda: 2.0)

    def measure(path: Path) -> float:
        measured.append(path.name)
        return values[path.name]

    monkeypatch.setattr(module, "measure_integrated_lufs", measure)

    assert module.main([str(collection), "--receipt", str(receipt), "--json"]) == 0
    generated = json.loads(receipt.read_text(encoding="utf-8"))
    assert measured == input_names
    assert generated["schema_version"] == 1
    assert generated["collection"] == "collection"
    assert generated["raw_master_output"] == "master.mp3"
    assert generated["full_collection_scans"] == 1
    assert generated["track_count"] == 12
    assert generated["max_deviation_lu"] == 2.0
    assert generated["status"] == "PASS"
    assert all(track["sha256"] for track in generated["tracks"])
    capsys.readouterr()

    measured.clear()
    assert module.main([str(collection), "--validate-receipt", str(receipt), "--json"]) == 0
    assert measured == []
    validated = json.loads(capsys.readouterr().out)
    assert validated["status"] == "PASS"


@pytest.mark.parametrize("receipt_case", ("missing", "corrupt", "input-mismatch", "threshold-mismatch"))
def test_receipt_validation_fails_closed(module, tmp_path, monkeypatch, capsys, receipt_case):
    collection = _collection(tmp_path)
    receipt = collection / "receipt.json"
    values = {"01-a.mp3": -14.8, "02-b.mp3": -14.0, "03-c.wav": -13.1}
    monkeypatch.setattr(module, "load_max_deviation_lu", lambda: 2.0)
    monkeypatch.setattr(module, "measure_integrated_lufs", lambda path: values[path.name])

    if receipt_case != "missing":
        assert module.main([str(collection), "--receipt", str(receipt)]) == 0
    if receipt_case == "corrupt":
        receipt.write_text("{broken", encoding="utf-8")
    elif receipt_case == "input-mismatch":
        (collection / "02-Individual-music" / "01-a.mp3").write_bytes(b"changed")
    elif receipt_case == "threshold-mismatch":
        monkeypatch.setattr(module, "load_max_deviation_lu", lambda: 1.5)

    assert module.main([str(collection), "--validate-receipt", str(receipt)]) == 1
    assert "ERROR:" in capsys.readouterr().err


def test_receipt_validation_rejects_threshold_violation(module, tmp_path, monkeypatch, capsys):
    collection = _collection(tmp_path)
    receipt = collection / "receipt.json"
    values = {"01-a.mp3": -17.0, "02-b.mp3": -14.0, "03-c.wav": -12.0}
    monkeypatch.setattr(module, "load_max_deviation_lu", lambda: 2.0)
    monkeypatch.setattr(module, "measure_integrated_lufs", lambda path: values[path.name])

    assert module.main([str(collection), "--receipt", str(receipt)]) == 2
    assert module.main([str(collection), "--validate-receipt", str(receipt)]) == 2
    assert "FAIL" in capsys.readouterr().out


def test_main_fails_and_lists_outliers_above_two_lu(module, tmp_path, monkeypatch, capsys):
    collection = _collection(tmp_path)
    values = {"01-a.mp3": -17.0, "02-b.mp3": -14.0, "03-c.wav": -12.0}
    monkeypatch.setattr(module, "load_max_deviation_lu", lambda: 2.0)
    monkeypatch.setattr(module, "measure_integrated_lufs", lambda path: values[path.name])

    result = module.main([str(collection), "--json"])

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert payload["measured_deviation_lu"] == 5.0
    assert payload["target_range_lufs"] == [-15.0, -13.0]
    assert {track["file"] for track in payload["tracks"] if track["outlier"]} == {
        "01-a.mp3",
        "03-c.wav",
    }


def test_load_max_deviation_accepts_channel_override(module, monkeypatch):
    monkeypatch.setattr(
        module,
        "load_skill_config",
        lambda _skill: {"validation": {"loudness_deviation": {"max_lu": 1.25}}},
    )

    assert module.load_max_deviation_lu() == 1.25


@pytest.mark.parametrize("value", (0, -1, True, "invalid"))
def test_load_max_deviation_rejects_invalid_values(module, monkeypatch, value):
    monkeypatch.setattr(
        module,
        "load_skill_config",
        lambda _skill: {"validation": {"loudness_deviation": {"max_lu": value}}},
    )

    with pytest.raises(module.ConfigError):
        module.load_max_deviation_lu()
