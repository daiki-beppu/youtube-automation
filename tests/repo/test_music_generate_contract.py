"""Contracts for merging Suno Helper and Lyria into ``/music --generate`` (#3826)."""

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
SKILL_DIR = INVENTORY.skills_root / "music"
STATE = SKILL_DIR / "references" / "music-chain-state.py"


def _collection(tmp_path: Path, music_engine: str) -> Path:
    channel = tmp_path / "channel"
    channel_config = channel / "config" / "channel"
    channel_config.mkdir(parents=True)
    (channel_config / "youtube.json").write_text(json.dumps({"music_engine": music_engine}), encoding="utf-8")
    collection = channel / "collections" / "planning" / "demo"
    documentation = collection / "20-documentation"
    documentation.mkdir(parents=True)
    (documentation / "suno-patterns.yaml").write_text("mode: instrumental\n", encoding="utf-8")
    write_suno_prompt_pair(documentation, [{"name": "a"}, {"name": "b"}])
    return collection


def _run_state(collection: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STATE), "--collection-path", str(collection), "--step", "generate"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_music_exposes_generate_mode_and_removes_old_skills() -> None:
    assert not os.path.lexists(INVENTORY.skills_root / "suno-helper")
    assert not os.path.lexists(INVENTORY.skills_root / "lyria")

    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "--generate" in INVENTORY.frontmatter("music")["description"]
    assert "| `--generate` | `references/generate.md` |" in skill
    assert "extension/references/serve.md" in skill
    assert len(skill.splitlines()) <= 400


def test_generate_reference_routes_by_music_engine_and_keeps_completion_contracts() -> None:
    generate = (SKILL_DIR / "references" / "generate.md").read_text(encoding="utf-8")

    assert "music_engine" in generate
    assert "suno" in generate and "lyria" in generate and "minimax" in generate
    assert "entry 数 × 2" in generate
    assert "assets.music_downloaded = true" in generate
    assert "suno_playlist_url" in generate
    assert "01-master/master.mp3" in generate
    assert "extension/references/serve.md" in generate
    assert "`/suno-helper`" not in generate
    assert "`/lyria`" not in generate


def test_music_chain_adds_generate_after_lyric() -> None:
    manifest = json.loads((SKILL_DIR / "references/music-chain-manifest.json").read_text(encoding="utf-8"))

    assert [step["id"] for step in manifest["steps"]] == ["prompt", "lyric", "generate", "master"]
    assert manifest["steps"][2]["skill"] == "music"


def test_generate_defaults_are_owned_by_music_and_legacy_loaders_remain_compatible() -> None:
    defaults = yaml.safe_load((SKILL_DIR / "config.default.yaml").read_text(encoding="utf-8"))

    assert set(defaults) == {"prompt", "lyric", "generate", "master"}
    assert set(defaults["generate"]) == {"suno", "lyria", "minimax"}
    assert skill_config.skill_config_default_relative_path("suno-helper") == Path("music/config.default.yaml")
    assert skill_config.skill_config_default_relative_path("lyria") == Path("music/config.default.yaml")
    assert skill_config.load_skill_config("suno-helper", use_cache=False)["unattended"]["max_entries"] == 10
    assert skill_config.load_skill_config("lyria", use_cache=False)["model"] == "lyria-3-pro-preview"


def test_generate_state_routes_suno_and_requires_strict_completion(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "suno")

    before = _run_state(collection)
    assert before.returncode == 10
    assert json.loads(before.stdout)["engine"] == "suno"

    music_dir = collection / "02-Individual-music"
    music_dir.mkdir()
    for index in range(4):
        (music_dir / f"{index:02d}.mp3").write_bytes(b"audio")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "planning": {
                    "music": {
                        "suno_playlist_url": "https://suno.com/playlist/demo",
                        "expected_file_count": 4,
                        "actual_file_count": 4,
                        "missing_file_count": 0,
                    }
                },
                "assets": {"music_downloaded": True},
            }
        ),
        encoding="utf-8",
    )

    after = _run_state(collection)
    assert after.returncode == 0
    assert json.loads(after.stdout)["decision"] == "skip"


def test_generate_state_routes_lyria_and_skips_only_after_master_exists(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "lyria")

    before = _run_state(collection)
    assert before.returncode == 10
    assert json.loads(before.stdout)["engine"] == "lyria"

    master = collection / "01-master" / "master.mp3"
    master.parent.mkdir()
    master.write_bytes(b"audio")
    after = _run_state(collection)
    assert after.returncode == 0
    assert json.loads(after.stdout)["decision"] == "skip"


def test_generate_state_routes_minimax_and_skips_only_after_master_exists(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "minimax")

    before = _run_state(collection)
    assert before.returncode == 10
    assert json.loads(before.stdout)["engine"] == "minimax"

    master = collection / "01-master" / "master.mp3"
    master.parent.mkdir()
    master.write_bytes(b"audio")
    after = _run_state(collection)
    assert after.returncode == 0
    assert json.loads(after.stdout)["decision"] == "skip"
