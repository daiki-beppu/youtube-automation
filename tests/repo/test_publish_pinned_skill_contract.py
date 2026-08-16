"""Contracts for replacing ``/pinned-comment`` with ``/publish --pinned`` (#3845)."""

from __future__ import annotations

import json

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
PUBLISH = INVENTORY.skill_directory("publish")


def _section(text: str, heading: str, next_heading: str) -> str:
    return text.split(heading, 1)[1].split(next_heading, 1)[0]


def test_publish_owns_pinned_mode_without_promoting_cli_arguments() -> None:
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")
    pinned = (PUBLISH / "references" / "pinned.md").read_text(encoding="utf-8")
    modes = _section(skill, "## モード判定", "## 修飾フラグ")
    modifiers = _section(skill, "## 修飾フラグ", "## 設定読み込みゲート")

    assert "pinned-comment" not in {path.name for path in INVENTORY.skill_directories()}
    assert "| `--pinned` | `references/pinned.md` |" in modes
    assert "--dry-run" not in modes and "--apply" not in modes
    assert "--dry-run" not in modifiers and "--apply" not in modifiers
    assert "yt-pinned-comment" in pinned
    assert "--dry-run" in pinned and "--apply" in pinned
    assert "Studio UI" in pinned and "手動ピン留め" in pinned


def test_publish_chain_appends_pinned_with_existing_approval_resolution() -> None:
    manifest = json.loads((PUBLISH / "references" / "publish-chain-manifest.json").read_text(encoding="utf-8"))
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")

    assert [step["id"] for step in manifest["steps"]] == ["playlist", "upload", "community", "pinned"]
    assert manifest["steps"][3] == {
        "id": "pinned",
        "skill": "publish",
        "prerequisiteArtifacts": ["collections/<id>/workflow-state.json::upload.video_id"],
        "outputArtifacts": ["pinned_comment_history.json"],
        "approvalGate": {
            "skip": True,
            "configPath": "workflow.post_publish.skip_approvals.pinned_comment",
        },
        "idempotency": {"script": "references/publish-chain-state.py"},
    }
    assert "workflow.post_publish.skip_approvals.pinned_comment" in skill
    assert "approval_gates.pinned_comment" in skill
    assert "承認されるまで" in skill


def test_publish_manifest_owns_pinned_step() -> None:
    manifest = json.loads(
        (REPO_ROOT / ".claude/skills/publish/references/publish-chain-manifest.json").read_text(encoding="utf-8")
    )

    pinned = next(step for step in manifest["steps"] if step["id"] == "pinned")
    assert pinned["skill"] == "publish"


def test_pinned_reference_routes_legacy_video_id_repair_through_owner_cli() -> None:
    reference = (PUBLISH / "references" / "pinned.md").read_text(encoding="utf-8")

    assert "top-level `video_id`" in reference
    assert "`upload.video_id`" in reference
    assert "yt-workflow-state --collection <path> set-upload --video-id <video-id>" in reference
