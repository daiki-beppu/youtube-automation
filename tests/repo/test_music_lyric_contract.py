"""Contracts for migrating ``/suno-lyric`` into ``/music --lyric`` (#3825)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from tests.helpers.music_prompt import write_suno_prompt_pair
from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _migrate_config
from youtube_automation.configuration import skills as skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
SKILL_DIR = INVENTORY.skills_root / "music"
STATE = SKILL_DIR / "references" / "music-chain-state.py"


def _write_channel(tmp_path: Path, *, music_engine: str, genre_line: str, mode: str) -> Path:
    channel = tmp_path / "channel"
    (channel / "config" / "channel").mkdir(parents=True)
    (channel / "config" / "channel" / "youtube.json").write_text(
        json.dumps({"music_engine": music_engine}), encoding="utf-8"
    )
    (channel / "config" / "skills").mkdir()
    (channel / "config" / "skills" / "music.yaml").write_text(
        yaml.safe_dump({"prompt": {"genre_line": genre_line}}), encoding="utf-8"
    )
    collection = channel / "collections" / "planning" / "demo"
    documentation = collection / "20-documentation"
    documentation.mkdir(parents=True)
    (documentation / "suno-patterns.yaml").write_text(yaml.safe_dump({"mode": mode}), encoding="utf-8")
    write_suno_prompt_pair(documentation, [{"name": "fixture"}])
    return collection


def _run_state(collection: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STATE), "--collection-path", str(collection), "--step", "lyric"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_music_exposes_lyric_mode_and_replaces_suno_lyric() -> None:
    assert not os.path.lexists(INVENTORY.skills_root / "suno-lyric")

    frontmatter = INVENTORY.frontmatter("music")
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "--lyric" in frontmatter["description"]
    assert "| `--prompt` | `references/prompt.md` |" in skill
    assert "| `--lyric` | `references/lyric.md` |" in skill
    assert len(skill.splitlines()) <= 400


def test_music_chain_adds_lyric_after_prompt() -> None:
    manifest = json.loads((SKILL_DIR / "references/music-chain-manifest.json").read_text(encoding="utf-8"))

    assert [step["id"] for step in manifest["steps"]][:2] == ["prompt", "lyric"]
    lyric = manifest["steps"][1]
    assert lyric["skill"] == "music"
    assert lyric["prerequisiteArtifacts"] == manifest["steps"][0]["outputArtifacts"]
    assert lyric["outputArtifacts"] == [
        "20-documentation/suno-lyrics.md",
        "20-documentation/suno-lyrics.json",
    ]


def test_music_lyric_config_is_namespaced_and_keeps_legacy_loader() -> None:
    defaults = yaml.safe_load((SKILL_DIR / "config.default.yaml").read_text(encoding="utf-8"))

    assert {"prompt", "lyric"} <= set(defaults)
    assert isinstance(defaults["lyric"], dict)
    assert "music.lyric" in skill_config.SKILL_ONLY_CONFIG_KEYS
    assert skill_config.skill_config_default_relative_path("suno-lyric") == Path("music/config.default.yaml")
    assert _migrate_config.SKILL_CONFIG_MIGRATIONS["suno-lyric"] == _migrate_config.SkillConfigMigration(
        "music", "lyric"
    )


def test_music_lyric_loader_reads_legacy_override(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "suno-lyric.yaml").write_text("lyric:\n  language: ja\n", encoding="utf-8")

    loaded = skill_config.load_skill_config("music.lyric", use_cache=False, channel_dir=tmp_path)

    assert loaded["lyric"]["language"] == "ja"


def test_music_lyric_loader_reads_namespaced_override(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "music.yaml").write_text("lyric:\n  lyric:\n    language: ja\n", encoding="utf-8")

    loaded = skill_config.load_skill_config("music.lyric", use_cache=False, channel_dir=tmp_path)

    assert loaded["lyric"]["language"] == "ja"


def test_music_lyric_migration_preserves_existing_prompt_section(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    legacy = config_dir / "suno-lyric.yaml"
    legacy.write_text("lyric:\n  language: ja\n", encoding="utf-8")
    destination = config_dir / "music.yaml"
    destination.write_text("prompt:\n  genre_line: soulful vocals\n", encoding="utf-8")

    plan = _migrate_config.build_migration_plan(
        tmp_path,
        {"suno-lyric": _migrate_config.SkillConfigMigration("music", "lyric")},
    )
    _migrate_config.apply_migration_plan(plan)

    assert not legacy.exists()
    assert yaml.safe_load(destination.read_text(encoding="utf-8")) == {
        "prompt": {"genre_line": "soulful vocals"},
        "lyric": {"lyric": {"language": "ja"}},
    }


def test_music_lyric_state_runs_then_skips_after_outputs_exist(tmp_path: Path) -> None:
    collection = _write_channel(tmp_path, music_engine="suno", genre_line="soulful female vocals", mode="vocal")

    before = _run_state(collection)
    assert before.returncode == 10
    assert json.loads(before.stdout)["decision"] == "run"

    documentation = collection / "20-documentation"
    (documentation / "suno-lyrics.md").write_text("# Lyrics\n", encoding="utf-8")
    (documentation / "suno-lyrics.json").write_text("[]\n", encoding="utf-8")
    after = _run_state(collection)
    assert after.returncode == 0
    assert json.loads(after.stdout)["decision"] == "skip"

def test_music_lyric_state_blocks_lyria_engine(tmp_path: Path) -> None:
    collection = _write_channel(tmp_path, music_engine="lyria", genre_line="soulful female vocals", mode="vocal")

    result = _run_state(collection)

    assert result.returncode == 20
    assert json.loads(result.stdout)["reason"] == "music_engine_not_lyric_capable"

def test_music_lyric_state_blocks_instrumental_collection(tmp_path: Path) -> None:
    collection = _write_channel(tmp_path, music_engine="suno", genre_line="ambient instrumental", mode="instrumental")

    result = _run_state(collection)

    assert result.returncode == 20
    assert json.loads(result.stdout)["reason"] == "lyrics_not_required"
