from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.commands.collections import workflow_status
from youtube_automation.core.errors import DocumentRenderError


def _channel(tmp_path: Path) -> tuple[Path, Path]:
    collection = tmp_path / "collections" / "planning" / "sample"
    collection.mkdir(parents=True)
    state_path = collection / "workflow-state.json"
    state_path.write_text(
        json.dumps(
            {
                "collection_name": "Sample",
                "stage": "planning",
                "phase": "prepared",
                "updated_at": "2026-08-16T00:00:00+00:00",
                "assets": {},
                "upload": {},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, state_path


def test_command_generates_fixed_snapshot_and_opens_it(tmp_path: Path, monkeypatch, capsys) -> None:
    channel, _ = _channel(tmp_path)
    opened: list[Path] = []
    monkeypatch.setattr(workflow_status, "open_local_file", lambda path: opened.append(path) is None)

    code = workflow_status.main(["--target", str(channel)])

    destination = channel / "tmp" / "reviews" / "workflow-status.html"
    assert code == 0
    assert destination.is_file()
    assert opened == [destination.resolve()]
    assert str(destination.resolve()) in capsys.readouterr().out


def test_browser_failure_is_nonzero_and_reports_absolute_snapshot_path(tmp_path: Path, monkeypatch, capsys) -> None:
    channel, state_path = _channel(tmp_path)
    before = state_path.read_bytes()
    monkeypatch.setattr(workflow_status, "open_local_file", lambda _path: False)

    code = workflow_status.main(["--target", str(channel)])

    destination = channel / "tmp" / "reviews" / "workflow-status.html"
    captured = capsys.readouterr()
    assert code == 1
    assert destination.is_file()
    assert str(destination.resolve()) in captured.err
    assert state_path.read_bytes() == before


def test_renderer_failure_preserves_previous_snapshot_and_state(tmp_path: Path, monkeypatch, capsys) -> None:
    channel, state_path = _channel(tmp_path)
    destination = channel / "tmp" / "reviews" / "workflow-status.html"
    destination.parent.mkdir(parents=True)
    destination.write_text("previous", encoding="utf-8")
    before = state_path.read_bytes()

    def fail_render(_snapshot):
        raise DocumentRenderError("render failed")

    monkeypatch.setattr(workflow_status, "render_workflow_status", fail_render)

    code = workflow_status.main(["--target", str(channel)])

    assert code == 1
    assert destination.read_text(encoding="utf-8") == "previous"
    assert state_path.read_bytes() == before
    assert str(destination.resolve()) in capsys.readouterr().err
