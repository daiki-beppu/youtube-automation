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
