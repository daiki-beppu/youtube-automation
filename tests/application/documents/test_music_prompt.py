from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.application.documents.migration import MarkdownMigrationDecision
from youtube_automation.application.documents.music_prompt import (
    finalize_music_prompt_review,
    music_prompt_artifact_digest,
    write_music_prompt_document,
)
from youtube_automation.core.errors import DocumentMigrationError
from youtube_automation.domains.suno.prompts import read_suno_prompt_entries


def _document(*, engine: str = "suno", semantic_status: str = "pass") -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "engine": engine,
        "collection_id": "rain-focus",
        "provenance": {
            "producer": "music",
            "source_paths": ["20-documentation/suno-patterns.yaml"],
        },
        "entries": [
            {
                "name": "Quiet Rain",
                "style": "acoustic folk, soft guitar",
                "lyrics": "" if engine == "suno" else "[Instrumental]",
                "options": (
                    {"style_influence": 80, "weirdness": 20}
                    if engine == "suno"
                    else {"model": "lyria-3-pro-preview", "bpm": 72, "mode": "instrumental"}
                ),
                "track_role": "core",
                "review": {
                    "verify_status": "pass",
                    "semantic_status": semantic_status,
                    "notes": ["quality rubric passed"],
                },
            }
        ],
    }


def _state(path: Path) -> None:
    path.write_text(
        json.dumps({"phase": "planning", "assets": {"thumbnail": False}, "unknown": {"keep": True}}),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("engine", "filename"),
    [
        ("suno", "suno-prompts.json"),
        ("lyria", "lyria-prompt.json"),
    ],
)
def test_verified_music_prompt_pair_waits_for_finalized_review(tmp_path: Path, engine: str, filename: str) -> None:
    target = tmp_path / "20-documentation" / filename
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    _state(state)
    verified: list[str] = []

    result = write_music_prompt_document(
        target,
        state,
        lambda: _document(engine=engine),
        MarkdownMigrationDecision.NOT_REQUIRED,
        machine_verify=lambda document: verified.append(document["engine"]),
    )

    assert result.value == "created"
    assert verified == [engine]
    assert target.with_suffix(".html").is_file()
    persisted = json.loads(state.read_text())
    assert persisted["assets"] == {"thumbnail": False}
    assert persisted["unknown"] == {"keep": True}

    finalize_music_prompt_review(
        target,
        state,
        decision="approve",
        source="web",
        expected_artifact_digest=music_prompt_artifact_digest(target),
    )

    persisted = json.loads(state.read_text())
    assert persisted["assets"] == {"thumbnail": False, "music_prompts": True}


def test_stale_review_digest_does_not_update_state(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/suno-prompts.json"
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    _state(state)
    write_music_prompt_document(
        target,
        state,
        _document,
        MarkdownMigrationDecision.NOT_REQUIRED,
        machine_verify=lambda _document: None,
    )
    before = state.read_bytes()

    with pytest.raises(DocumentMigrationError, match="digest"):
        finalize_music_prompt_review(
            target,
            state,
            decision="approve",
            source="web",
            expected_artifact_digest="0" * 64,
        )

    assert state.read_bytes() == before


@pytest.mark.parametrize("failure", ["verify", "semantic"])
def test_review_failure_does_not_publish_or_update_state(tmp_path: Path, failure: str) -> None:
    target = tmp_path / "20-documentation/suno-prompts.json"
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    _state(state)
    before = state.read_bytes()

    def fail_verify(_document: object) -> None:
        raise DocumentMigrationError("suno verify failed")

    with pytest.raises(DocumentMigrationError, match="verify|semantic"):
        write_music_prompt_document(
            target,
            state,
            lambda: _document(semantic_status="fail" if failure == "semantic" else "pass"),
            MarkdownMigrationDecision.NOT_REQUIRED,
            machine_verify=fail_verify if failure == "verify" else lambda _document: None,
        )

    assert state.read_bytes() == before
    assert not target.exists()
    assert not target.with_suffix(".html").exists()


def test_markdown_migration_requires_explicit_yes_and_removes_markdown_after_pair_validation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "20-documentation/suno-prompts.json"
    target.parent.mkdir()
    markdown = target.with_suffix(".md")
    markdown.write_text("legacy", encoding="utf-8")
    state = tmp_path / "workflow-state.json"
    _state(state)

    write_music_prompt_document(
        target,
        state,
        _document,
        MarkdownMigrationDecision.YES,
        machine_verify=lambda _document: None,
    )

    assert not markdown.exists()
    assert target.is_file() and target.with_suffix(".html").is_file()


def test_legacy_suno_json_markdown_pair_is_migrated_atomically(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/suno-prompts.json"
    target.parent.mkdir()
    target.write_text('[{"name":"legacy","style":"old","lyrics":""}]', encoding="utf-8")
    markdown = target.with_suffix(".md")
    markdown.write_text("legacy view", encoding="utf-8")
    state = tmp_path / "workflow-state.json"
    _state(state)

    result = write_music_prompt_document(
        target,
        state,
        _document,
        MarkdownMigrationDecision.YES,
        machine_verify=lambda _document: None,
    )

    assert result.value == "migrated"
    assert not markdown.exists()
    assert json.loads(target.read_text())["schema_version"] == 1


def test_downstream_reads_only_validated_json_html_pair(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/suno-prompts.json"
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    _state(state)
    write_music_prompt_document(
        target,
        state,
        _document,
        MarkdownMigrationDecision.NOT_REQUIRED,
        machine_verify=lambda _document: None,
    )

    assert read_suno_prompt_entries(tmp_path)[0]["name"] == "Quiet Rain"
    target.with_suffix(".html").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match=r"validated JSON\+HTML pair"):
        read_suno_prompt_entries(tmp_path)
