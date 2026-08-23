from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document

_RUNNER = REPO_ROOT / ".claude/skills/wf-new/references/validate_persona_chain.py"
_SPEC = importlib.util.spec_from_file_location("validate_persona_chain", _RUNNER)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _publish(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    publish_json_document(path, RepositorySchema.CHANNEL_STRATEGY)


def _documents(tmp_path: Path, *, persona_scene_ids: list[str] | None = None) -> tuple[Path, Path]:
    persona_path = tmp_path / "persona.json"
    scene_path = tmp_path / "scene.json"
    _publish(
        persona_path,
        {
            "schema_version": 1,
            "document_type": "persona",
            "updated_at": "2026-07-02T00:00:00Z",
            "status": "confirmed",
            "persona": {"id": "persona-primary", "name": "primary", "desires": ["focus"]},
            "scene_ids": ["scene-1"] if persona_scene_ids is None else persona_scene_ids,
            "evidence": [{"id": "ev-1", "source_path": "input.json", "observation": "fact"}],
        },
    )
    _publish(
        scene_path,
        {
            "schema_version": 1,
            "document_type": "scene",
            "updated_at": "2026-07-02T00:00:00Z",
            "status": "confirmed",
            "persona_id": "persona-primary",
            "scenes": [
                {"id": "scene-1", "situation": "work", "desires": ["focus"], "evidence_ids": ["ev-1"]},
                {"id": "scene-2", "situation": "rest", "desires": ["relax"], "evidence_ids": ["ev-1"]},
            ],
            "evidence": [{"id": "ev-1", "source_path": "input.json", "observation": "fact"}],
        },
    )
    return persona_path, scene_path


def _republish(path: Path, update: dict[str, object]) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(update)
    _publish(path, document)


def test_validate_persona_chain_accepts_producer_supported_scene_subset(tmp_path: Path) -> None:
    persona_path, scene_path = _documents(tmp_path)

    _MODULE.validate_persona_chain(persona_path, scene_path)


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("empty", []),
        ("extra", ["scene-1", "scene-missing"]),
    ],
)
def test_validate_persona_chain_rejects_incomplete_or_unknown_references(
    tmp_path: Path, mutation: str, value: list[str]
) -> None:
    persona_path, scene_path = _documents(tmp_path, persona_scene_ids=value)

    with pytest.raises(AutomationError, match="空にできません|未定義 ID"):
        _MODULE.validate_persona_chain(persona_path, scene_path)


def test_validate_persona_chain_rejects_persona_id_mismatch(tmp_path: Path) -> None:
    persona_path, scene_path = _documents(tmp_path)
    _republish(scene_path, {"persona_id": "persona-other"})

    with pytest.raises(AutomationError, match="persona_id"):
        _MODULE.validate_persona_chain(persona_path, scene_path)


def test_validate_persona_chain_rejects_wrong_document_type(tmp_path: Path) -> None:
    _, scene_path = _documents(tmp_path)

    with pytest.raises(AutomationError, match="document_type"):
        _MODULE.validate_persona_chain(scene_path, scene_path)


def test_validate_persona_chain_rejects_schema_failure(tmp_path: Path) -> None:
    persona_path, scene_path = _documents(tmp_path)
    persona_path.write_text("{}", encoding="utf-8")

    with pytest.raises(AutomationError):
        _MODULE.validate_persona_chain(persona_path, scene_path)


def test_validate_persona_chain_rejects_digest_mismatch(tmp_path: Path) -> None:
    persona_path, scene_path = _documents(tmp_path)
    persona = json.loads(persona_path.read_text(encoding="utf-8"))
    persona["persona"]["name"] = "tampered"
    persona_path.write_text(json.dumps(persona), encoding="utf-8")

    with pytest.raises(AutomationError):
        _MODULE.validate_persona_chain(persona_path, scene_path)


def test_validate_persona_chain_rejects_missing_html(tmp_path: Path) -> None:
    persona_path, scene_path = _documents(tmp_path)
    scene_path.with_suffix(".html").unlink()

    with pytest.raises(AutomationError):
        _MODULE.validate_persona_chain(persona_path, scene_path)
