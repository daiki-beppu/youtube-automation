from __future__ import annotations

import json

import pytest

from youtube_automation.application.documents.review import ReviewResult
from youtube_automation.commands.documents import collection_plan_select


def test_web_selection_uses_common_broker_result_and_finalizer(tmp_path, monkeypatch, capsys) -> None:
    collection = tmp_path / "collection"
    collection.mkdir()
    calls: list[tuple[object, ...]] = []

    def fake_review(path, artifact, **options):
        calls.append((path, artifact, options))
        return ReviewResult(status="selected", artifact_digest="a" * 64, candidate_id="plan-b")

    def fake_finalize(json_path, state_path, **options):
        calls.append((json_path, state_path, options))

    monkeypatch.setattr(collection_plan_select, "run_review", fake_review)
    monkeypatch.setattr(collection_plan_select, "finalize_collection_plan_selection", fake_finalize)

    rc = collection_plan_select.main(["--collection", str(collection)])

    assert rc == 0
    assert calls[0][2] == {"selection": True, "transport": "web"}
    assert calls[1][2] == {
        "proposal_id": "plan-b",
        "source": "web",
        "expected_artifact_digest": "a" * 64,
    }
    assert json.loads(capsys.readouterr().out)["source"] == "web"


def test_terminal_without_candidate_lists_allowlist_and_does_not_finalize(tmp_path, monkeypatch, capsys) -> None:
    collection = tmp_path / "collection"
    collection.mkdir()
    monkeypatch.setattr(
        collection_plan_select,
        "run_review",
        lambda *_args, **_kwargs: ReviewResult(
            status="terminal_required", artifact_digest="a" * 64, candidates=("plan-a", "plan-b")
        ),
    )
    monkeypatch.setattr(
        collection_plan_select,
        "finalize_collection_plan_selection",
        lambda *_args, **_kwargs: pytest.fail("must not finalize"),
    )

    rc = collection_plan_select.main(["--collection", str(collection), "--transport", "terminal"])

    captured = capsys.readouterr()
    assert rc == 2
    assert json.loads(captured.out)["candidates"] == ["plan-a", "plan-b"]
    assert "--candidate-id" in captured.err


def test_terminal_candidate_and_automatic_use_same_finalizer_without_web_wait(tmp_path, monkeypatch) -> None:
    collection = tmp_path / "collection"
    collection.mkdir()
    finalized: list[dict[str, object]] = []

    def fake_review(_path, _artifact, **options):
        assert options == {"transport": "terminal"}
        return ReviewResult(status="terminal_required", artifact_digest="a" * 64, candidates=("plan-a", "plan-b"))

    monkeypatch.setattr(collection_plan_select, "run_review", fake_review)
    monkeypatch.setattr(
        collection_plan_select,
        "finalize_collection_plan_selection",
        lambda *_args, **options: finalized.append(options),
    )

    assert (
        collection_plan_select.main(
            ["--collection", str(collection), "--transport", "terminal", "--candidate-id", "plan-b"]
        )
        == 0
    )
    assert collection_plan_select.main(["--collection", str(collection), "--automatic"]) == 0
    assert finalized == [
        {"proposal_id": "plan-b", "source": "terminal", "expected_artifact_digest": "a" * 64},
        {"proposal_id": "plan-a", "source": "automatic", "expected_artifact_digest": "a" * 64},
    ]


def test_unknown_terminal_candidate_is_rejected_before_finalizer(tmp_path, monkeypatch, capsys) -> None:
    collection = tmp_path / "collection"
    collection.mkdir()
    monkeypatch.setattr(
        collection_plan_select,
        "run_review",
        lambda *_args, **_kwargs: ReviewResult(
            status="terminal_required", artifact_digest="a" * 64, candidates=("plan-a",)
        ),
    )
    monkeypatch.setattr(
        collection_plan_select,
        "finalize_collection_plan_selection",
        lambda *_args, **_kwargs: pytest.fail("must not finalize"),
    )

    rc = collection_plan_select.main(
        ["--collection", str(collection), "--transport", "terminal", "--candidate-id", "unknown"]
    )

    assert rc == 1
    assert "allowlist" in capsys.readouterr().err
