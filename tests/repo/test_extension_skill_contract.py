"""Contracts for consolidating extension setup and collection serving (#3747)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
SKILLS = INVENTORY.skills_root
EXTENSION = SKILLS / "extension"
GUARD = EXTENSION / "references" / "extension-mode-guard.py"


def _run_guard(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_extension_replaces_ext_install_and_exposes_modes() -> None:
    assert not os.path.lexists(SKILLS / "ext-install")
    skill = (EXTENSION / "SKILL.md").read_text(encoding="utf-8")
    assert "name: extension" in skill
    assert "purpose: 準備する" in skill
    for mode in ("--install", "--update", "--serve", "--stop"):
        assert f"| `{mode}` | `references/{mode[2:]}.md` |" in skill
    for modifier in ("--suno", "--distrokid", "--community"):
        assert f"| `{modifier}` |" in skill
    assert len(skill.splitlines()) <= 400


def test_extension_mode_guard_enforces_exclusivity_and_targets() -> None:
    conflict = _run_guard("--install", "--update")
    assert conflict.returncode == 2
    assert json.loads(conflict.stdout)["reason"] == "exclusive_mode_required"

    missing_target = _run_guard("--serve")
    assert missing_target.returncode == 2
    assert json.loads(missing_target.stdout)["reason"] == "single_target_required"

    too_many_targets = _run_guard("--stop", "--suno", "--distrokid")
    assert too_many_targets.returncode == 2
    assert json.loads(too_many_targets.stdout)["reason"] == "single_target_required"

    duplicate_target = _run_guard("--serve", "--suno", "--suno")
    assert duplicate_target.returncode == 2
    assert json.loads(duplicate_target.stdout)["reason"] == "single_target_required"

    auto = _run_guard()
    assert auto.returncode == 0
    assert json.loads(auto.stdout) == {
        "mode": "auto",
        "targets": ["suno", "distrokid", "community"],
    }

    selected = _run_guard("--install", "--suno", "--distrokid")
    assert selected.returncode == 0
    assert json.loads(selected.stdout) == {
        "mode": "install",
        "targets": ["suno", "distrokid"],
    }


def test_extension_references_own_install_update_and_server_contracts() -> None:
    for name in ("install", "update", "serve", "stop"):
        assert (EXTENSION / "references" / f"{name}.md").is_file()

    serve = (EXTENSION / "references" / "serve.md").read_text(encoding="utf-8")
    for token in (
        "--suno",
        "--allow-extension suno-helper",
        "--distrokid",
        "--allow-extension distrokid-helper",
        '--distrokid-capture-root "$CHANNEL_DIR"',
        "--port 7874",
        "既存 server",
        "再利用",
        "--stop",
        "process が残っていない",
    ):
        assert token in serve


def test_collection_server_consumers_reference_shared_contract() -> None:
    consumers = (
        SKILLS / "music" / "references" / "generate.md",
        SKILLS / "distrokid-helper" / "SKILL.md",
        SKILLS / "music" / "references" / "master.md",
        SKILLS / "music" / "references" / "prompt.md",
        SKILLS / "wf-new" / "SKILL.md",
        SKILLS / "wf-new" / "references" / "phase2.md",
    )
    for path in consumers:
        text = path.read_text(encoding="utf-8")
        assert "extension/references/serve.md" in text, path
        assert "--allow-extension" not in text, path


def test_current_operator_routes_use_extension_name() -> None:
    paths = [
        REPO_ROOT / ".claude" / "CLAUDE.template.md",
        REPO_ROOT / "docs" / "features.md",
        *(path / "SKILL.md" for path in INVENTORY.skill_directories()),
    ]
    for path in paths:
        assert "/ext-install" not in path.read_text(encoding="utf-8"), path
