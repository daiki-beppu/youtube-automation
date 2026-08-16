"""Skill が生成する運用文書の JSON + HTML 移行 workflow。"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from youtube_automation.core.errors import DocumentMigrationError
from youtube_automation.domains.documents.rendering import (
    render_repository_document,
    validate_generated_html,
)
from youtube_automation.domains.documents.schema_registry import (
    RepositorySchema,
    validate_repository_document,
)
from youtube_automation.infrastructure.filesystem import write_verified_text_files_transactionally


class MarkdownMigrationDecision(str, Enum):
    """既存 Markdown の移行に対する利用者の明示判断。"""

    YES = "yes"
    NO = "no"
    NOT_REQUIRED = "not-required"


class DocumentWriteResult(str, Enum):
    """運用文書 writer の状態遷移結果。"""

    CREATED = "created"
    MIGRATED = "migrated"
    DECLINED = "declined"
    UPDATED = "updated"


def write_operational_document(
    json_path: Path,
    schema: RepositorySchema,
    build_document: Callable[[], object],
    migration_decision: MarkdownMigrationDecision,
    *,
    allow_legacy_json_markdown: bool = False,
) -> DocumentWriteResult:
    """新規作成・明示移行・移行済み更新を rollback 可能な一操作で行う。"""
    if json_path.suffix != ".json":
        raise DocumentMigrationError("運用文書の正本 path は .json で指定してください")
    html_path = json_path.with_suffix(".html")
    markdown_path = json_path.with_suffix(".md")
    paths = (json_path, html_path, markdown_path)
    if any(path.is_symlink() for path in paths):
        raise DocumentMigrationError("運用文書 path に symlink は使用できません")

    state = _resolve_state(
        json_path,
        html_path,
        markdown_path,
        allow_legacy_json_markdown=allow_legacy_json_markdown,
    )
    if state is DocumentWriteResult.MIGRATED:
        if migration_decision is MarkdownMigrationDecision.NO:
            return DocumentWriteResult.DECLINED
        if migration_decision is not MarkdownMigrationDecision.YES:
            raise DocumentMigrationError("既存 Markdown の移行には明示的な yes/no が必要です")
    elif migration_decision is not MarkdownMigrationDecision.NOT_REQUIRED:
        raise DocumentMigrationError("新規作成・移行済み更新では Markdown 移行判断を指定しません")

    if state is DocumentWriteResult.UPDATED:
        _validate_existing_pair(json_path, html_path, schema)

    document = build_document()
    json_text = _serialize_document(document)
    html_text = render_repository_document(schema, document)

    def verify_and_finalize() -> None:
        _verify_published_pair(json_path, html_path, schema, json_text, html_text)
        if state is DocumentWriteResult.MIGRATED:
            markdown_path.unlink()

    write_verified_text_files_transactionally(
        {json_path: json_text, html_path: html_text},
        verify_and_finalize,
    )
    return state


def _resolve_state(
    json_path: Path,
    html_path: Path,
    markdown_path: Path,
    *,
    allow_legacy_json_markdown: bool,
) -> DocumentWriteResult:
    existing = (json_path.exists(), html_path.exists(), markdown_path.exists())
    if existing == (False, False, False):
        return DocumentWriteResult.CREATED
    if existing == (False, False, True):
        return DocumentWriteResult.MIGRATED
    if allow_legacy_json_markdown and existing == (True, False, True):
        return DocumentWriteResult.MIGRATED
    if existing == (True, True, False):
        return DocumentWriteResult.UPDATED
    raise DocumentMigrationError("運用文書は none / Markdown-only / JSON+HTML pair の状態である必要があります")


def _serialize_document(document: object) -> str:
    try:
        return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as error:
        raise DocumentMigrationError("運用文書を JSON object として直列化できません") from error


def _validate_existing_pair(json_path: Path, html_path: Path, schema: RepositorySchema) -> None:
    try:
        document = json.loads(json_path.read_text(encoding="utf-8"))
        html = html_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DocumentMigrationError("移行済み運用文書 pair を再読込できません") from error
    expected_html = render_repository_document(schema, document)
    if html != expected_html:
        raise DocumentMigrationError("移行済み運用文書の JSON と HTML が対応していません")


def _verify_published_pair(
    json_path: Path,
    html_path: Path,
    schema: RepositorySchema,
    expected_json: str,
    expected_html: str,
) -> None:
    try:
        persisted_json = json_path.read_text(encoding="utf-8")
        persisted_html = html_path.read_text(encoding="utf-8")
        document = json.loads(persisted_json)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DocumentMigrationError("公開した運用文書 pair を再読込できません") from error
    if persisted_json != expected_json or persisted_html != expected_html:
        raise DocumentMigrationError("公開した運用文書 pair が生成内容と一致しません")
    validate_repository_document(schema, document)
    validate_generated_html(persisted_html)
