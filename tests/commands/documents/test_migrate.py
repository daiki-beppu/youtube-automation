from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.commands.documents import migrate


def _write_candidate(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "week_start": "2026-08-10",
                        "axes": [{"key": "calm", "label": "Calm", "votes": 3}],
                        "top_axis": "calm",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_cli_publishes_new_candidate_as_json_html_pair(tmp_path: Path, capsys) -> None:
    candidate = tmp_path / "candidate.json"
    target = tmp_path / "weekly.json"
    _write_candidate(candidate)

    result = migrate.main([str(candidate), "--target", str(target), "--schema", "weekly_vote_log.schema.json"])

    assert result == 0
    assert capsys.readouterr().out.strip() == f"created: {target.resolve()}"
    assert target.is_file()
    assert target.with_suffix(".html").is_file()


def test_cli_requires_explicit_decision_for_markdown_migration(tmp_path: Path, capsys) -> None:
    candidate = tmp_path / "candidate.json"
    target = tmp_path / "weekly.json"
    markdown = target.with_suffix(".md")
    _write_candidate(candidate)
    markdown.write_bytes(b"legacy")

    result = migrate.main([str(candidate), "--target", str(target), "--schema", "weekly_vote_log.schema.json"])

    assert result == 1
    assert "明示的な yes/no" in capsys.readouterr().err
    assert markdown.read_bytes() == b"legacy"


def test_cli_no_decision_stops_markdown_update_successfully(tmp_path: Path, capsys) -> None:
    target = tmp_path / "weekly.json"
    markdown = target.with_suffix(".md")
    markdown.write_bytes(b"legacy")

    result = migrate.main(
        [
            "--target",
            str(target),
            "--schema",
            "weekly_vote_log.schema.json",
            "--migration-decision",
            "no",
        ]
    )

    assert result == 0
    assert capsys.readouterr().out.strip() == f"declined: {target.resolve()}"
    assert markdown.read_bytes() == b"legacy"


def test_collection_plan_requires_workflow_state_gate(tmp_path: Path, capsys) -> None:
    candidate = tmp_path / "candidate.json"
    target = tmp_path / "20-documentation/plan_proposals.json"
    target.parent.mkdir()
    candidate.write_text("{}", encoding="utf-8")

    result = migrate.main([str(candidate), "--target", str(target), "--schema", "collection-plan.schema.json"])

    assert result == 1
    assert "--workflow-state" in capsys.readouterr().err
