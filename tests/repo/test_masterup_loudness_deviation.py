"""Contract tests for the masterup per-track loudness deviation gate."""

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

SCRIPT = REPO_ROOT / ".claude" / "skills" / "masterup" / "references" / "check_loudness_deviation.py"
SKILL = REPO_ROOT / ".claude" / "skills" / "masterup" / "SKILL.md"


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
    music = collection / "02-Individual-music"
    music.mkdir(parents=True)
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
    distributed_script = workspace / ".claude" / "skills" / "masterup" / "references" / SCRIPT.name
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
        if line.startswith("uv run python3 ") and SCRIPT.name in line
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
