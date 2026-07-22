"""Helpers for reading ``suno-prompts.json`` legacy arrays and envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}") from exc
    return normalize_suno_prompt_entries(data)
