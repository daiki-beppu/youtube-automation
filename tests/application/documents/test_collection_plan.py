from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.application.documents import migration
from youtube_automation.application.documents.collection_plan import write_collection_plan_document
from youtube_automation.application.documents.migration import MarkdownMigrationDecision
from youtube_automation.core.errors import DocumentMigrationError


def _candidate(*, plan_id: str = "plan-a", status: str = "selected") -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "collection_name": "Rain Focus",
        "theme_slug": "rain-focus",
        "track_count": 12,
        "music_engine": "suno",
        "final_title": "Rain Focus",
        "target_persona": "persona-primary",
        "viewing_scene": "scene-night",
        "constraint_compliance": [{"constraint_id": "audio-001", "status": "pass", "evidence_ids": ["ev-1"]}],
        "evidence": [{"id": "ev-1", "source_path": "reports/analysis.json", "observation": "retention"}],
        "insight_ids": ["insight-1"],
        "preview_assets": ["10-assets/planning-preview.png"],
        "selection_status": status,
        "selection_reason": "推奨順1位",
    }


def _document(*, mode: str = "normal") -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "mode": mode,
        "collection_id": "20260816-rain-focus",
        "provenance": {"producer": "wf-new", "batch_id": "batch-1" if mode == "batch" else None},
        "candidates": [_candidate()],
    }


def _state(path: Path) -> None:
    path.write_text(json.dumps({"phase": "planning", "planning": {}, "unknown": {"keep": True}}), encoding="utf-8")


def test_normal_plan_pair_is_verified_before_workflow_state_projection(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    target.parent.mkdir()
    _state(state)

    result = write_collection_plan_document(
        target,
        state,
        _document,
        MarkdownMigrationDecision.NOT_REQUIRED,
    )

    persisted = json.loads(state.read_text())
    assert result.value == "created"
    assert target.with_suffix(".html").is_file()
    assert persisted["planning"] == {
        "generated": True,
        "final_title": "Rain Focus",
        "target_persona": "persona-primary",
    }
    assert persisted["unknown"] == {"keep": True}


def test_batch_projection_uses_same_plan_field_names(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    target.parent.mkdir()
    _state(state)

    write_collection_plan_document(
        target, state, lambda: _document(mode="batch"), MarkdownMigrationDecision.NOT_REQUIRED
    )

    candidate = json.loads(target.read_text())["candidates"][0]
    assert candidate["plan_id"] == "plan-a"
    assert candidate["final_title"] == "Rain Focus"
    assert candidate["target_persona"] == "persona-primary"


def test_invalid_plan_does_not_update_workflow_state_or_publish_pair(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    target.parent.mkdir()
    _state(state)
    before = state.read_bytes()
    invalid = _document()
    invalid["candidates"] = [_candidate(status="rejected")]

    with pytest.raises(DocumentMigrationError, match="selected"):
        write_collection_plan_document(
            target,
            state,
            lambda: invalid,
            MarkdownMigrationDecision.NOT_REQUIRED,
        )

    assert state.read_bytes() == before
    assert not target.exists()
    assert not target.with_suffix(".html").exists()


def test_markdown_decline_preserves_markdown_and_workflow_state(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    target.parent.mkdir()
    markdown = target.with_suffix(".md")
    markdown.write_text("legacy", encoding="utf-8")
    _state(state)
    before = state.read_bytes()

    result = write_collection_plan_document(target, state, _document, MarkdownMigrationDecision.NO)

    assert result.value == "declined"
    assert markdown.read_text() == "legacy"
    assert state.read_bytes() == before


def test_html_generation_failure_rolls_back_pair_and_does_not_update_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    target.parent.mkdir()
    _state(state)
    before = state.read_bytes()

    def fail_render(_schema: object, _document: object) -> str:
        raise DocumentMigrationError("render failed")

    monkeypatch.setattr(migration, "render_repository_document", fail_render)

    with pytest.raises(DocumentMigrationError, match="render failed"):
        write_collection_plan_document(target, state, _document, MarkdownMigrationDecision.NOT_REQUIRED)

    assert state.read_bytes() == before
    assert not target.exists()
    assert not target.with_suffix(".html").exists()
