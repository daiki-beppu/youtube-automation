"""コレクション企画 pair の公開後だけ workflow state を投影する。"""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Literal

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
SelectionSource = Literal["web", "terminal", "automatic"]


def write_collection_plan_document(
    json_path: Path,
    workflow_state_path: Path,
    build_document: Callable[[], object],
    migration_decision: MarkdownMigrationDecision,
) -> DocumentWriteResult:
    """Publish an all-proposed draft pair without changing planning state."""
    return _write_collection_plan_document(
        json_path,
        workflow_state_path,
        build_document,
        migration_decision,
        selection_finalized=False,
    )


def _write_collection_plan_document(
    json_path: Path,
    workflow_state_path: Path,
    build_document: Callable[[], object],
    migration_decision: MarkdownMigrationDecision,
    *,
    selection_finalized: bool,
) -> DocumentWriteResult:
    """Publish a draft or a broker-validated selection, then project state."""
    if json_path.name != "plan_proposals.json":
        raise DocumentMigrationError("企画正本の filename は plan_proposals.json である必要があります")

    def build_and_validate() -> object:
        document = build_document()
        validate_repository_document(RepositorySchema.COLLECTION_PLAN, document)
        selected = _selected_candidate_or_draft(document)
        if selected is not None and not selection_finalized:
            raise DocumentMigrationError("企画確定はyt-collection-plan-selectを使用してください")
        if selected is None and json_path.is_file():
            current = read_published_json_document(json_path, RepositorySchema.COLLECTION_PLAN)
            if _selected_candidate_or_draft(current) is not None:
                raise DocumentMigrationError("確定済みcollection planをdraftへ戻せません")
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
    selected = _selected_candidate_or_draft(document)
    if selected is None:
        return result

    def project(state):
        state.record_collection_plan(
            final_title=selected["final_title"],
            target_persona=selected["target_persona"],
        )
        return state

    update_workflow_state(workflow_state_path, project)
    return result


def collection_plan_artifact_digest(json_path: Path) -> str:
    """Hash the validated JSON pair plus every declared preview asset."""
    document = read_published_json_document(json_path, RepositorySchema.COLLECTION_PLAN)
    digest = hashlib.sha256()
    digest.update(json_path.read_bytes())
    for reference, preview in _preview_paths(json_path, document):
        digest.update(b"\0preview\0")
        digest.update(reference.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(preview).encode("ascii"))
    return digest.hexdigest()


def collection_plan_candidate_digest(json_path: Path, candidate: dict[str, object]) -> str:
    digest = hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    document = {"candidates": [candidate]}
    for reference, preview in _preview_paths(json_path, document):
        digest.update(b"\0preview\0")
        digest.update(reference.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(preview).encode("ascii"))
    return digest.hexdigest()


def finalize_collection_plan_selection(
    json_path: Path,
    workflow_state_path: Path,
    *,
    proposal_id: str,
    source: SelectionSource,
    expected_artifact_digest: str,
) -> DocumentWriteResult:
    """Revalidate a reviewed proposal and use the existing pair→state owner order."""
    if source not in {"web", "terminal", "automatic"}:
        raise DocumentMigrationError(f"selection sourceが不正です: {source}")
    current_digest = collection_plan_artifact_digest(json_path)
    if not secrets.compare_digest(current_digest, expected_artifact_digest):
        raise DocumentMigrationError("collection plan JSON / preview digestがreview時点から変わりました")
    document = read_published_json_document(json_path, RepositorySchema.COLLECTION_PLAN)
    if not isinstance(document, dict) or not isinstance(document.get("candidates"), list):
        raise DocumentMigrationError("collection plan candidates が不正です")
    updated = copy.deepcopy(document)
    candidates = updated["candidates"]
    matches = [
        candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("plan_id") == proposal_id
    ]
    if len(matches) != 1 or matches[0].get("selection_status") != "proposed":
        raise DocumentMigrationError(f"未選択proposal_idではありません: {proposal_id}")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise DocumentMigrationError("collection plan candidate は object で指定してください")
        selected = candidate is matches[0]
        candidate["selection_status"] = (
            "auto_selected" if selected and source == "automatic" else "selected" if selected else "rejected"
        )
        if selected:
            candidate["selection_source"] = source
            candidate["selection_reason"] = f"{source} reviewでproposal_idを検証して確定"
    return _write_collection_plan_document(
        json_path,
        workflow_state_path,
        lambda: updated,
        MarkdownMigrationDecision.NOT_REQUIRED,
        selection_finalized=True,
    )


def _selected_candidate_or_draft(document: object) -> dict[str, object] | None:
    if not isinstance(document, dict) or not isinstance(document.get("candidates"), list):
        raise DocumentMigrationError("collection plan candidates が不正です")
    candidates = document["candidates"]
    selected = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("selection_status") in _SELECTED
    ]
    if len(selected) == 1:
        if selected[0].get("selection_source") not in {"web", "terminal", "automatic"}:
            raise DocumentMigrationError("確定candidateにはselection_sourceが必要です")
        return selected[0]
    if (
        not selected
        and candidates
        and all(
            isinstance(candidate, dict) and candidate.get("selection_status") == "proposed" for candidate in candidates
        )
    ):
        return None
    raise DocumentMigrationError(
        "collection plan は全件proposedまたはselected / auto_selected candidateを1件だけ必要とします"
    )


def _preview_paths(json_path: Path, document: object) -> tuple[tuple[str, Path], ...]:
    if not isinstance(document, dict) or not isinstance(document.get("candidates"), list):
        raise DocumentMigrationError("collection plan candidates が不正です")
    collection_root = json_path.parent.parent.resolve()
    result: list[tuple[str, Path]] = []
    for candidate in document["candidates"]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("preview_assets"), list):
            raise DocumentMigrationError("candidate preview_assets はarrayで指定してください")
        for value in candidate["preview_assets"]:
            if not isinstance(value, str):
                raise DocumentMigrationError("preview asset referenceはstringで指定してください")
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise DocumentMigrationError(f"preview asset pathがcollection外です: {value}")
            unresolved = collection_root / relative
            preview = unresolved.resolve()
            if unresolved.is_symlink() or not preview.is_relative_to(collection_root) or not preview.is_file():
                raise DocumentMigrationError(f"preview assetを安全に解決できません: {value}")
            result.append((value, preview))
    return tuple(result)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
