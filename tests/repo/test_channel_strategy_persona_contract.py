"""Executable contracts for ``/channel-strategy --persona`` (#3820)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

ROOT = REPO_ROOT
SKILL_DIR = ROOT / ".claude" / "skills" / "channel-strategy"
SKILL = SKILL_DIR / "SKILL.md"
PERSONA = SKILL_DIR / "references" / "persona.md"
MANIFEST = SKILL_DIR / "references" / "channel-strategy-chain-manifest.json"
STATE = SKILL_DIR / "references" / "channel-strategy-chain-state.py"
INVENTORY = SkillInventory(ROOT)


def _run_state(channel_dir: Path) -> tuple[int, dict[str, object]]:
    result = subprocess.run(
        ["uv", "run", "python", str(STATE), "--channel-dir", str(channel_dir), "--step", "persona"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def _touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# artifact\n", encoding="utf-8")


def test_channel_strategy_distributes_persona_mode_as_the_canonical_owner() -> None:
    names = {path.name for path in INVENTORY.skill_directories()}

    assert "channel-strategy" in names
    assert "audience-persona-design" not in names
    assert PERSONA.is_file()


def test_channel_strategy_registers_only_persona_and_reserves_later_modes() -> None:
    text = SKILL.read_text(encoding="utf-8")
    frontmatter = INVENTORY.frontmatter("channel-strategy")
    mode_table = text.split("| mode | 読む reference |", 1)[1].split("## 共通前提", 1)[0]
    modes = [line.split("|", 2)[1].strip() for line in mode_table.splitlines() if line.startswith("| `--")]

    assert frontmatter["name"] == "channel-strategy"
    assert frontmatter["purpose"] == "決める"
    assert "--persona" in frontmatter["description"]
    assert modes == ["`--persona`"]
    assert all(flag in text for flag in ("--scene", "--constraints", "--direction"))


def test_channel_strategy_manifest_contains_only_persona_step() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest == {
        "chainId": "channel-strategy",
        "steps": [
            {
                "id": "persona",
                "skill": "channel-strategy",
                "prerequisiteArtifacts": ["docs/plans/viewer-voice-analysis.md"],
                "outputArtifacts": ["docs/channel/personas/persona-definition.md"],
                "idempotency": {"script": "references/channel-strategy-chain-state.py"},
            }
        ],
    }


def test_persona_state_blocks_until_viewer_voice_exists(tmp_path: Path) -> None:
    exit_code, result = _run_state(tmp_path)

    assert exit_code == 20
    assert result == {
        "step": "persona",
        "decision": "blocked",
        "reason": "viewer_voice_missing",
        "missing": ["docs/plans/viewer-voice-analysis.md"],
        "next": "channel-research --voice",
    }


def test_persona_state_runs_then_skips_after_output_exists(tmp_path: Path) -> None:
    _touch(tmp_path, "docs/plans/viewer-voice-analysis.md")
    exit_code, result = _run_state(tmp_path)
    assert exit_code == 10
    assert result["decision"] == "run"
    assert result["reason"] == "persona_missing"

    _touch(tmp_path, "docs/channel/personas/persona-definition.md")
    exit_code, result = _run_state(tmp_path)
    assert exit_code == 0
    assert result["decision"] == "skip"
    assert result["reason"] == "persona_complete"
