from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.commands.documents import render


def test_cli_renders_registered_schema_to_same_basename(tmp_path: Path, capsys) -> None:
    source = tmp_path / "weekly.json"
    source.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")

    result = render.main([str(source), "--schema", "weekly_vote_log.schema.json"])

    output = source.with_suffix(".html")
    assert result == 0
    assert capsys.readouterr().out.strip() == str(output.resolve())
    assert output.is_file()


def test_cli_returns_nonzero_and_preserves_existing_html_for_invalid_document(tmp_path: Path, capsys) -> None:
    source = tmp_path / "weekly.json"
    output = source.with_suffix(".html")
    source.write_text(json.dumps({"entries": []}), encoding="utf-8")
    output.write_bytes(b"previous")

    result = render.main([str(source), "--schema", "weekly_vote_log.schema.json"])

    assert result == 1
    assert "pointer=/" in capsys.readouterr().err
    assert output.read_bytes() == b"previous"


def test_cli_checks_all_registered_pairs_and_ignores_unregistered_json(tmp_path: Path, capsys) -> None:
    current = tmp_path / "current.json"
    stale = tmp_path / "nested" / "stale.json"
    stale.parent.mkdir()
    payload = json.dumps({"schema_version": 1, "entries": []})
    current.write_text(payload, encoding="utf-8")
    stale.write_text(payload, encoding="utf-8")
    (tmp_path / "config.json").write_text('{"unrelated": true}', encoding="utf-8")
    assert render.main([str(current), "--schema", "weekly_vote_log.schema.json"]) == 0
    stale.with_suffix(".html").write_text("old template", encoding="utf-8")
    capsys.readouterr()

    result = render.main(["--check", "--all", str(tmp_path)])

    output = capsys.readouterr().out
    assert result == 1
    assert "stale" in output
    assert str(stale.resolve()) in output
    assert str(current.resolve()) not in output
    assert "config.json" not in output


def test_cli_fixes_all_stale_or_missing_registered_pairs(tmp_path: Path, capsys) -> None:
    stale = tmp_path / "stale.json"
    missing = tmp_path / "missing.json"
    payload = json.dumps({"schema_version": 1, "entries": []})
    stale.write_text(payload, encoding="utf-8")
    missing.write_text(payload, encoding="utf-8")
    stale.with_suffix(".html").write_text("old template", encoding="utf-8")

    result = render.main(["--fix", "--all", str(tmp_path)])

    assert result == 0
    assert "refreshed 2" in capsys.readouterr().out
    assert render.main(["--check", "--all", str(tmp_path)]) == 0
