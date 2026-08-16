from __future__ import annotations

from pathlib import Path

from youtube_automation.application.thumbnail_review import ThumbnailReviewResult
from youtube_automation.commands.thumbnail import thumbnail_review


def test_automatic_skips_html_broker_and_existing_auto_owner_remains_canonical(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    calls: list[bool] = []

    def fake_review(*_args, automatic: bool = False, **_kwargs) -> ThumbnailReviewResult:
        calls.append(automatic)
        return ThumbnailReviewResult(status="skipped")

    monkeypatch.setattr(thumbnail_review, "run_thumbnail_review", fake_review)
    result = thumbnail_review.main(["--collection", str(tmp_path), "--artifact", "thumbnail", "--automatic"])

    assert result == 0
    assert calls == [True]
    assert "yt-thumbnail-auto-select" in capsys.readouterr().out


def test_terminal_fallback_lists_allowlisted_ids_without_finalizing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        thumbnail_review,
        "run_thumbnail_review",
        lambda *_args, **_kwargs: ThumbnailReviewResult(
            status="terminal_required", artifact_digest="a" * 64, candidates=("choice-1",)
        ),
    )
    monkeypatch.setattr(
        thumbnail_review,
        "finalize_thumbnail_review_selection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not finalize")),
    )

    result = thumbnail_review.main(["--collection", str(tmp_path), "--artifact", "main", "--transport", "terminal"])

    assert result == 2
    assert '"candidate_id"' not in capsys.readouterr().out
