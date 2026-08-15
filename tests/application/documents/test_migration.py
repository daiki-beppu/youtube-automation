from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from youtube_automation.application.documents import migration
from youtube_automation.core.errors import DocumentMigrationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure import filesystem


def _document(week_start: str = "2026-08-10") -> dict[str, object]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "week_start": week_start,
                "axes": [{"key": "calm", "label": "Calm", "votes": 3}],
                "top_axis": "calm",
            }
        ],
    }


def _builder(week_start: str = "2026-08-10") -> Callable[[], object]:
    return lambda: _document(week_start)


def test_new_document_creates_json_and_html_without_markdown(tmp_path: Path) -> None:
    target = tmp_path / "weekly.json"

    result = migration.write_operational_document(
        target,
        RepositorySchema.WEEKLY_VOTE_LOG,
        _builder(),
        migration.MarkdownMigrationDecision.NOT_REQUIRED,
    )

    assert result is migration.DocumentWriteResult.CREATED
    assert json.loads(target.read_text()) == _document()
    assert target.with_suffix(".html").is_file()
    assert not target.with_suffix(".md").exists()


def test_approved_markdown_migration_deletes_markdown_after_pair_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "weekly.json"
    markdown = target.with_suffix(".md")
    markdown.write_text("legacy", encoding="utf-8")
    real_validator = migration.validate_generated_html

    def validate_while_markdown_exists(html: str) -> None:
        assert markdown.read_text(encoding="utf-8") == "legacy"
        real_validator(html)

    monkeypatch.setattr(migration, "validate_generated_html", validate_while_markdown_exists)

    result = migration.write_operational_document(
        target,
        RepositorySchema.WEEKLY_VOTE_LOG,
        _builder(),
        migration.MarkdownMigrationDecision.YES,
    )

    assert result is migration.DocumentWriteResult.MIGRATED
    assert target.is_file()
    assert target.with_suffix(".html").is_file()
    assert not markdown.exists()


def test_declined_markdown_migration_stops_without_modifying_markdown(tmp_path: Path) -> None:
    target = tmp_path / "weekly.json"
    markdown = target.with_suffix(".md")
    markdown.write_bytes(b"legacy")

    def unexpected_conversion() -> object:
        raise AssertionError("Markdown conversion must not run after No")

    result = migration.write_operational_document(
        target,
        RepositorySchema.WEEKLY_VOTE_LOG,
        unexpected_conversion,
        migration.MarkdownMigrationDecision.NO,
    )

    assert result is migration.DocumentWriteResult.DECLINED
    assert markdown.read_bytes() == b"legacy"
    assert not target.exists()
    assert not target.with_suffix(".html").exists()


def test_post_publish_validation_failure_rolls_back_existing_json_and_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "weekly.json"
    migration.write_operational_document(
        target,
        RepositorySchema.WEEKLY_VOTE_LOG,
        _builder(),
        migration.MarkdownMigrationDecision.NOT_REQUIRED,
    )
    original_json = target.read_bytes()
    original_html = target.with_suffix(".html").read_bytes()

    def fail_validation(_html: str) -> None:
        raise DocumentMigrationError("post-publish validation failed")

    monkeypatch.setattr(migration, "validate_generated_html", fail_validation)

    with pytest.raises(DocumentMigrationError, match="post-publish"):
        migration.write_operational_document(
            target,
            RepositorySchema.WEEKLY_VOTE_LOG,
            _builder("2026-08-17"),
            migration.MarkdownMigrationDecision.NOT_REQUIRED,
        )

    assert target.read_bytes() == original_json
    assert target.with_suffix(".html").read_bytes() == original_html


