"""運用成果物 inventory の ratchet 契約。"""

from __future__ import annotations

from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.documents.operational_artifacts import (
    OperationalArtifactInventory,
    lint_operational_artifacts,
    load_operational_artifact_inventory,
)
from youtube_automation.domains.skills.inventory import SkillInventory


def _skill(root: Path, name: str, *, writes: str, reads: str = "なし") -> None:
    directory = root / ".claude" / "skills" / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"""---
name: {name}
description: "fixture"
purpose: 作る
---

## 成果物

- `書き込む`: `{writes}`
- `読み込む`: `{reads}`
""",
        encoding="utf-8",
    )


def _inventory(**overrides: object) -> OperationalArtifactInventory:
    payload: dict[str, object] = {
        "artifacts": [
            {
                "path": "reports/example.json",
                "owner": "producer",
                "schema": "analysis-report.schema.json",
                "consumers": ["consumer"],
            }
        ],
        "allowlists": {
            "hand_written_inputs": [],
            "repository_docs": [],
            "machine_only": [],
            "other_writes": [],
            "schemas": [],
        },
    }
    payload.update(overrides)
    return OperationalArtifactInventory.from_mapping(payload)


def test_valid_pair_and_validated_consumer_pass(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="reports/example.json`, `reports/example.html")
    _skill(tmp_path, "consumer", writes="なし", reads="reports/example.json")

    assert (
        lint_operational_artifacts(
            tmp_path,
            SkillInventory(tmp_path),
            _inventory(),
            repository_schemas=("analysis-report.schema.json",),
        )
        == []
    )


def test_markdown_writer_reports_owner_and_path(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="なし")
    reference = tmp_path / ".claude" / "skills" / "producer" / "references" / "mode.md"
    reference.parent.mkdir()
    reference.write_text("- `書き込む`: `docs/plans/new-report.md`\n", encoding="utf-8")

    violations = lint_operational_artifacts(tmp_path, SkillInventory(tmp_path), _inventory(artifacts=[]))

    assert any("producer" in item and "docs/plans/new-report.md" in item for item in violations)


def test_json_without_html_or_machine_only_reports_missing_pair(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="reports/example.json")

    violations = lint_operational_artifacts(tmp_path, SkillInventory(tmp_path), _inventory())

    assert any("reports/example.html" in item and "pair" in item for item in violations)


def test_explicit_markdown_and_machine_only_allowlists_pass(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="docs/plans/notes.md`, `reports/raw.json")
    inventory = _inventory(
        artifacts=[],
        allowlists={
            "hand_written_inputs": [{"path": "docs/plans/notes.md", "owner": "producer", "reason": "hand-written"}],
            "repository_docs": [],
            "machine_only": [{"path": "reports/raw.json", "owner": "producer", "reason": "state"}],
            "other_writes": [],
            "schemas": [],
        },
    )

    assert lint_operational_artifacts(tmp_path, SkillInventory(tmp_path), inventory, repository_schemas=()) == []


def test_stale_allowlist_is_rejected(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="なし")
    inventory = _inventory(
        artifacts=[],
        allowlists={
            "hand_written_inputs": [
                {"path": "docs/plans/deleted.md", "owner": "producer", "reason": "no longer exists"}
            ],
            "repository_docs": [],
            "machine_only": [],
            "other_writes": [],
            "schemas": [],
        },
    )

    violations = lint_operational_artifacts(tmp_path, SkillInventory(tmp_path), inventory)

    assert any("stale allowlist" in item and "docs/plans/deleted.md" in item for item in violations)


def test_orphan_schema_and_html_are_rejected(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="reports/orphan.html")
    inventory = _inventory(artifacts=[])

    violations = lint_operational_artifacts(
        tmp_path,
        SkillInventory(tmp_path),
        inventory,
        repository_schemas=("unused.schema.json",),
    )

    assert any("orphan HTML" in item and "reports/orphan.html" in item for item in violations)
    assert any("orphan schema" in item and "unused.schema.json" in item for item in violations)


def test_explicit_standalone_html_write_passes(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="reports/review.html")
    inventory = _inventory(
        artifacts=[],
        allowlists={
            "hand_written_inputs": [],
            "repository_docs": [],
            "machine_only": [],
            "other_writes": [{"path": "reports/review.html", "owner": "producer", "reason": "standalone review"}],
            "schemas": [],
        },
    )

    assert lint_operational_artifacts(tmp_path, SkillInventory(tmp_path), inventory, repository_schemas=()) == []


def test_master_video_review_inventory_uses_concrete_output_paths() -> None:
    inventory = load_operational_artifact_inventory()
    video_paths = {entry.path for entry in inventory.other_writes if entry.owner == "video"}

    assert "collections/<id>/20-documentation/reviews/master-video-preview.html" in video_paths
    assert "collections/<id>/20-documentation/reviews/master-video-full.html" in video_paths
    assert not any("{" in path or "}" in path for path in video_paths)


def test_unregistered_or_schema_unvalidated_consumer_is_rejected(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="reports/example.json`, `reports/example.html")
    _skill(tmp_path, "intruder", writes="なし", reads="reports/example.json")

    violations = lint_operational_artifacts(tmp_path, SkillInventory(tmp_path), _inventory())

    assert any("schema未検証consumer" in item and "intruder" in item for item in violations)


def test_python_writer_and_unvalidated_consumer_are_scanned(tmp_path: Path) -> None:
    _skill(tmp_path, "producer", writes="reports/example.json`, `reports/example.html")
    source = tmp_path / "src" / "youtube_automation" / "leak.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """from pathlib import Path
import json

def leak() -> None:
    Path('docs/plans/leak.md').write_text('bad')

def consume() -> object:
    return json.loads(Path('reports/example.json').read_text())
""",
        encoding="utf-8",
    )

    violations = lint_operational_artifacts(
        tmp_path,
        SkillInventory(tmp_path),
        _inventory(),
        repository_schemas=("analysis-report.schema.json",),
    )

    assert any("docs/plans/leak.md" in item and "leak.py" in item for item in violations)
    assert any("schema未検証consumer" in item and "leak.py" in item for item in violations)


def test_repository_inventory_matches_all_distributed_skills_and_sources() -> None:
    inventory = load_operational_artifact_inventory()

    assert inventory.artifacts
    assert lint_operational_artifacts(REPO_ROOT, SkillInventory(REPO_ROOT), inventory) == []
