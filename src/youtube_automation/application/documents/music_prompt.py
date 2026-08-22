"""音楽 prompt pair の review gate と workflow-state 投影。"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping
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

MachineVerifier = Callable[[object], None]
ReviewDecision = Literal["approve", "reject"]
ReviewSource = Literal["web", "terminal", "automatic"]
_FILENAMES = {
    "suno": "suno-prompts.json",
    "lyria": "lyria-prompt.json",
    "minimax": "minimax-prompt.json",
}


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
    """verify と semantic review が通った未承認 prompt pair を公開する。"""

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
    return result


def music_prompt_artifact_digest(json_path: Path) -> str:
    """検証済み prompt pair の正本 JSON digest を返す。"""
    read_published_json_document(json_path, RepositorySchema.MUSIC_PROMPT)
    digest = hashlib.sha256()
    with json_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finalize_music_prompt_review(
    json_path: Path,
    workflow_state_path: Path,
    *,
    decision: ReviewDecision,
    source: ReviewSource,
    expected_artifact_digest: str,
) -> None:
    """review 済み digest を再検証し、承認時だけ既存 state owner を実行する。"""
    if decision not in {"approve", "reject"}:
        raise DocumentMigrationError(f"music prompt review decisionが不正です: {decision}")
    if source not in {"web", "terminal", "automatic"}:
        raise DocumentMigrationError(f"music prompt review sourceが不正です: {source}")
    current_digest = music_prompt_artifact_digest(json_path)
    if not secrets.compare_digest(current_digest, expected_artifact_digest):
        raise DocumentMigrationError("music prompt JSON digestがreview時点から変わりました")
    document = read_published_json_document(json_path, RepositorySchema.MUSIC_PROMPT)
    _engine, entries = _reviewed_entries(document)
    require_recorded_machine_verification(document)
    _require_semantic_pass(entries)
    if decision == "reject":
        return

    def project(state):
        state.set_asset("music_prompts", True)
        return state

    update_workflow_state(workflow_state_path, project)


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
