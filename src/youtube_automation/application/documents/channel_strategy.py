"""チャンネル戦略文書の schema・相互参照を一つの保存境界で検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from youtube_automation.application.documents.migration import (
    DocumentWriteResult,
    MarkdownMigrationDecision,
    write_operational_document,
)
from youtube_automation.core.errors import DocumentMigrationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema, validate_repository_document
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

_RELATIVE_TARGETS = {
    "direction": Path("docs/channel/channel-direction.json"),
    "persona": Path("docs/channel/personas/persona-definition.json"),
    "scene": Path("docs/plans/viewing-scene-matrix.json"),
    "constraints": Path("docs/channel/creative-constraints.json"),
}


def validate_channel_strategy_document_type(document: object, expected_type: str) -> dict[str, object]:
    """Validate the shared strategy document type contract and return an object."""
    if not isinstance(document, dict):
        raise DocumentMigrationError("channel strategy document は JSON object で指定してください")
    if document.get("document_type") != expected_type:
        raise DocumentMigrationError(f"参照先 {expected_type} の document_type が不正です")
    return document


def validate_persona_scene_references(
    persona: object,
    scene: object,
    *,
    require_nonempty: bool = False,
) -> None:
    """Validate producer-owned persona/scene references.

    A persona may intentionally select a subset of the scenes.  The write boundary
    also permits an empty selection while the producer is between its persona and
    scene phases; consumers may request a completed, non-empty chain.
    """
    persona_document = validate_channel_strategy_document_type(persona, "persona")
    scene_document = validate_channel_strategy_document_type(scene, "scene")
    persona_value = persona_document.get("persona")
    if not isinstance(persona_value, dict) or scene_document.get("persona_id") != persona_value.get("id"):
        raise DocumentMigrationError("persona_id が persona 正本を参照していません")
    persona_scene_ids = _string_set(persona_document.get("scene_ids"), "scene_ids")
    scene_ids = _ids(scene_document.get("scenes"), "scenes")
    _require_subset(persona_scene_ids, scene_ids, "scene_ids")
    if require_nonempty and (not persona_scene_ids or not scene_ids):
        raise DocumentMigrationError("persona/scene の参照は空にできません")


def write_channel_strategy_document(
    json_path: Path,
    build_document: Callable[[], object],
    migration_decision: MarkdownMigrationDecision,
) -> DocumentWriteResult:
    """候補の schema と既存 strategy pair への参照を検証して原子的に公開する。"""
    root = _channel_root(json_path)

    def build_and_validate() -> object:
        document = build_document()
        validate_repository_document(RepositorySchema.CHANNEL_STRATEGY, document)
        if not isinstance(document, dict):
            raise DocumentMigrationError("channel strategy document は JSON object で指定してください")
        document_type = document.get("document_type")
        expected = _RELATIVE_TARGETS.get(document_type) if isinstance(document_type, str) else None
        if expected is None or root / expected != json_path:
            raise DocumentMigrationError("document_type と channel strategy の公開先 path が一致しません")
        _validate_evidence_references(document)
        _validate_strategy_references(root, document)
        return document

    return write_operational_document(
        json_path,
        RepositorySchema.CHANNEL_STRATEGY,
        build_and_validate,
        migration_decision,
    )


def _channel_root(path: Path) -> Path:
    relative = Path("docs") / "channel"
    for parent in (path.parent, *path.parents):
        if (parent / relative).is_dir() or parent / _RELATIVE_TARGETS["persona"] == path:
            return parent
    raise DocumentMigrationError("channel strategy の公開先は CHANNEL_DIR 配下にしてください")


def _published(root: Path, document_type: str) -> dict[str, object]:
    path = root / _RELATIVE_TARGETS[document_type]
    try:
        document = read_published_json_document(path, RepositorySchema.CHANNEL_STRATEGY)
    except Exception as error:
        raise DocumentMigrationError(f"参照先 {document_type} の検証済み JSON+HTML pair が必要です") from error
    return validate_channel_strategy_document_type(document, document_type)


def _validate_strategy_references(root: Path, document: dict[str, object]) -> None:
    document_type = document["document_type"]
    if document_type == "persona":
        scene_ids = _string_set(document.get("scene_ids", []), "scene_ids")
        scene_path = root / _RELATIVE_TARGETS["scene"]
        if scene_ids or scene_path.exists() or scene_path.with_suffix(".html").exists():
            scene = _published(root, "scene")
            validate_persona_scene_references(document, scene)
        return
    if document_type not in {"scene", "constraints"}:
        return
    persona = _published(root, "persona")
    if document_type == "scene":
        # Scene is the producer of the candidate scene ID set.  At this write
        # boundary it may remove or rename scenes that the currently published
        # persona still references; the persona pair is updated in the next
        # phase.  Only its ownership reference is enforceable here.
        persona_value = persona.get("persona")
        if not isinstance(persona_value, dict) or document.get("persona_id") != persona_value.get("id"):
            raise DocumentMigrationError("persona_id が persona 正本を参照していません")
    else:
        persona_value = persona.get("persona")
        if not isinstance(persona_value, dict) or document.get("persona_id") != persona_value.get("id"):
            raise DocumentMigrationError("persona_id が persona 正本を参照していません")
    if document_type == "constraints":
        scene = _published(root, "scene")
        _require_subset(
            _string_set(document.get("scene_ids"), "scene_ids"),
            _ids(scene.get("scenes"), "scenes"),
            "scene_ids",
        )
        constraint_ids = [item.get("id") for item in _objects(document.get("constraints"), "constraints")]
        if len(constraint_ids) != len(set(constraint_ids)):
            raise DocumentMigrationError("constraint ID は文書内で一意である必要があります")


def _validate_evidence_references(document: dict[str, object]) -> None:
    evidence_ids = _ids(document.get("evidence"), "evidence")
    for field in ("scenes", "constraints"):
        for item in _objects(document.get(field, []), field):
            _require_subset(_string_set(item.get("evidence_ids"), "evidence_ids"), evidence_ids, "evidence_ids")


def _objects(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DocumentMigrationError(f"{field} は object array で指定してください")
    return value


def _ids(value: object, field: str) -> set[str]:
    return {str(item.get("id")) for item in _objects(value, field)}


def _string_set(value: object, field: str) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DocumentMigrationError(f"{field} は string array で指定してください")
    return set(value)


def _require_subset(values: Iterable[str], allowed: set[str], field: str) -> None:
    missing = sorted(set(values) - allowed)
    if missing:
        raise DocumentMigrationError(f"{field} に未定義 ID があります: {', '.join(missing)}")
