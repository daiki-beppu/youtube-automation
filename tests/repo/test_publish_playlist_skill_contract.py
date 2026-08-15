"""Contracts for replacing ``/playlist`` with ``/publish --playlist`` (#3842)."""

from __future__ import annotations

import json

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
PUBLISH = INVENTORY.skill_directory("publish")


def test_publish_owns_playlist_mode_and_closed_references() -> None:
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")
    playlist = (PUBLISH / "references" / "playlist.md").read_text(encoding="utf-8")

    assert "playlist" not in {path.name for path in INVENTORY.skill_directories()}
    assert "| `--playlist` | `references/playlist.md` |" in skill
    assert "playlist_manager.py" in playlist
    assert "playlist_status.py" in playlist
    assert "publish/references/playlist_manager.py" in playlist
    assert "publish/references/playlist_status.py" in playlist
    assert "dry-run → 確認 → 本番" in playlist


def test_publish_chain_runs_playlist_before_upload() -> None:
    manifest = json.loads((PUBLISH / "references" / "publish-chain-manifest.json").read_text(encoding="utf-8"))

    assert [step["id"] for step in manifest["steps"]] == ["playlist", "upload"]
    playlist = manifest["steps"][0]
    assert playlist == {
        "id": "playlist",
        "skill": "publish",
        "prerequisiteArtifacts": ["config/channel/playlists.json"],
        "outputArtifacts": ["config/channel/playlists.json::playlists.*.playlist_id"],
        "approvalGate": {"skip": False},
        "idempotency": {"script": "references/publish-chain-state.py"},
    }


def test_publish_without_mode_runs_the_full_chain() -> None:
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")

    assert "0 個なら chain manifest に従い playlist → upload" in skill
    assert "playlist step" in skill
    assert "upload step" in skill
