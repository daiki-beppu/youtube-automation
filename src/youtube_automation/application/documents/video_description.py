"""動画説明 pair の品質 gate、reader、workflow-state 投影。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from youtube_automation.application.documents.migration import (
    DocumentWriteResult,
    MarkdownMigrationDecision,
    write_operational_document,
)
from youtube_automation.application.documents.projection import publish_and_project
from youtube_automation.core.errors import DocumentMigrationError
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.documents.schema_registry import RepositorySchema, validate_repository_document
from youtube_automation.domains.documents.video_description import (
    read_video_description_metadata as _read_video_description_metadata,
)
from youtube_automation.domains.documents.video_description import (
    require_quality_pass,
)
from youtube_automation.infrastructure.documents.publishing import read_published_json_document


def write_video_description_document(
    json_path: Path,
    workflow_state_path: Path,
    build_document: Callable[[], object],
    migration_decision: MarkdownMigrationDecision,
) -> DocumentWriteResult:
    """検証済み description pair の公開後だけ description state を完了する。"""
    if json_path.name != "descriptions.json":
        raise DocumentMigrationError("動画説明正本の filename は descriptions.json である必要があります")

    def build_and_validate() -> object:
        document = build_document()
        validate_repository_document(RepositorySchema.VIDEO_DESCRIPTION, document)
        require_quality_pass(document)
        return document

    def publish() -> DocumentWriteResult:
        result = write_operational_document(
            json_path,
            RepositorySchema.VIDEO_DESCRIPTION,
            build_and_validate,
            migration_decision,
        )
        if result is not DocumentWriteResult.DECLINED:
            persisted = read_published_json_document(json_path, RepositorySchema.VIDEO_DESCRIPTION)
            require_quality_pass(persisted)
        return result

    def project(result: DocumentWriteResult) -> None:
        if result is DocumentWriteResult.DECLINED:
            return

        def transition(state):
            state.set_asset("description", True)
            return state

        update_workflow_state(workflow_state_path, transition)

    return publish_and_project(publish, project)


def read_video_description_metadata(json_path: Path) -> dict[str, object]:
    """domain-owned validated reader の application facade。"""
    return _read_video_description_metadata(json_path)
