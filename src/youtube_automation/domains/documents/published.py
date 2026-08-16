"""検証済み JSON+HTML pair の domain reader。"""

from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.rendering import render_repository_document
from youtube_automation.domains.documents.schema_registry import RepositorySchema


def read_published_json_document(source: Path, schema: RepositorySchema) -> object:
    """対応HTMLを再生成照合し、AI/下流入力には検証済みJSONだけを返す。"""
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
