"""Contracts for replacing ``/community-post`` with ``/publish --community`` (#3843)."""

from __future__ import annotations

import json

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _migrate_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
PUBLISH = INVENTORY.skill_directory("publish")


def test_publish_owns_community_mode() -> None:
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")
    community = (PUBLISH / "references" / "community.md").read_text(encoding="utf-8")

    assert "community-post" not in {path.name for path in INVENTORY.skill_directories()}
    assert "| `--community` | `references/community.md` |" in skill
    assert "community-post.txt" in community
    assert "pbcopy" in community
    assert 'open "$STUDIO_URL"' in community
    assert "--community --batch" in community


def test_publish_chain_appends_community_with_existing_approval_resolution() -> None:
    manifest = json.loads((PUBLISH / "references" / "publish-chain-manifest.json").read_text(encoding="utf-8"))
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")

    assert [step["id"] for step in manifest["steps"]][:3] == ["playlist", "upload", "community"]
    community = manifest["steps"][2]
    assert community == {
        "id": "community",
        "skill": "publish",
        "prerequisiteArtifacts": ["collections/<id>/workflow-state.json::upload.video_id"],
        "outputArtifacts": ["collections/<id>/20-documentation/community-post.txt"],
        "approvalGate": {
            "skip": True,
            "configPath": "workflow.post-publish.skip_approvals.community-post",
        },
        "idempotency": {"script": "references/publish-chain-state.py"},
    }
    assert "workflow.json::post_publish.approval_gates.community_post" in skill
    assert "workflow.json::post_publish.skip_approvals.community_post" in skill
    assert "承認されるまで" in skill


def test_community_default_config_is_namespaced_and_migratable(tmp_path) -> None:
    config = yaml.safe_load((PUBLISH / "config.default.yaml").read_text(encoding="utf-8"))
    migration = _migrate_config.SKILL_CONFIG_MIGRATIONS["community-post"]

    assert set(config) == {"upload", "community"}
    assert "template" in config["community"]
    assert "studio_url" in config["community"]
    assert migration.target_skill == "publish"
    assert migration.section == "community"
    assert load_skill_config("community-post", use_cache=False, channel_dir=tmp_path) == config["community"]
    assert load_skill_config("publish", use_cache=False, channel_dir=tmp_path) == config
