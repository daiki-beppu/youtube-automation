"""Validated downstream reader for the canonical Suno prompt document."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from youtube_automation.core.errors import DocumentRenderError, DocumentValidationError
from youtube_automation.domains.documents.published import read_published_json_document
from youtube_automation.domains.documents.schema_registry import RepositorySchema

DOCUMENTATION_DIRNAME = "20-documentation"
SUNO_PROMPTS_JSON_FILENAME = "suno-prompts.json"


def suno_prompts_path(collection_dir: Path) -> Path:
    return collection_dir / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME


def normalize_suno_prompt_entries(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return data["entries"]
    raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: root must be a list or object with entries")


def read_suno_prompt_entries(collection_dir: Path) -> list[Any]:
    path = suno_prompts_path(collection_dir)
    try:
        data = read_published_json_document(path, RepositorySchema.MUSIC_PROMPT)
    except (DocumentRenderError, DocumentValidationError, OSError, ValueError) as exc:
        raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: expected validated JSON+HTML pair") from exc
    return normalize_suno_prompt_entries(data)


def read_suno_prompt_delivery_payload(collection_dir: Path) -> object:
    """検証済み正本から Suno helper 公開契約だけを投影する。"""
    return read_suno_prompt_delivery_payload_from_path(suno_prompts_path(collection_dir))


def read_suno_prompt_delivery_payload_from_path(path: Path) -> object:
    """明示された検証済み正本から Suno helper 公開契約だけを投影する。"""
    try:
        document = read_published_json_document(path, RepositorySchema.MUSIC_PROMPT)
    except (DocumentRenderError, DocumentValidationError, OSError, ValueError) as exc:
        raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: expected validated JSON+HTML pair") from exc
    if not isinstance(document, dict):
        raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: root must be an object")
    delivered = []
    for entry in normalize_suno_prompt_entries(document):
        if not isinstance(entry, dict):
            raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: entry must be an object")
        options = entry.get("options")
        if not isinstance(options, dict):
            raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: options must be an object")
        delivered.append(
            {
                key: value
                for key, value in {**entry, **options}.items()
                if key not in {"options", "review", "track_role"}
            }
        )
    duration_filter = document.get("duration_filter")
    if duration_filter is None:
        return delivered
    return {"entries": delivered, "duration_filter": duration_filter}
