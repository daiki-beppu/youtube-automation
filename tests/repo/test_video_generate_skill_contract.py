"""Contracts for replacing the legacy video-generation skill with ``/video --generate`` (#3835)."""

from __future__ import annotations

import json

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _migrate_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
VIDEO = INVENTORY.skill_directory("video")


def test_video_owns_generate_mode_and_local_generation_assets() -> None:
    skill = (VIDEO / "SKILL.md").read_text(encoding="utf-8")

    assert "videoup" not in {path.name for path in INVENTORY.skill_directories()}
    assert "purpose: 作る" in skill
    assert "| `--generate` | `references/generate.md` |" in skill
    assert "/music --master" in skill
    assert "/music --generate" in skill
    assert "/thumbnail --loop" in skill
    assert (VIDEO / "references" / "generate_videos.sh").is_file()


def test_video_chain_manifest_starts_with_generate_without_approval_gate() -> None:
    manifest = json.loads((VIDEO / "references" / "video-chain-manifest.json").read_text(encoding="utf-8"))

    assert manifest["chainId"] == "video"
    assert manifest["steps"] == [
        {
            "id": "generate",
            "skill": "video",
            "prerequisiteArtifacts": [
                "collections/<id>/01-master/<master-audio>",
                "collections/<id>/10-assets/main.png|main.jpg|loop.mp4",
            ],
            "outputArtifacts": ["collections/<id>/01-master/*.mp4"],
            "approvalGate": {
                "skip": True,
                "configPath": "workflow.video.skip_approvals.generate",
            },
            "idempotency": {"script": "references/video-chain-state.py"},
        }
    ]


def test_video_default_config_namespaces_generate_mode() -> None:
    config = yaml.safe_load((VIDEO / "config.default.yaml").read_text(encoding="utf-8"))

    assert set(config) == {"generate"}
    assert config["generate"]["video_type"] == "loop"


def test_video_config_loader_and_migration_share_generate_namespace(tmp_path) -> None:
    migration = _migrate_config.SKILL_CONFIG_MIGRATIONS["videoup"]
    default = yaml.safe_load((VIDEO / "config.default.yaml").read_text(encoding="utf-8"))

    assert migration.target_skill == "video"
    assert migration.section == "generate"
    assert load_skill_config("video", use_cache=False, channel_dir=tmp_path) == default
