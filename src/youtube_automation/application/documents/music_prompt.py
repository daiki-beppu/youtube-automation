"""音楽 prompt pair の review gate と workflow-state 投影。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
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

MachineVerifier = Callable[[object], None]
_FILENAMES = {"suno": "suno-prompts.json", "lyria": "lyria-prompt.json"}


def require_recorded_machine_verification(document: object) -> None:
    """candidate に記録された entry ごとの機械 verify 成功を検証する。"""
    _engine, entries = _reviewed_entries(document)
    for index, entry in enumerate(entries, 1):
        review = entry.get("review") if isinstance(entry, Mapping) else None
        if not isinstance(review, Mapping) or review.get("verify_status") != "pass":
            raise DocumentMigrationError(f"music prompt entry {index} の machine verify が PASS ではありません")


def write_music_prompt_document(
    json_path: Path,
    workflow_state_path: Path,
    build_document: Callable[[], object],
    migration_decision: MarkdownMigrationDecision,
    *,
    machine_verify: MachineVerifier,
) -> DocumentWriteResult:
    """verify と semantic review が通った prompt pair だけを成功状態へ進める。"""

    def build_and_validate() -> object:
        document = build_document()
        validate_repository_document(RepositorySchema.MUSIC_PROMPT, document)
        machine_verify(document)
        engine, entries = _reviewed_entries(document)
        expected_filename = _FILENAMES[engine]
        if json_path.name != expected_filename:
            raise DocumentMigrationError(f"{engine} prompt の filename は {expected_filename} である必要があります")
        _require_semantic_pass(entries)
        return document

    result = write_operational_document(
        json_path,
        RepositorySchema.MUSIC_PROMPT,
        build_and_validate,
        migration_decision,
        allow_legacy_json_markdown=True,
    )
    if result is DocumentWriteResult.DECLINED:
        return result
    persisted = read_published_json_document(json_path, RepositorySchema.MUSIC_PROMPT)
    _engine, entries = _reviewed_entries(persisted)
    _require_semantic_pass(entries)

    def project(state):
        assets = state.assets
        if assets is None:
            state["assets"] = {}
            assets = state.assets
        if assets is None:
            raise DocumentMigrationError("workflow-state.json::assets を初期化できません")
        assets["music_prompts"] = True
        return state

    update_workflow_state(workflow_state_path, project)
    return result


def _reviewed_entries(document: object) -> tuple[str, list[object]]:
    if not isinstance(document, Mapping):
        raise DocumentMigrationError("music prompt は JSON object で指定してください")
    engine = document.get("engine")
    entries = document.get("entries")
    if engine not in _FILENAMES or not isinstance(entries, list):
        raise DocumentMigrationError("music prompt の engine / entries が不正です")
    return str(engine), entries


def _require_semantic_pass(entries: list[object]) -> None:
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, Mapping):
            raise DocumentMigrationError(f"music prompt entry {index} が object ではありません")
        review = entry.get("review")
        if not isinstance(review, Mapping) or review.get("semantic_status") != "pass":
            raise DocumentMigrationError(f"music prompt entry {index} の semantic review が PASS ではありません")
