"""Contracts for replacing ``/live-clean`` with ``/publish --clean`` (#3846)."""

from __future__ import annotations

import json

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _migrate_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
PUBLISH = INVENTORY.skill_directory("publish")


def test_publish_owns_clean_as_the_fifth_exclusive_mode() -> None:
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")
    clean = (PUBLISH / "references" / "clean.md").read_text(encoding="utf-8")
    modes = skill.split("## モード判定", 1)[1].split("## 修飾フラグ", 1)[0]

    assert "live-clean" not in {path.name for path in INVENTORY.skill_directories()}
    assert "| `--clean` | `references/clean.md` |" in modes
    assert modes.count("| `--") == 5
    assert "rm -rf" in clean and "絶対に使わない" in clean


def test_clean_requires_publish_completion_and_explicit_approval() -> None:
    clean = (PUBLISH / "references" / "clean.md").read_text(encoding="utf-8")

    for condition in (
        '`stage` が `"live"`',
        '`phase` が `"complete"`',
        "`upload.video_id`",
        "`upload.publish_at`",
    ):
        assert condition in clean
    assert "4条件すべて" in clean
    assert "clean-scan.py" in clean
    assert "git pull --ff-only" in clean
    assert "pull に失敗" in clean and "ドライラン表示へ進まない" in clean
    assert "削除を実行する" in clean and "キャンセル" in clean
    assert "承認されるまで" in clean
    assert "削除しない" in clean


def test_clean_is_not_part_of_the_default_publish_chain() -> None:
    manifest = json.loads((PUBLISH / "references" / "publish-chain-manifest.json").read_text(encoding="utf-8"))
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")

    assert [step["id"] for step in manifest["steps"]] == ["playlist", "upload", "community", "pinned"]
    overview = skill.split("## Overview", 1)[1].split("## モード判定", 1)[0]
    assert "playlist → upload → community → pinned" in overview
    assert "clean" not in overview


def test_live_clean_config_migrates_to_publish_clean_namespace(tmp_path) -> None:
    config = yaml.safe_load((PUBLISH / "config.default.yaml").read_text(encoding="utf-8"))
    migration = _migrate_config.SKILL_CONFIG_MIGRATIONS["live-clean"]

    assert set(config) == {"upload", "community", "clean"}
    assert "delete_patterns" in config["clean"]
    assert "protect_patterns" in config["clean"]
    assert migration == _migrate_config.SkillConfigMigration("publish", "clean")
    assert load_skill_config("live-clean", use_cache=False, channel_dir=tmp_path) == config["clean"]
    assert load_skill_config("publish", use_cache=False, channel_dir=tmp_path) == config
