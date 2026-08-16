"""検証済み動画説明 document の typed reader。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from youtube_automation.core.errors import DocumentMigrationError
from youtube_automation.domains.documents.published import read_published_json_document
from youtube_automation.domains.documents.schema_registry import RepositorySchema


def read_video_description_metadata(json_path: Path) -> dict[str, object]:
    """validated JSON+HTML pair から upload 用 metadata だけを返す。"""
    document = read_video_description_document(json_path)
    if not isinstance(document, Mapping):
        raise DocumentMigrationError("動画説明は JSON object で指定してください")
    return {
        "title": document["title"],
        "description": document["description"],
        "tags": document["tags"],
        "localizations": document["localizations"],
    }


def read_video_description_document(json_path: Path) -> Mapping[str, object]:
    """validated pair の完全な JSON document を返す。"""
    document = read_published_json_document(json_path, RepositorySchema.VIDEO_DESCRIPTION)
    require_quality_pass(document)
    if not isinstance(document, Mapping):
        raise DocumentMigrationError("動画説明は JSON object で指定してください")
    return document


def require_quality_pass(document: object) -> None:
    """全 quality check が成功していない文書を downstream から拒否する。"""
    if not isinstance(document, Mapping):
        raise DocumentMigrationError("動画説明は JSON object で指定してください")
    quality = document.get("quality")
    if not isinstance(quality, Mapping) or quality.get("status") != "pass":
        raise DocumentMigrationError("動画説明の quality status が PASS ではありません")
    checks = quality.get("checks")
    if not isinstance(checks, list) or any(
        not isinstance(check, Mapping) or check.get("status") != "pass" for check in checks
    ):
        raise DocumentMigrationError("動画説明の quality check に FAIL があります")
