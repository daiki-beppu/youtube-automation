from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from youtube_automation.application.documents.review import ReviewResult
from youtube_automation.commands.documents import music_prompt_select


def _prompt_file(collection: Path) -> None:
    path = collection / "20-documentation/suno-prompts.json"
    path.parent.mkdir()
    path.write_text("{}", encoding="utf-8")


def test_web_approval_uses_shared_review_then_finalizer(tmp_path: Path, monkeypatch) -> None:
    _prompt_file(tmp_path)
    review = Mock(
        return_value=ReviewResult(
            status="selected", artifact_digest="a" * 64, candidate_id="approve", candidates=("approve", "reject")
        )
    )
    finalize = Mock()
    monkeypatch.setattr(music_prompt_select, "run_review", review)
    monkeypatch.setattr(music_prompt_select, "finalize_music_prompt_review", finalize)

    assert music_prompt_select.main(["--collection", str(tmp_path)]) == 0

    review.assert_called_once_with(tmp_path.resolve(), "music-prompt", selection=True, transport="web")
    finalize.assert_called_once_with(
        tmp_path.resolve() / "20-documentation/suno-prompts.json",
        tmp_path.resolve() / "workflow-state.json",
        decision="approve",
        source="web",
        expected_artifact_digest="a" * 64,
    )


def test_automatic_skips_html_and_broker_but_uses_same_finalizer(tmp_path: Path, monkeypatch) -> None:
    _prompt_file(tmp_path)
    review = Mock()
    finalize = Mock()
    monkeypatch.setattr(music_prompt_select, "run_review", review)
    monkeypatch.setattr(music_prompt_select, "finalize_music_prompt_review", finalize)
    monkeypatch.setattr(music_prompt_select, "music_prompt_artifact_digest", Mock(return_value="b" * 64))

    assert music_prompt_select.main(["--collection", str(tmp_path), "--automatic"]) == 0

    review.assert_not_called()
    assert finalize.call_args.kwargs["source"] == "automatic"


def test_terminal_without_candidate_reports_manifest_without_state_change(tmp_path: Path, monkeypatch, capsys) -> None:
    _prompt_file(tmp_path)
    monkeypatch.setattr(
        music_prompt_select,
        "run_review",
        Mock(
            return_value=ReviewResult(
                status="terminal_required", artifact_digest="c" * 64, candidates=("approve", "reject")
            )
        ),
    )
    finalize = Mock()
    monkeypatch.setattr(music_prompt_select, "finalize_music_prompt_review", finalize)

    assert music_prompt_select.main(["--collection", str(tmp_path), "--transport", "terminal"]) == 2

    assert json.loads(capsys.readouterr().out)["candidates"] == ["approve", "reject"]
    finalize.assert_not_called()
