"""運用成果物 inventory の ratchet 契約。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.documents.operational_artifacts import (
    OperationalArtifactInventory,
    lint_operational_artifacts,
    load_operational_artifact_inventory,
    resolve_artifacts,
)
from youtube_automation.domains.documents.rendering import render_repository_document
from youtube_automation.domains.documents.schema_registry import RepositorySchema
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


def _published_analysis(path: Path) -> None:
    document = json.loads((REPO_ROOT / "tests/fixtures/documents/analysis-report.json").read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    path.with_suffix(".html").write_text(
        render_repository_document(RepositorySchema.ANALYSIS_REPORT, document), encoding="utf-8"
    )


def test_resolve_artifacts_excludes_analysis_sidecars_and_selects_latest(tmp_path: Path) -> None:
    older = tmp_path / "reports" / "analysis_20260820.json"
    latest = tmp_path / "reports" / "analysis_20260822.json"
    _published_analysis(older)
    _published_analysis(latest)
    (tmp_path / "reports" / "analysis_20260822.vpd-ranking.json").write_text("{}", encoding="utf-8")

    resolved = resolve_artifacts(tmp_path, "reports/analysis_*.json")

    assert resolved.valid == (older, latest)
    assert resolved.invalid == ()
    assert resolved.latest == latest


def test_resolve_artifacts_classifies_invalid_published_pair(tmp_path: Path) -> None:
    invalid = tmp_path / "reports" / "analysis_20260822.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("{}", encoding="utf-8")

    resolved = resolve_artifacts(tmp_path, "reports/analysis_*.json")

    assert resolved.valid == ()
    assert resolved.invalid[0].path == invalid
    assert resolved.invalid[0].reason
    assert resolved.latest is None


def test_artifact_freshness_compares_filename_dates(tmp_path: Path) -> None:
    report = tmp_path / "reports" / "analysis_20260820.json"
    _published_analysis(report)
    data = tmp_path / "data" / "analytics_data_20260822.json"

    freshness = resolve_artifacts(tmp_path, "reports/analysis_*.json").freshness(against=data)

    assert freshness.is_stale is True
    assert freshness.reason == "relative"


def test_artifact_freshness_applies_absolute_limit_to_upstream_date(tmp_path: Path) -> None:
    report = tmp_path / "reports" / "analysis_20260822.json"
    _published_analysis(report)
    data = tmp_path / "data" / "analytics_data_20260822.json"

    freshness = resolve_artifacts(tmp_path, "reports/analysis_*.json").freshness(
        against=data,
        max_age_days=1,
        today=date(2026, 8, 24),
    )

    assert freshness.is_stale is True
    assert freshness.reason == "absolute"
    assert freshness.against_date == date(2026, 8, 22)


def test_artifact_freshness_without_upstream_date_is_not_absolute_stale(tmp_path: Path) -> None:
    report = tmp_path / "reports" / "analysis_20260820.json"
    _published_analysis(report)

    freshness = resolve_artifacts(tmp_path, "reports/analysis_*.json").freshness(
        against=(),
        max_age_days=1,
        today=date(2026, 8, 24),
    )

    assert freshness.is_stale is False
    assert freshness.reason is None
    assert freshness.artifact_date == date(2026, 8, 20)
    assert freshness.against_date is None


def test_missing_artifact_takes_precedence_over_absolute_limit(tmp_path: Path) -> None:
    data = tmp_path / "data" / "analytics_data_20260820.json"

    freshness = resolve_artifacts(tmp_path, "reports/analysis_*.json").freshness(
        against=data,
        max_age_days=1,
        today=date(2026, 8, 24),
    )

    assert freshness.is_stale is True
    assert freshness.reason == "missing"
    assert freshness.artifact_date is None
    assert freshness.against_date == date(2026, 8, 20)
