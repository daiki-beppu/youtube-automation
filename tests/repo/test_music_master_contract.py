"""Behavioral contracts for merging ``/masterup`` into ``/music --master`` (#3827)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from tests.helpers.music_prompt import write_suno_prompt_pair
from tests.helpers.paths import REPO_ROOT
from youtube_automation.configuration import skills as skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
MUSIC = INVENTORY.skills_root / "music"
STATE = MUSIC / "references" / "music-chain-state.py"


def _collection(tmp_path: Path, music_engine: str) -> Path:
    channel = tmp_path / "channel"
    channel_config = channel / "config" / "channel"
    channel_config.mkdir(parents=True)
    (channel_config / "youtube.json").write_text(json.dumps({"music_engine": music_engine}), encoding="utf-8")
    collection = channel / "collections" / "planning" / "demo"
    music = collection / "02-Individual-music"
    music.mkdir(parents=True)
    for index in range(2):
        (music / f"{index:02d}.mp3").write_bytes(b"audio")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "planning": {
                    "music": {
                        "suno_playlist_url": "https://suno.com/playlist/demo",
                        "expected_file_count": 2,
                        "actual_file_count": 2,
                        "missing_file_count": 0,
                    }
                },
                "assets": {"music_downloaded": True},
            }
        ),
        encoding="utf-8",
    )
    documentation = collection / "20-documentation"
    documentation.mkdir()
    (documentation / "suno-patterns.yaml").write_text("mode: instrumental\n", encoding="utf-8")
    write_suno_prompt_pair(documentation, [{"name": "a"}])
    return collection


def _run_state(collection: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STATE), "--collection-path", str(collection), "--step", "master"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_music_exposes_master_mode_and_owns_masterup_assets() -> None:
    assert not os.path.lexists(INVENTORY.skills_root / "masterup")
    assert "--master" in INVENTORY.frontmatter("music")["description"]
    assert (MUSIC / "references/master.md").is_file()
    assert (MUSIC / "references/check_loudness_deviation.py").is_file()
    assert (MUSIC / "references/finalize_master.py").is_symlink()
    assert (MUSIC / "references/suno-fallback.md").is_file()


def test_music_chain_runs_master_after_generate() -> None:
    manifest = json.loads((MUSIC / "references/music-chain-manifest.json").read_text(encoding="utf-8"))

    assert [step["id"] for step in manifest["steps"]] == ["prompt", "lyric", "generate", "master"]
    assert manifest["steps"][-1]["skill"] == "music"


def test_master_defaults_are_owned_by_music_and_legacy_loader_remains_compatible() -> None:
    defaults = yaml.safe_load((MUSIC / "config.default.yaml").read_text(encoding="utf-8"))

    assert "master" in defaults
    assert skill_config.skill_config_default_relative_path("masterup") == Path("music/config.default.yaml")
    loaded = skill_config.load_skill_config("masterup", use_cache=False)
    assert loaded["audio"]["crossfade_duration"] == 1.0
    assert loaded["validation"]["loudness_deviation"]["max_lu"] == 2.0


def test_suno_master_runs_after_download_and_skips_after_master_exists(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "suno")

    before = _run_state(collection)
    assert before.returncode == 10
    assert json.loads(before.stdout) == {
        "step": "master",
        "engine": "suno",
        "decision": "run",
        "reason": "master_missing",
        "missing": ["01-master/master.mp3"],
    }

    master = collection / "01-master" / "master.mp3"
    master.parent.mkdir()
    master.write_bytes(b"audio")
    after = _run_state(collection)
    assert after.returncode == 0
    assert json.loads(after.stdout)["reason"] == "master_complete"


def test_suno_master_blocks_before_generate_completion(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "suno")
    (collection / "workflow-state.json").unlink()

    completed = _run_state(collection)

    assert completed.returncode == 20
    payload = json.loads(completed.stdout)
    assert payload["decision"] == "blocked"
    assert payload["reason"] == "generate_prerequisite_missing"
    assert payload["next"] == "music --generate"


def test_lyria_master_is_always_skipped_as_not_required(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "lyria")

    completed = _run_state(collection)

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "step": "master",
        "engine": "lyria",
        "decision": "skip",
        "reason": "lyria_master_not_required",
    }


def test_master_rejects_unknown_music_engine(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "unknown")

    completed = _run_state(collection)

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["decision"] == "error"
    assert "music_engine must be suno or lyria" in payload["reason"]
