"""コレクション企画 pair の公開後だけ workflow state を投影する。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from youtube_automation.application.documents.migration import (
    DocumentWriteResult,
    MarkdownMigrationDecision,
    write_operational_document,
)
from youtube_automation.core.errors import DocumentMigrationError
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.documents.schema_registry import RepositorySchema, validate_repository_document
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

_SELECTED = frozenset({"selected", "auto_selected"})


def write_collection_plan_document(
    json_path: Path,
    workflow_state_path: Path,
    build_document: Callable[[], object],
    migration_decision: MarkdownMigrationDecision,
) -> DocumentWriteResult:
    """企画 pair の完全な検証後に限り planning state を更新する。"""
    if json_path.name != "plan_proposals.json":
        raise DocumentMigrationError("企画正本の filename は plan_proposals.json である必要があります")

    def build_and_validate() -> object:
        document = build_document()
        validate_repository_document(RepositorySchema.COLLECTION_PLAN, document)
        _selected_candidate(document)
        _validate_references(document)
        return document

    result = write_operational_document(
        json_path,
        RepositorySchema.COLLECTION_PLAN,
        build_and_validate,
        migration_decision,
    )
    if result is DocumentWriteResult.DECLINED:
        return result
    document = read_published_json_document(json_path, RepositorySchema.COLLECTION_PLAN)
    selected = _selected_candidate(document)

    def project(state):
        planning = state.planning
        if planning is None:
            state["planning"] = {}
            planning = state.planning
        if planning is None:
            raise DocumentMigrationError("workflow-state.json::planning を初期化できません")
        planning["generated"] = True
        planning["final_title"] = selected["final_title"]
        planning["target_persona"] = selected["target_persona"]
        return state

    update_workflow_state(workflow_state_path, project)
    return result


def _selected_candidate(document: object) -> dict[str, object]:
    if not isinstance(document, dict) or not isinstance(document.get("candidates"), list):
        raise DocumentMigrationError("collection plan candidates が不正です")
    selected = [
        candidate
        for candidate in document["candidates"]
        if isinstance(candidate, dict) and candidate.get("selection_status") in _SELECTED
    ]
    if len(selected) != 1:
        raise DocumentMigrationError("collection plan は selected / auto_selected candidate を1件だけ必要とします")
    return selected[0]


def _validate_references(document: object) -> None:
    if not isinstance(document, dict):
        raise DocumentMigrationError("collection plan は JSON object で指定してください")
    candidates = document["candidates"]
    if not isinstance(candidates, list):
        raise DocumentMigrationError("collection plan candidates は array で指定してください")
    plan_ids: list[object] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise DocumentMigrationError("collection plan candidate は object で指定してください")
        plan_ids.append(candidate["plan_id"])
        evidence = candidate["evidence"]
        constraints = candidate["constraint_compliance"]
        if not isinstance(evidence, list) or not isinstance(constraints, list):
            raise DocumentMigrationError("candidate evidence/constraint_compliance は array が必要です")
        evidence_ids = {item["id"] for item in evidence if isinstance(item, dict)}
        for constraint in constraints:
            if not isinstance(constraint, dict):
                raise DocumentMigrationError("constraint compliance は object で指定してください")
            references = constraint["evidence_ids"]
            if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
                raise DocumentMigrationError("constraint evidence_ids は string array で指定してください")
            missing = sorted(set(references) - evidence_ids)
            if missing:
                raise DocumentMigrationError(f"constraint evidence_ids に未定義 ID があります: {', '.join(missing)}")
    if len(plan_ids) != len(set(plan_ids)):
        raise DocumentMigrationError("collection plan の plan_id は一意である必要があります")
