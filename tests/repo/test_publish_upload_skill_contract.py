"""Contracts for replacing ``/video-upload`` with ``/publish --upload`` (#3841)."""

from __future__ import annotations

import json

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _migrate_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
PUBLISH = INVENTORY.skill_directory("publish")


def test_publish_owns_upload_mode_and_legacy_assets() -> None:
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")
    upload = (PUBLISH / "references" / "upload.md").read_text(encoding="utf-8")

    assert "video-upload" not in {path.name for path in INVENTORY.skill_directories()}
    assert "purpose: 公開する" in skill
    assert "| `--upload` | `references/upload.md` |" in skill
    assert "content_model.type" in upload
    assert "yt-upload-collection" in upload
    assert "yt-upload-auto" in upload
    assert (PUBLISH / "references" / "posting-checklist.md").is_file()
    assert (PUBLISH / "references" / "scheduled-publish.md").is_file()


def test_publish_chain_manifest_keeps_upload_approval_gate() -> None:
    manifest = json.loads((PUBLISH / "references" / "publish-chain-manifest.json").read_text(encoding="utf-8"))

    assert manifest["chainId"] == "publish"
    upload = next(step for step in manifest["steps"] if step["id"] == "upload")
    assert upload == {
        "id": "upload",
        "skill": "publish",
        "prerequisiteArtifacts": [
            "collections/<id>/01-master/*.mp4",
            "collections/<id>/20-documentation/descriptions.json",
            "collections/<id>/20-documentation/descriptions.html",
        ],
        "outputArtifacts": [
            "collections/<id>/20-documentation/upload_tracking.json",
            "collections/<id>/workflow-state.json::upload.video_id",
        ],
        "approvalGate": {
            "skip": False,
            "configPath": "workflow.wf_next.skip_upload_approval",
        },
        "idempotency": {"script": "references/publish-chain-state.py"},
    }


def test_publish_default_config_namespaces_upload_mode() -> None:
    config = yaml.safe_load((PUBLISH / "config.default.yaml").read_text(encoding="utf-8"))

    assert "upload" in config
    assert config["upload"]["preflight"]["master_video_globs"][0] == "01-master/*.mp4"


def test_video_upload_config_migrates_to_publish_upload_namespace(tmp_path) -> None:
    migration = _migrate_config.SKILL_CONFIG_MIGRATIONS["video-upload"]
    default = yaml.safe_load((PUBLISH / "config.default.yaml").read_text(encoding="utf-8"))

    assert migration.target_skill == "publish"
    assert migration.section == "upload"
    assert load_skill_config("video-upload", use_cache=False, channel_dir=tmp_path) == default["upload"]
    assert load_skill_config("publish", use_cache=False, channel_dir=tmp_path) == default