def test_second_file_replace_failure_rolls_back_both_existing_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "weekly.json"
    html = target.with_suffix(".html")
    migration.write_operational_document(
        target,
        RepositorySchema.WEEKLY_VOTE_LOG,
        _builder(),
        migration.MarkdownMigrationDecision.NOT_REQUIRED,
    )
    original_json = target.read_bytes()
    original_html = html.read_bytes()
    real_replace = filesystem.replace_file

    def fail_html_publish(source: Path, destination: Path) -> None:
        if source.suffix == ".tmp" and destination == html:
            raise OSError("html replace failed")
        real_replace(source, destination)

    monkeypatch.setattr(filesystem, "replace_file", fail_html_publish)

    with pytest.raises(OSError, match="html replace failed"):
        migration.write_operational_document(
            target,
            RepositorySchema.WEEKLY_VOTE_LOG,
            _builder("2026-08-17"),
            migration.MarkdownMigrationDecision.NOT_REQUIRED,
        )

    assert target.read_bytes() == original_json
    assert html.read_bytes() == original_html


def test_markdown_migration_validation_failure_keeps_markdown_and_removes_new_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "weekly.json"
    markdown = target.with_suffix(".md")
    markdown.write_bytes(b"legacy")

    def fail_validation(_html: str) -> None:
        raise DocumentMigrationError("post-publish validation failed")

    monkeypatch.setattr(migration, "validate_generated_html", fail_validation)

    with pytest.raises(DocumentMigrationError, match="post-publish"):
        migration.write_operational_document(
            target,
            RepositorySchema.WEEKLY_VOTE_LOG,
            _builder(),
            migration.MarkdownMigrationDecision.YES,
        )

    assert markdown.read_bytes() == b"legacy"
    assert not target.exists()
    assert not target.with_suffix(".html").exists()


def test_markdown_delete_failure_rolls_back_new_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "weekly.json"
    markdown = target.with_suffix(".md")
    markdown.write_bytes(b"legacy")
    real_unlink = Path.unlink

    def fail_markdown_delete(path: Path, missing_ok: bool = False) -> None:
        if path == markdown:
            raise OSError("markdown delete failed")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_markdown_delete)

    with pytest.raises(OSError, match="markdown delete failed"):
        migration.write_operational_document(
            target,
            RepositorySchema.WEEKLY_VOTE_LOG,
            _builder(),
            migration.MarkdownMigrationDecision.YES,
        )

    assert markdown.read_bytes() == b"legacy"
    assert not target.exists()
    assert not target.with_suffix(".html").exists()


def test_migrated_pair_updates_without_migration_decision(tmp_path: Path) -> None:
    target = tmp_path / "weekly.json"
    migration.write_operational_document(
        target,
        RepositorySchema.WEEKLY_VOTE_LOG,
        _builder(),
        migration.MarkdownMigrationDecision.NOT_REQUIRED,
    )

    result = migration.write_operational_document(
        target,
        RepositorySchema.WEEKLY_VOTE_LOG,
        _builder("2026-08-17"),
        migration.MarkdownMigrationDecision.NOT_REQUIRED,
    )

    assert result is migration.DocumentWriteResult.UPDATED
    assert json.loads(target.read_text())["entries"][0]["week_start"] == "2026-08-17"


@pytest.mark.parametrize(
    ("existing_suffixes", "decision"),
    [
        ((".md",), migration.MarkdownMigrationDecision.NOT_REQUIRED),
        ((".json",), migration.MarkdownMigrationDecision.NOT_REQUIRED),
        ((".html",), migration.MarkdownMigrationDecision.NOT_REQUIRED),
        ((".json", ".html", ".md"), migration.MarkdownMigrationDecision.NOT_REQUIRED),
    ],
)
def test_incomplete_or_unapproved_state_is_rejected_without_changes(
    tmp_path: Path,
    existing_suffixes: tuple[str, ...],
    decision: migration.MarkdownMigrationDecision,
) -> None:
    target = tmp_path / "weekly.json"
    paths = {suffix: target.with_suffix(suffix) for suffix in existing_suffixes}
    for suffix, path in paths.items():
        path.write_text("{}" if suffix == ".json" else "existing", encoding="utf-8")
    before = {suffix: path.read_bytes() for suffix, path in paths.items()}

    with pytest.raises(DocumentMigrationError):
        migration.write_operational_document(
            target,
            RepositorySchema.WEEKLY_VOTE_LOG,
            _builder(),
            decision,
        )

    assert {suffix: path.read_bytes() for suffix, path in paths.items()} == before
