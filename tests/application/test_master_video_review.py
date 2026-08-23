from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from youtube_automation.application import master_video_review
from youtube_automation.core.errors import ReviewError
from youtube_automation.infrastructure.browser.selection_broker import BrokerSelection
from youtube_automation.infrastructure.media.probe import VideoProbe

NOW = datetime(2026, 8, 16, 14, 0, tzinfo=UTC)


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "rain-collection"
    (collection / "01-master").mkdir(parents=True)
    (collection / "10-assets").mkdir()
    (collection / "10-assets" / "loop.mp4").write_bytes(b"loop")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "version": 2,
                "phase": "mastered",
                "assets": {"master_audio": "master.wav", "master_video": None},
            }
        ),
        encoding="utf-8",
    )
    return collection


def _probe(_path: Path) -> VideoProbe:
    return VideoProbe(duration_seconds=20.0, width=1920, height=1080, codec="h264")


def _broker(candidate_id: str):
    class Broker:
        def __init__(self, manifest):
            self.manifest = manifest
            self.endpoint = f"http://127.0.0.1:43210/select/{manifest.token}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def wait(self, *, timeout: float):
            assert timeout == 30
            return BrokerSelection(candidate_id, self.manifest.artifact_digest)

    return Broker


def _presentation() -> master_video_review.VideoReviewPresentation:
    return master_video_review.VideoReviewPresentation(
        background_route="loop.mp4 (loop)",
        effect="zoom / subtle",
        overlays="audio visualizer enabled",
        full_output_outlook="effect bake + stream copy / roughly 1-2 minutes",
    )


def test_video_source_streams_file_digest_through_shared_helper(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    video = collection / "01-master" / "Rain-Preview.mp4"
    video.write_bytes(b"preview")
    monkeypatch.setattr(master_video_review, "probe_video", _probe)
    digested: list[Path] = []

    def digest(path: Path) -> str:
        digested.append(path)
        return "a" * 64

    monkeypatch.setattr(master_video_review, "sha256_file", digest)
    monkeypatch.setattr(Path, "read_bytes", lambda _path: pytest.fail("video must not be read into memory"))

    source = master_video_review._VideoSource(collection, "preview", _presentation())
    source.candidates()

    assert digested == [video.resolve()]


def test_preview_review_plays_probe_and_composition_without_updating_state(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "01-master" / "Rain-Preview.mp4").write_bytes(b"preview")
    monkeypatch.setattr(master_video_review, "probe_video", _probe)
    monkeypatch.setattr(master_video_review, "SelectionBroker", _broker("preview:Rain-Preview.mp4"))
    monkeypatch.setattr(master_video_review, "open_local_file", lambda _path: True)

    result = master_video_review.review_master_video(
        collection,
        kind="preview",
        presentation=_presentation(),
        automatic=False,
        transport="web",
        candidate_id=None,
        now=NOW,
        timeout=30,
    )

    html = (collection / "20-documentation/reviews/master-video-preview.html").read_text(encoding="utf-8")
    state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    assert result.status == "selected"
    assert state["assets"]["master_video"] is None
    assert "<video" in html
    for value in (
        "preview（20秒短尺確認）",
        "1920 × 1080",
        "h264",
        "loop.mp4 (loop)",
        "zoom / subtle",
        "audio visualizer enabled",
        "effect bake + stream copy",
    ):
        assert value in html


def test_full_review_updates_master_video_only_after_revalidated_selection(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "01-master" / "Rain-Master.mp4").write_bytes(b"full")
    monkeypatch.setattr(master_video_review, "probe_video", _probe)
    monkeypatch.setattr(master_video_review, "SelectionBroker", _broker("full:Rain-Master.mp4"))
    monkeypatch.setattr(master_video_review, "open_local_file", lambda _path: True)

    result = master_video_review.review_master_video(
        collection,
        kind="full",
        presentation=_presentation(),
        automatic=False,
        transport="web",
        candidate_id=None,
        now=NOW,
        timeout=30,
    )

    state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    assert result.candidate_id == "full:Rain-Master.mp4"
    assert state["assets"]["master_video"] == "Rain-Master.mp4"
    assert state["phase"] == "mastered"


def test_probe_failure_keeps_master_video_pending_and_creates_no_html(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "01-master" / "Rain-Master.mp4").write_bytes(b"broken")
    monkeypatch.setattr(master_video_review, "probe_video", lambda _path: None)

    with pytest.raises(ReviewError, match="ffprobe"):
        master_video_review.review_master_video(
            collection,
            kind="full",
            presentation=_presentation(),
            automatic=False,
            transport="web",
            candidate_id=None,
            now=NOW,
            timeout=30,
        )

    state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    assert state["assets"]["master_video"] is None
    assert not (collection / "tmp").exists()


def test_automatic_full_path_skips_html_browser_and_broker_but_still_probes(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "01-master" / "Rain-Master.mp4").write_bytes(b"full")
    monkeypatch.setattr(master_video_review, "probe_video", _probe)
    monkeypatch.setattr(master_video_review, "open_local_file", lambda _path: pytest.fail("browser must not open"))
    monkeypatch.setattr(master_video_review, "SelectionBroker", lambda _manifest: pytest.fail("broker must not start"))

    result = master_video_review.review_master_video(
        collection,
        kind="full",
        presentation=_presentation(),
        automatic=True,
        transport="web",
        candidate_id=None,
        now=NOW,
        timeout=30,
    )

    state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    assert result.status == "selected"
    assert state["assets"]["master_video"] == "Rain-Master.mp4"
    assert not (collection / "tmp").exists()
