"""Contracts for migrating ``/suno`` into ``/music --prompt`` (#3824)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
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


def test_music_chain_manifest_keeps_prompt_as_first_step() -> None:
    manifest = json.loads((SKILL_DIR / "references/music-chain-manifest.json").read_text(encoding="utf-8"))

    assert manifest["chainId"] == "music"
    assert [step["id"] for step in manifest["steps"]][:1] == ["prompt"]
    step = manifest["steps"][0]
    assert step["skill"] == "music"
    assert step["idempotency"]["script"] == "references/music-chain-state.py"
    assert "20-documentation/suno-prompts.json" in step["outputArtifacts"]


def test_music_prompt_config_uses_namespaced_default_and_keeps_legacy_loader() -> None:
    defaults = yaml.safe_load((SKILL_DIR / "config.default.yaml").read_text(encoding="utf-8"))

    assert "prompt" in defaults
    assert isinstance(defaults["prompt"], dict)
    assert "music.prompt" in skill_config.SKILL_CONFIG_KEYS
    assert skill_config.skill_config_default_relative_path("suno") == Path("music/config.default.yaml")
    assert _migrate_config.SKILL_CONFIG_MIGRATIONS["suno"] == _migrate_config.SkillConfigMigration("music", "prompt")


def test_music_prompt_state_runs_then_blocks_invalid_output(tmp_path: Path) -> None:
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
    assert after.returncode == 20
    assert json.loads(after.stdout)["decision"] == "blocked"


def _prompt_state(collection: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STATE), "--collection-path", str(collection), "--step", "prompt"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_prompt_resume_requires_approval_of_current_pair(tmp_path: Path) -> None:
    from tests.application.documents.test_music_prompt import _document
    from youtube_automation.application.documents.migration import MarkdownMigrationDecision
    from youtube_automation.application.documents.music_prompt import (
        finalize_music_prompt_review,
        music_prompt_artifact_digest,
        require_recorded_machine_verification,
        write_music_prompt_document,
    )

    target = tmp_path / "20-documentation/suno-prompts.json"
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    write_music_prompt_document(
        target,
        state,
        _document,
        MarkdownMigrationDecision.NOT_REQUIRED,
        machine_verify=require_recorded_machine_verification,
    )
    unapproved = _prompt_state(tmp_path)
    assert unapproved.returncode == 20
    assert json.loads(unapproved.stdout)["next"]
    finalize_music_prompt_review(
        target,
        state,
        decision="approve",
        source="automatic",
        expected_artifact_digest=music_prompt_artifact_digest(target),
    )
    before = {path: path.read_bytes() for path in (target, target.with_suffix(".html"), state)}
    for _ in range(2):
        approved = _prompt_state(tmp_path)
        assert approved.returncode == 0, approved.stdout
        assert json.loads(approved.stdout)["decision"] == "skip"
    assert all(path.read_bytes() == data for path, data in before.items())

    changed = _document()
    changed["entries"][0]["style"] = "changed approved-looking prompt"
    write_music_prompt_document(
        target,
        state,
        lambda: changed,
        MarkdownMigrationDecision.NOT_REQUIRED,
        machine_verify=require_recorded_machine_verification,
    )
    stale = _prompt_state(tmp_path)
    assert stale.returncode == 20
    assert json.loads(stale.stdout)["next"]


@pytest.mark.parametrize("damage", ["broken_json", "empty_entries", "missing_html", "changed_json", "legacy_approval"])
def test_prompt_resume_blocks_damaged_or_unbound_approval(tmp_path: Path, damage: str) -> None:
    from tests.application.documents.test_music_prompt import _document
    from youtube_automation.application.documents.migration import MarkdownMigrationDecision
    from youtube_automation.application.documents.music_prompt import (
        finalize_music_prompt_review,
        music_prompt_artifact_digest,
        require_recorded_machine_verification,
        write_music_prompt_document,
    )

    target = tmp_path / "20-documentation/suno-prompts.json"
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    write_music_prompt_document(
        target,
        state,
        _document,
        MarkdownMigrationDecision.NOT_REQUIRED,
        machine_verify=require_recorded_machine_verification,
    )
    finalize_music_prompt_review(
        target,
        state,
        decision="approve",
        source="automatic",
        expected_artifact_digest=music_prompt_artifact_digest(target),
    )
    if damage == "broken_json":
        target.write_text("not-json", encoding="utf-8")
    elif damage == "empty_entries":
        document = _document()
        document["entries"] = []
        target.write_text(json.dumps(document), encoding="utf-8")
    elif damage == "missing_html":
        target.with_suffix(".html").unlink()
    elif damage == "changed_json":
        document = _document()
        document["entries"][0]["style"] = "changed"
        target.write_text(json.dumps(document), encoding="utf-8")
    else:
        legacy = json.loads(state.read_text(encoding="utf-8"))
        del legacy["music_prompt_approved_digest"]
        state.write_text(json.dumps(legacy), encoding="utf-8")
    before = state.read_bytes()

    result = _prompt_state(tmp_path)

    assert result.returncode == 20, result.stdout + result.stderr
    assert json.loads(result.stdout)["decision"] == "blocked"
    assert json.loads(result.stdout)["next"]
    assert state.read_bytes() == before
