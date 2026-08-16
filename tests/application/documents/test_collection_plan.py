from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.application.documents import migration
from youtube_automation.application.documents.collection_plan import (
    collection_plan_artifact_digest,
    finalize_collection_plan_selection,
    write_collection_plan_document,
)
from youtube_automation.application.documents.migration import MarkdownMigrationDecision
from youtube_automation.core.errors import DocumentMigrationError


def _candidate(*, plan_id: str = "plan-a", status: str = "selected") -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "collection_name": "Rain Focus",
        "theme_slug": "rain-focus",
        "track_count": 12,
        "music_engine": "suno",
        "music_direction": "雨音を邪魔しない低密度ambient",
        "video_direction": "夜の窓辺を固定構図で見せる",
        "thumbnail_direction": "青い窓と暖色lampを対比する",
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
    (tmp_path / "10-assets").mkdir()
    (tmp_path / "10-assets" / "planning-preview.png").write_bytes(b"preview")
    _state(state)

    draft = _document()
    draft["candidates"] = [_candidate(status="proposed")]
    result = write_collection_plan_document(
        target,
        state,
        lambda: draft,
        MarkdownMigrationDecision.NOT_REQUIRED,
    )
    assert json.loads(state.read_text(encoding="utf-8"))["planning"] == {}
    finalize_collection_plan_selection(
        target,
        state,
        proposal_id="plan-a",
        source="terminal",
        expected_artifact_digest=collection_plan_artifact_digest(target),
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
    (tmp_path / "10-assets").mkdir()
    (tmp_path / "10-assets" / "planning-preview.png").write_bytes(b"preview")
    _state(state)

    draft = _document(mode="batch")
    draft["candidates"] = [_candidate(status="proposed")]
    write_collection_plan_document(target, state, lambda: draft, MarkdownMigrationDecision.NOT_REQUIRED)
    finalize_collection_plan_selection(
        target,
        state,
        proposal_id="plan-a",
        source="automatic",
        expected_artifact_digest=collection_plan_artifact_digest(target),
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


def test_selected_candidate_cannot_bypass_review_finalizer(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    target.parent.mkdir()
    _state(state)
    selected = _document()
    selected_candidate = selected["candidates"][0]
    assert isinstance(selected_candidate, dict)
    selected_candidate["selection_source"] = "web"

    with pytest.raises(DocumentMigrationError, match="yt-collection-plan-select"):
        write_collection_plan_document(
            target,
            state,
            lambda: selected,
            MarkdownMigrationDecision.NOT_REQUIRED,
        )

    assert not target.exists()
    assert json.loads(state.read_text(encoding="utf-8"))["planning"] == {}


def test_proposed_plan_pair_is_published_for_review_without_state_projection(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    target.parent.mkdir()
    _state(state)
    before = state.read_bytes()
    draft = _document()
    draft["candidates"] = [_candidate(status="proposed")]

    result = write_collection_plan_document(
        target,
        state,
        lambda: draft,
        MarkdownMigrationDecision.NOT_REQUIRED,
    )

    assert result.value == "created"
    assert target.with_suffix(".html").is_file()
    html = target.with_suffix(".html").read_text(encoding="utf-8")
    for label in ("タイトル", "対象視聴者", "視聴シーン", "音楽方針", "映像方針", "サムネ方針", "根拠", "制約適合"):
        assert label in html
    assert '<img src="../10-assets/planning-preview.png"' in html
    assert state.read_bytes() == before


def test_web_selection_revalidates_digest_and_projects_existing_owner_order(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    preview = tmp_path / "10-assets" / "planning-preview.png"
    target.parent.mkdir()
    preview.parent.mkdir()
    preview.write_bytes(b"preview-a")
    _state(state)
    draft = _document()
    draft["candidates"] = [
        _candidate(plan_id="plan-a", status="proposed"),
        _candidate(plan_id="plan-b", status="proposed"),
    ]
    write_collection_plan_document(target, state, lambda: draft, MarkdownMigrationDecision.NOT_REQUIRED)
    digest = collection_plan_artifact_digest(target)

    finalize_collection_plan_selection(
        target,
        state,
        proposal_id="plan-b",
        source="web",
        expected_artifact_digest=digest,
    )

    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert [candidate["selection_status"] for candidate in persisted["candidates"]] == ["rejected", "selected"]
    assert persisted["candidates"][1]["selection_source"] == "web"
    assert json.loads(state.read_text(encoding="utf-8"))["planning"]["final_title"] == "Rain Focus"


def test_preview_digest_change_rejects_selection_without_state_or_pair_update(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    preview = tmp_path / "10-assets" / "planning-preview.png"
    target.parent.mkdir()
    preview.parent.mkdir()
    preview.write_bytes(b"preview-a")
    _state(state)
    draft = _document()
    draft["candidates"] = [_candidate(status="proposed")]
    write_collection_plan_document(target, state, lambda: draft, MarkdownMigrationDecision.NOT_REQUIRED)
    digest = collection_plan_artifact_digest(target)
    preview.write_bytes(b"preview-b")
    before_pair = (target.read_bytes(), target.with_suffix(".html").read_bytes())
    before_state = state.read_bytes()

    with pytest.raises(DocumentMigrationError, match="digest"):
        finalize_collection_plan_selection(
            target,
            state,
            proposal_id="plan-a",
            source="terminal",
            expected_artifact_digest=digest,
        )

    assert (target.read_bytes(), target.with_suffix(".html").read_bytes()) == before_pair
    assert state.read_bytes() == before_state


def test_preview_symlink_is_rejected_by_digest_boundary(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    outside = tmp_path / "outside.png"
    preview = tmp_path / "10-assets" / "planning-preview.png"
    target.parent.mkdir()
    preview.parent.mkdir()
    outside.write_bytes(b"outside")
    preview.symlink_to(outside)
    _state(state)
    draft = _document()
    draft["candidates"] = [_candidate(status="proposed")]
    write_collection_plan_document(target, state, lambda: draft, MarkdownMigrationDecision.NOT_REQUIRED)

    with pytest.raises(DocumentMigrationError, match="安全に解決"):
        collection_plan_artifact_digest(target)


def test_markdown_decline_preserves_markdown_and_workflow_state(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/plan_proposals.json"
    state = tmp_path / "workflow-state.json"
    target.parent.mkdir()
    markdown = target.with_suffix(".md")
    markdown.write_text("legacy", encoding="utf-8")
    _state(state)
    before = state.read_bytes()

    draft = _document()
    draft["candidates"] = [_candidate(status="proposed")]
    result = write_collection_plan_document(target, state, lambda: draft, MarkdownMigrationDecision.NO)

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
        draft = _document()
        draft["candidates"] = [_candidate(status="proposed")]
        write_collection_plan_document(target, state, lambda: draft, MarkdownMigrationDecision.NOT_REQUIRED)

    assert state.read_bytes() == before
    assert not target.exists()
    assert not target.with_suffix(".html").exists()
