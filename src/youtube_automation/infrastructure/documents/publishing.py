"""構造化 JSON と同 basename の HTML を原子的に公開する。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.rendering import render_repository_document, validate_generated_html
from youtube_automation.domains.documents.schema_registry import RepositorySchema


def publish_json_document(source: Path, schema: RepositorySchema) -> Path:
    """JSON を読み、検証済み HTML を同 directory・basename へ原子的に保存する。"""
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DocumentRenderError(f"structured document JSON を読めません: {source}") from error
    html = render_repository_document(schema, document)
    destination = source.with_suffix(".html")
    _write_html_atomically(destination, html)
    return destination


def read_published_json_document(source: Path, schema: RepositorySchema) -> object:
    """検証済み JSON+HTML pair を読み、AI/下流入力には JSON だけを返す。"""
    destination = source.with_suffix(".html")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        persisted_html = destination.read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DocumentRenderError(f"structured document pair を読めません: {source}") from error
    expected_html = render_repository_document(schema, document)
    if persisted_html != expected_html:
        raise DocumentRenderError(f"structured document JSON と HTML が対応していません: {source}")
    return document


def _write_html_atomically(destination: Path, html: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(html)
            stream.flush()
            os.fsync(stream.fileno())
        persisted = temporary.read_text(encoding="utf-8")
        if persisted != html:
            raise DocumentRenderError("temporary HTML の再読込結果が一致しません")
        validate_generated_html(persisted)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
