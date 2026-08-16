from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.domains.documents.rendering import render_repository_document
from youtube_automation.domains.documents.schema_registry import RepositorySchema


def write_video_description_pair(
    documentation: Path,
    *,
    title: str = "Rain Focus — Complete Collection",
    description: str = "Opening\n\n00:00 Quiet Rain\n\n#Focus",
    tags: list[str] | None = None,
    localizations: dict[str, object] | None = None,
    tracks: list[dict[str, object]] | None = None,
) -> Path:
    document = {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "collection_id": documentation.parent.name,
        "title": title,
        "description": description,
        "description_sections": [{"id": "body", "heading": "Description", "body": description}],
        "tracks": [{"position": 1, "start": "00:00", "title": "Quiet Rain"}] if tracks is None else tracks,
        "tags": ["focus music"] if tags is None else tags,
        "localizations": {} if localizations is None else localizations,
        "provenance": {"producer": "video", "source_paths": ["workflow-state.json"]},
        "quality": {
            "status": "pass",
            "checks": [{"id": "metadata", "status": "pass", "message": "fixture verified"}],
        },
    }
    source = documentation / "descriptions.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    source.with_suffix(".html").write_text(
        render_repository_document(RepositorySchema.VIDEO_DESCRIPTION, document),
        encoding="utf-8",
    )
    return source
