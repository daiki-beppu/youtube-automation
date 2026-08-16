from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.application.documents.channel_strategy import write_channel_strategy_document
from youtube_automation.application.documents.migration import MarkdownMigrationDecision
from youtube_automation.core.errors import DocumentMigrationError


def _persona() -> dict[str, object]:
    return {
        "schema_version": 1,
        "document_type": "persona",
        "updated_at": "2026-08-16T00:00:00Z",
        "status": "confirmed",
        "persona": {"id": "persona-primary", "name": "夜の集中者", "desires": ["集中したい"]},
        "scene_ids": [],
        "evidence": [{"id": "ev-1", "source_path": "docs/channel-research.json", "observation": "夜に聴く"}],
    }


def _scene(persona_id: str = "persona-primary") -> dict[str, object]:
    return {
        "schema_version": 1,
        "document_type": "scene",
        "updated_at": "2026-08-16T00:00:00Z",
        "status": "hypothesis",
        "persona_id": persona_id,
        "scenes": [{"id": "scene-night", "situation": "夜の作業", "desires": ["集中"], "evidence_ids": ["ev-1"]}],
        "evidence": [
            {"id": "ev-1", "source_path": "docs/channel/personas/persona-definition.json", "observation": "夜型"}
        ],
    }


def _constraints(scene_id: str = "scene-night") -> dict[str, object]:
    return {
        "schema_version": 1,
        "document_type": "constraints",
        "updated_at": "2026-08-16T00:00:00Z",
        "status": "confirmed",
        "persona_id": "persona-primary",
        "scene_ids": [scene_id],
        "constraints": [{"id": "audio-001", "category": "audio", "statement": "穏やか", "evidence_ids": ["ev-1"]}],
        "evidence": [{"id": "ev-1", "source_path": "docs/plans/viewing-scene-matrix.json", "observation": "夜の作業"}],
    }


def _write(root: Path, relative: str, document: dict[str, object]) -> None:
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    write_channel_strategy_document(
        root / relative,
        lambda: document,
        MarkdownMigrationDecision.NOT_REQUIRED,
    )


def test_strategy_documents_publish_validated_json_html_pairs_in_dependency_order(tmp_path: Path) -> None:
    _write(tmp_path, "docs/channel/personas/persona-definition.json", _persona())
    _write(tmp_path, "docs/plans/viewing-scene-matrix.json", _scene())
    _write(tmp_path, "docs/channel/creative-constraints.json", _constraints())

    scene = json.loads((tmp_path / "docs/plans/viewing-scene-matrix.json").read_text())
    assert scene["persona_id"] == "persona-primary"
    assert (tmp_path / "docs/channel/creative-constraints.html").is_file()


@pytest.mark.parametrize(
    ("relative", "document", "match"),
    [
        ("docs/plans/viewing-scene-matrix.json", _scene("unknown"), "persona_id"),
        ("docs/channel/creative-constraints.json", _constraints("unknown"), "scene_ids"),
    ],
)
def test_broken_cross_document_reference_is_rejected_without_changing_existing_pair(
    tmp_path: Path, relative: str, document: dict[str, object], match: str
) -> None:
    _write(tmp_path, "docs/channel/personas/persona-definition.json", _persona())
    if "creative" in relative:
        _write(tmp_path, "docs/plans/viewing-scene-matrix.json", _scene())
    target = tmp_path / relative
    before = target.read_bytes() if target.exists() else None

    with pytest.raises(DocumentMigrationError, match=match):
        _write(tmp_path, relative, document)

    assert (target.read_bytes() if target.exists() else None) == before


def test_duplicate_constraint_ids_are_rejected_before_publish(tmp_path: Path) -> None:
    _write(tmp_path, "docs/channel/personas/persona-definition.json", _persona())
    _write(tmp_path, "docs/plans/viewing-scene-matrix.json", _scene())
    document = _constraints()
    document["constraints"] = [document["constraints"][0], document["constraints"][0]]  # type: ignore[index]

    with pytest.raises(DocumentMigrationError, match="constraint ID"):
        _write(tmp_path, "docs/channel/creative-constraints.json", document)


def test_markdown_migration_requires_explicit_approval_and_preserves_markdown_on_rejection(tmp_path: Path) -> None:
    target = tmp_path / "docs/channel/personas/persona-definition.json"
    target.parent.mkdir(parents=True)
    markdown = target.with_suffix(".md")
    markdown.write_text("legacy", encoding="utf-8")

    result = write_channel_strategy_document(target, _persona, MarkdownMigrationDecision.NO)

    assert result.value == "declined"
    assert markdown.read_text() == "legacy"
    assert not target.exists()
