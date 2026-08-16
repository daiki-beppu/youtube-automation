from __future__ import annotations

import json

from youtube_automation.application.documents.review import ReviewResult
from youtube_automation.commands.documents import review


def test_cli_returns_selected_id_and_digest_as_json(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        review,
        "run_review",
        lambda *_args, **_kwargs: ReviewResult(status="selected", artifact_digest="a" * 64, candidate_id="candidate-a"),
    )

    code = review.main(["--collection", str(tmp_path), "--artifact", "thumbnail", "--select", "--timeout", "30"])

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "artifact_digest": "a" * 64,
        "candidate_id": "candidate-a",
        "status": "selected",
    }


def test_terminal_fallback_is_explicit_nonzero(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        review,
        "run_review",
        lambda *_args, **_kwargs: ReviewResult(
            status="terminal_required", artifact_digest="a" * 64, candidates=("a", "b")
        ),
    )

    code = review.main(["--collection", str(tmp_path), "--artifact", "thumbnail", "--transport", "terminal"])

    captured = capsys.readouterr()
    assert code == 2
    assert "terminal fallback" in captured.err
    assert json.loads(captured.out)["candidates"] == ["a", "b"]


def test_automatic_flag_is_forwarded_without_selection(monkeypatch, tmp_path) -> None:
    received: dict[str, object] = {}

    def fake_run(*_args, **kwargs):
        received.update(kwargs)
        return ReviewResult(status="skipped")

    monkeypatch.setattr(review, "run_review", fake_run)

    assert review.main(["--collection", str(tmp_path), "--artifact", "video", "--automatic"]) == 0
    assert received["automatic"] is True
