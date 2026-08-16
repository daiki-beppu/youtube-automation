from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from youtube_automation.application.documents import review
from youtube_automation.core.errors import DocumentRenderError, ReviewError
from youtube_automation.infrastructure.browser.selection_broker import BrokerSelection

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "collection"
    (collection / "10-assets").mkdir(parents=True)
    (collection / "01-master").mkdir()
    return collection


def test_automatic_approval_skips_discovery_html_and_browser(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    monkeypatch.setattr(review, "open_local_file", lambda _path: pytest.fail("browser must not open"))

    result = review.run_review(collection, "thumbnail", automatic=True)

    assert result.status == "skipped"
    assert not (collection / "tmp").exists()


def test_collection_symlink_is_rejected_before_resolving_candidates(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    (collection / "10-assets" / "candidate.jpg").write_bytes(b"image")
    alias = tmp_path / "collection-alias"
    alias.symlink_to(collection, target_is_directory=True)

    with pytest.raises(ReviewError, match="collection directoryが不正"):
        review.run_review(alias, "thumbnail", transport="terminal", now=NOW)


def test_media_review_atomically_overwrites_fixed_html_and_opens_browser(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "10-assets" / "candidate.jpg").write_bytes(b"image")
    destination = collection / "tmp" / "reviews" / "thumbnail.html"
    destination.parent.mkdir(parents=True)
    destination.write_text("old mixed content", encoding="utf-8")
    opened: list[Path] = []
    monkeypatch.setattr(review, "open_local_file", lambda path: opened.append(path) is None)

    result = review.run_review(collection, "thumbnail", now=NOW)

    assert result.status == "displayed"
    assert result.html_path == destination.resolve()
    assert "old mixed content" not in destination.read_text(encoding="utf-8")
    assert opened == [destination.resolve()]
    assert not list(destination.parent.glob(".thumbnail.html.*.tmp"))


def test_renderer_failure_preserves_previous_html_and_does_not_open_browser(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "10-assets" / "candidate.jpg").write_bytes(b"image")
    destination = collection / "tmp" / "reviews" / "thumbnail.html"
    destination.parent.mkdir(parents=True)
    destination.write_text("previous", encoding="utf-8")
    monkeypatch.setattr(
        review, "render_review_html", lambda *_args, **_kwargs: (_ for _ in ()).throw(DocumentRenderError("fail"))
    )
    monkeypatch.setattr(review, "open_local_file", lambda _path: pytest.fail("browser must not open"))

    with pytest.raises(DocumentRenderError, match="fail"):
        review.run_review(collection, "thumbnail", now=NOW)

    assert destination.read_text(encoding="utf-8") == "previous"


def test_browser_failure_is_fail_closed_but_keeps_generated_html(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "10-assets" / "candidate.jpg").write_bytes(b"image")
    monkeypatch.setattr(review, "open_local_file", lambda _path: False)

    with pytest.raises(ReviewError, match="thumbnail.html"):
        review.run_review(collection, "thumbnail", now=NOW)

    assert (collection / "tmp" / "reviews" / "thumbnail.html").is_file()


def test_terminal_fallback_is_explicit_and_creates_no_html(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "10-assets" / "candidate.jpg").write_bytes(b"image")
    monkeypatch.setattr(review, "open_local_file", lambda _path: pytest.fail("browser must not open"))

    result = review.run_review(collection, "thumbnail", transport="terminal", now=NOW)

    assert result.status == "terminal_required"
    assert result.candidates == ("candidate-1",)
    assert not (collection / "tmp").exists()


def test_selection_returns_only_revalidated_candidate_id(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    (collection / "10-assets" / "candidate.jpg").write_bytes(b"image")
    monkeypatch.setattr(review, "open_local_file", lambda _path: True)

    class FakeBroker:
        def __init__(self, manifest, **_kwargs):
            self.manifest = manifest
            self.endpoint = f"http://127.0.0.1:43210/select/{manifest.token}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def wait(self, *, timeout: float):
            assert timeout == 30
            return BrokerSelection("candidate-1", self.manifest.artifact_digest)

    monkeypatch.setattr(review, "SelectionBroker", FakeBroker)

    result = review.run_review(collection, "thumbnail", selection=True, timeout=30, now=NOW)

    assert result.status == "selected"
    assert result.candidate_id == "candidate-1"


def test_artifact_change_while_waiting_rejects_selection(tmp_path: Path, monkeypatch) -> None:
    collection = _collection(tmp_path)
    candidate = collection / "10-assets" / "candidate.jpg"
    candidate.write_bytes(b"image")
    monkeypatch.setattr(review, "open_local_file", lambda _path: True)

    class MutatingBroker:
        def __init__(self, manifest, **_kwargs):
            self.manifest = manifest
            self.endpoint = f"http://127.0.0.1:43210/select/{manifest.token}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def wait(self, *, timeout: float):
            candidate.write_bytes(b"changed")
            return BrokerSelection("candidate-1", self.manifest.artifact_digest)

    monkeypatch.setattr(review, "SelectionBroker", MutatingBroker)

    with pytest.raises(ReviewError, match="digest"):
        review.run_review(collection, "thumbnail", selection=True, now=NOW)
