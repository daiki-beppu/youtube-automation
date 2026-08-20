from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.core.errors import DocumentValidationError
from youtube_automation.domains.documents.schema_registry import (
    RepositorySchema,
    compile_repository_schemas,
    load_repository_schema,
    repository_schema_names,
    validate_repository_document,
)


def _valid_insight() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "20260816-analysis-thumbnail",
        "date": "2026-08-16",
        "source": "analysis",
        "lever": "thumbnail",
        "finding": "CTR improved",
        "recommended_action": "Keep the layout",
        "evidence": "ctr=8.2",
        "status": "open",
    }


def test_registry_covers_and_compiles_every_repository_schema() -> None:
    files = {
        path.name
        for path in REPO_ROOT.rglob("*.schema.json")
        if ".venv" not in path.parts and "node_modules" not in path.parts
    }

    assert set(repository_schema_names()) == files
    compile_repository_schemas()
    assert all(load_repository_schema(schema)["$schema"].endswith("draft-07/schema#") for schema in RepositorySchema)


def test_validation_does_not_apply_schema_defaults_or_mutate_input() -> None:
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026-08-16",
                "axes": [{"key": "rain", "label": "Rain", "votes": 3}],
                "top_axis": "rain",
            }
        ],
    }
    original = copy.deepcopy(payload)

    validate_repository_document(RepositorySchema.WEEKLY_VOTE_LOG, payload)

    assert payload == original
    assert "notes" not in payload["entries"][0]


def test_invalid_document_raises_sanitized_domain_error_with_json_pointer() -> None:
    payload = _valid_insight()
    payload["finding"] = ""
    payload["evidence"] = "sk-live-secret-must-not-leak"

    with pytest.raises(DocumentValidationError) as captured:
        validate_repository_document(RepositorySchema.INSIGHTS_ENTRY, payload)

    message = str(captured.value)
    assert "schema keyword=minLength" in message
    assert "pointer=/finding" in message
    assert "sk-live-secret-must-not-leak" not in message


def test_analysis_and_audit_reports_have_fixed_owner_contracts() -> None:
    analysis = {
        "schema_version": 3,
        "generated_at": "2026-08-16T00:00:00Z",
        "summary": "分析サマリ",
        "inputs": {},
        "cli_outputs": {},
        "vpd_ranking": {},
        "win_pattern": {},
        "strategic_improvements": [],
        "next_collection_candidates": [],
        "action_plan": [],
        "strategic_discussion": [],
    }
    validate_repository_document(RepositorySchema.ANALYSIS_REPORT, analysis)

    audit = {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "audit_type": "alignment",
        "subject": "channel",
        "status": "FAIL",
        "summary": "不整合あり",
        "matrix": [{"check": "thumbnail", "status": "FAIL", "evidence": ["mismatch"], "next_action": "fix"}],
        "recommended_actions": ["thumbnail を更新"],
    }
    validate_repository_document(RepositorySchema.AUDIT_REPORT, audit)

    audit["matrix"] = [{"check": "thumbnail", "status": "UNKNOWN", "evidence": [], "next_action": None}]
    with pytest.raises(DocumentValidationError, match="pointer=/matrix/0/status"):
        validate_repository_document(RepositorySchema.AUDIT_REPORT, audit)


def test_channel_research_report_requires_traceable_comparison_evidence() -> None:
    report = {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "report_type": "benchmark",
        "summary": "競合比較",
        "source_provenance": [
            {"path": "data/benchmark_20260816.json", "collected_at": "2026-08-16", "claim": "再生数"}
        ],
        "competitor_comparison": [{"subject": "rival", "metric": "views", "value": 12000, "evidence_ids": ["ev-1"]}],
        "winning_patterns": [{"statement": "暗い配色", "evidence_ids": ["ev-1"], "confidence": "medium"}],
        "evidence": [{"id": "ev-1", "source_path": "data/benchmark_20260816.json", "observation": "12,000 views"}],
        "application_candidates": [{"statement": "暗い背景を比較する", "evidence_ids": ["ev-1"], "confidence": "low"}],
    }

    validate_repository_document(RepositorySchema.CHANNEL_RESEARCH_REPORT, report)

    report["competitor_comparison"] = [{"subject": "rival", "metric": "views", "value": 12000}]
    with pytest.raises(DocumentValidationError, match="pointer=/competitor_comparison/0"):
        validate_repository_document(RepositorySchema.CHANNEL_RESEARCH_REPORT, report)


def test_registry_rejects_unknown_schema_name_without_reading_external_file(tmp_path: Path) -> None:
    untrusted = tmp_path / "external.schema.json"
    untrusted.write_text(json.dumps({"type": "object"}), encoding="utf-8")

    with pytest.raises((TypeError, ValueError, KeyError)):
        validate_repository_document(str(untrusted), {})  # type: ignore[arg-type]
