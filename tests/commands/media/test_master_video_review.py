from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from youtube_automation.application.master_video_review import MasterVideoReviewResult
from youtube_automation.commands.media import master_video_review


def test_cli_passes_explicit_review_presentation_and_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    captured: dict[str, object] = {}

    def review(collection: Path, **options: object) -> MasterVideoReviewResult:
        captured.update(collection=collection, **options)
        return MasterVideoReviewResult("selected", "digest", "full:Rain-Master.mp4")

    monkeypatch.setattr(master_video_review, "review_master_video", review)
    args = Namespace(
        collection=tmp_path,
        kind="full",
        background_route="loop",
        effect="none",
        overlays="disabled",
        full_output_outlook="stream copy",
        automatic=False,
        transport="terminal",
        candidate_id="full:Rain-Master.mp4",
    )

    assert master_video_review.run(args) == 0
    assert captured["kind"] == "full"
    assert captured["candidate_id"] == "full:Rain-Master.mp4"
    assert captured["presentation"].background_route == "loop"
    assert '"candidate_id": "full:Rain-Master.mp4"' in capsys.readouterr().out
