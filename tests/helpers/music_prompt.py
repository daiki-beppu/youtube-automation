from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.domains.documents.rendering import render_repository_document
from youtube_automation.domains.documents.schema_registry import RepositorySchema


def write_suno_prompt_pair(
    documentation: Path,
    entries: list[dict[str, object]],
    *,
    duration_filter: object | None = None,
) -> None:
    normalized = [
        {
            "style": "fixture style",
            "lyrics": "",
            "options": {},
            "track_role": "core",
            "review": {"verify_status": "pass", "semantic_status": "pass", "notes": []},
            **entry,
        }
        for entry in entries
    ]
    document = {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "engine": "suno",
        "collection_id": documentation.parent.name,
        "provenance": {"producer": "music", "source_paths": ["suno-patterns.yaml"]},
        "entries": normalized,
    }
    if duration_filter is not None:
        document["duration_filter"] = duration_filter
    target = documentation / "suno-prompts.json"
    target.write_text(json.dumps(document), encoding="utf-8")
    target.with_suffix(".html").write_text(
        render_repository_document(RepositorySchema.MUSIC_PROMPT, document),
        encoding="utf-8",
    )
