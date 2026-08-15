"""Executable contracts for ``/channel-strategy`` modes (#3820-#3823)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.domains.skills.inventory import SkillInventory
from youtube_automation.infrastructure.documents.publishing import publish_json_document

ROOT = REPO_ROOT
SKILL_DIR = ROOT / ".claude" / "skills" / "channel-strategy"
SKILL = SKILL_DIR / "SKILL.md"
PERSONA = SKILL_DIR / "references" / "persona.md"
SCENE = SKILL_DIR / "references" / "scene.md"
CONSTRAINTS = SKILL_DIR / "references" / "constraints.md"
DIRECTION = SKILL_DIR / "references" / "direction.md"
DESIRE_VOCABULARY = SKILL_DIR / "references" / "desire-vocabulary.md"
MANIFEST = SKILL_DIR / "references" / "channel-strategy-chain-manifest.json"
STATE = SKILL_DIR / "references" / "channel-strategy-chain-state.py"
INVENTORY = SkillInventory(ROOT)


def _run_state(channel_dir: Path, step: str) -> tuple[int, dict[str, object]]:
    result = subprocess.run(
        ["uv", "run", "python", str(STATE), "--channel-dir", str(channel_dir), "--step", step],
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


def _viewer_voice(root: Path) -> None:
    path = root / "docs/plans/viewer-voice-analysis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "report_type": "viewer_voice",
        "summary": "voice",
        "source_provenance": [{"path": "data/comments.json", "collected_at": "2026-08-16", "claim": "voice"}],
        "competitor_comparison": [],
        "winning_patterns": [],
        "evidence": [{"id": "ev-1", "source_path": "data/comments.json", "observation": "fact"}],
        "application_candidates": [],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    publish_json_document(path, RepositorySchema.CHANNEL_RESEARCH_REPORT)


def test_channel_strategy_distributes_all_registered_modes_as_the_canonical_owner() -> None:
    names = {path.name for path in INVENTORY.skill_directories()}

    assert "channel-strategy" in names
    assert "audience-persona-design" not in names
    assert "viewing-scene" not in names
    assert "creative-constraints" not in names
    assert "channel-new" not in names
    assert PERSONA.is_file()
    assert SCENE.is_file()
    assert CONSTRAINTS.is_file()
    assert DIRECTION.is_file()
    assert DESIRE_VOCABULARY.is_file()


def test_channel_strategy_registers_all_four_modes() -> None:
    text = SKILL.read_text(encoding="utf-8")
    frontmatter = INVENTORY.frontmatter("channel-strategy")
    mode_table = text.split("| mode | 読む reference |", 1)[1].split("## 共通前提", 1)[0]
    modes = [line.split("|", 2)[1].strip() for line in mode_table.splitlines() if line.startswith("| `--")]

    assert frontmatter["name"] == "channel-strategy"
    assert frontmatter["purpose"] == "決める"
    assert "--persona" in frontmatter["description"]
    assert modes == ["`--persona`", "`--scene`", "`--constraints`", "`--direction`"]


def test_direction_preserves_step_order_without_joining_initial_chain() -> None:
    direction = DIRECTION.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert [
        line.split(":", 1)[0].removeprefix("## Step D")
        for line in direction.splitlines()
        if line.startswith("## Step D")
    ] == ["1", "2", "3", "4", "5"]
    assert [step["id"] for step in manifest["steps"]] == ["persona", "scene", "constraints"]


def test_channel_strategy_manifest_orders_persona_scene_constraints() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest == {
        "chainId": "channel-strategy",
        "steps": [
            {
                "id": "persona",
                "skill": "channel-strategy",
                "prerequisiteArtifacts": [
                    "docs/plans/viewer-voice-analysis.json",
                    "docs/plans/viewer-voice-analysis.html",
                ],
                "outputArtifacts": ["docs/channel/personas/persona-definition.md"],
                "idempotency": {"script": "references/channel-strategy-chain-state.py"},
            },
            {
                "id": "scene",
                "skill": "channel-strategy",
                "prerequisiteArtifacts": ["docs/channel/personas/persona-definition.md"],
                "outputArtifacts": ["docs/plans/viewing-scene-matrix.md"],
                "idempotency": {"script": "references/channel-strategy-chain-state.py"},
            },
            {
                "id": "constraints",
                "skill": "channel-strategy",
                "prerequisiteArtifacts": [
                    "docs/channel/personas/persona-definition.md",
                    "docs/plans/viewing-scene-matrix.md",
                ],
                "outputArtifacts": ["docs/channel/creative-constraints.md"],
                "idempotency": {"script": "references/channel-strategy-chain-state.py"},
            },
        ],
    }


def test_persona_state_blocks_until_viewer_voice_exists(tmp_path: Path) -> None:
    exit_code, result = _run_state(tmp_path, "persona")

    assert exit_code == 20
    assert result == {
        "step": "persona",
        "decision": "blocked",
        "reason": "viewer_voice_missing",
        "missing": ["docs/plans/viewer-voice-analysis.json"],
        "next": "channel-research --voice",
    }


def test_persona_state_runs_then_skips_after_output_exists(tmp_path: Path) -> None:
    _viewer_voice(tmp_path)
    exit_code, result = _run_state(tmp_path, "persona")
    assert exit_code == 10
    assert result["decision"] == "run"
    assert result["reason"] == "persona_missing"

    _touch(tmp_path, "docs/channel/personas/persona-definition.md")
    exit_code, result = _run_state(tmp_path, "persona")
    assert exit_code == 0
    assert result["decision"] == "skip"
    assert result["reason"] == "persona_complete"


def test_scene_state_blocks_until_persona_exists(tmp_path: Path) -> None:
    exit_code, result = _run_state(tmp_path, "scene")

    assert exit_code == 20
    assert result == {
        "step": "scene",
        "decision": "blocked",
        "reason": "persona_missing",
        "missing": ["docs/channel/personas/persona-definition.md"],
        "next": "channel-strategy --persona",
    }


def test_scene_state_runs_then_skips_after_output_exists(tmp_path: Path) -> None:
    _touch(tmp_path, "docs/channel/personas/persona-definition.md")
    exit_code, result = _run_state(tmp_path, "scene")
    assert exit_code == 10
    assert result["decision"] == "run"
    assert result["reason"] == "scene_missing"

    _touch(tmp_path, "docs/plans/viewing-scene-matrix.md")
    exit_code, result = _run_state(tmp_path, "scene")
    assert exit_code == 0
    assert result["decision"] == "skip"
    assert result["reason"] == "scene_complete"


def test_constraints_state_blocks_until_persona_and_scene_exist(tmp_path: Path) -> None:
    exit_code, result = _run_state(tmp_path, "constraints")
    assert exit_code == 20
    assert result["reason"] == "constraints_prerequisites_missing"
    assert result["missing"] == [
        "docs/channel/personas/persona-definition.md",
        "docs/plans/viewing-scene-matrix.md",
    ]
    assert result["next"] == "channel-strategy --persona"

    _touch(tmp_path, "docs/channel/personas/persona-definition.md")
    exit_code, result = _run_state(tmp_path, "constraints")
    assert exit_code == 20
    assert result["missing"] == ["docs/plans/viewing-scene-matrix.md"]
    assert result["next"] == "channel-strategy --scene"


def test_constraints_state_runs_then_skips_after_output_exists(tmp_path: Path) -> None:
    _touch(tmp_path, "docs/channel/personas/persona-definition.md")
    _touch(tmp_path, "docs/plans/viewing-scene-matrix.md")
    exit_code, result = _run_state(tmp_path, "constraints")
    assert exit_code == 10
    assert result["decision"] == "run"
    assert result["reason"] == "constraints_missing"

    _touch(tmp_path, "docs/channel/creative-constraints.md")
    exit_code, result = _run_state(tmp_path, "constraints")
    assert exit_code == 0
    assert result["decision"] == "skip"
    assert result["reason"] == "constraints_complete"
