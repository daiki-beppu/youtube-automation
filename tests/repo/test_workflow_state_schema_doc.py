"""workflow-state owner と追従 schema 文書の field 契約。"""

from __future__ import annotations

import json
import re
import types
from typing import Union, get_args, get_origin, get_type_hints, is_typeddict

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.collections.workflow_state import WorkflowStateDocument

SCHEMA_PATH = REPO_ROOT / ".claude/skills/wf-new/references/schema.md"
_SCHEMA_EXAMPLE = re.compile(r"## フィールド定義\s+```json\s+(\{.*?\})\s+```", re.DOTALL)


def _owner_paths(annotation: object, prefix: str = "") -> set[str]:
    if is_typeddict(annotation):
        paths: set[str] = set()
        for name, field_type in get_type_hints(annotation).items():
            path = f"{prefix}.{name}" if prefix else name
            paths.add(path)
            paths.update(_owner_paths(field_type, path))
        return paths

    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return _owner_paths(item_type, f"{prefix}[]")
    if origin in (Union, types.UnionType):
        paths: set[str] = set()
        for member in get_args(annotation):
            paths.update(_owner_paths(member, prefix))
        return paths
    return set()


def _document_paths(value: object, owner_paths: set[str], prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return set()

    paths: set[str] = set()
    for name, child in value.items():
        path = f"{prefix}.{name}" if prefix else name
        paths.add(path)
        if isinstance(child, dict) and any(candidate.startswith(f"{path}.") for candidate in owner_paths):
            paths.update(_document_paths(child, owner_paths, path))
        elif isinstance(child, list) and child and isinstance(child[0], dict):
            item_path = f"{path}[]"
            if any(candidate.startswith(f"{item_path}.") for candidate in owner_paths):
                paths.update(_document_paths(child[0], owner_paths, item_path))
    return paths


def test_schema_document_tracks_owner_field_names() -> None:
    owner_paths = _owner_paths(WorkflowStateDocument)
    match = _SCHEMA_EXAMPLE.search(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert match is not None, "schema.md field JSON example was not found"
    documented_paths = _document_paths(json.loads(match.group(1)), owner_paths)

    missing_from_document = sorted(owner_paths - documented_paths)
    missing_from_owner = sorted(documented_paths - owner_paths)
    assert not missing_from_document and not missing_from_owner, (
        f"missing from schema.md: {missing_from_document}; missing from owner: {missing_from_owner}"
    )
