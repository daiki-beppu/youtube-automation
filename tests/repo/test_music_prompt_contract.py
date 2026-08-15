"""Contracts for migrating ``/suno`` into ``/music --prompt`` (#3824)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _migrate_config
from youtube_automation.configuration import skills as skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
SKILL_DIR = INVENTORY.skills_root / "music"
STATE = SKILL_DIR / "references" / "music-chain-state.py"


def test_music_replaces_suno_and_exposes_prompt_mode() -> None:
    assert SKILL_DIR.is_dir()
    assert not os.path.lexists(INVENTORY.skills_root / "suno")

    frontmatter = INVENTORY.frontmatter("music")
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert frontmatter["name"] == "music"
    assert frontmatter["purpose"] == "作る"
    assert "--prompt" in frontmatter["description"]
    assert len(skill.splitlines()) <= 400
    assert "$ARGUMENTS" in skill
    assert "2 個以上" in skill
    assert "references/prompt.md" in skill


def test_music_chain_manifest_contains_only_prompt() -> None:
    manifest = json.loads((SKILL_DIR / "references/music-chain-manifest.json").read_text(encoding="utf-8"))

    assert manifest["chainId"] == "music"
    assert [step["id"] for step in manifest["steps"]] == ["prompt"]
    step = manifest["steps"][0]
    assert step["skill"] == "music"
    assert step["idempotency"]["script"] == "references/music-chain-state.py"
    assert "20-documentation/suno-prompts.json" in step["outputArtifacts"]


def test_music_prompt_config_uses_namespaced_default_and_keeps_legacy_loader() -> None:
    defaults = yaml.safe_load((SKILL_DIR / "config.default.yaml").read_text(encoding="utf-8"))

    assert set(defaults) == {"prompt"}
    assert isinstance(defaults["prompt"], dict)
    assert "music.prompt" in skill_config.SKILL_CONFIG_KEYS
    assert skill_config.skill_config_default_relative_path("suno") == Path("music/config.default.yaml")
    assert _migrate_config.SKILL_CONFIG_MIGRATIONS["suno"] == _migrate_config.SkillConfigMigration("music", "prompt")


def test_music_prompt_state_runs_then_skips_after_output_exists(tmp_path: Path) -> None:
    collection = tmp_path / "collections" / "planning" / "demo"
    collection.mkdir(parents=True)

    before = subprocess.run(
        [sys.executable, str(STATE), "--collection-path", str(collection), "--step", "prompt"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert before.returncode == 10
    assert json.loads(before.stdout)["decision"] == "run"

    output = collection / "20-documentation" / "suno-prompts.json"
    output.parent.mkdir()
    output.write_text("[]\n", encoding="utf-8")
    after = subprocess.run(
        [sys.executable, str(STATE), "--collection-path", str(collection), "--step", "prompt"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert after.returncode == 0
    assert json.loads(after.stdout)["decision"] == "skip"
