from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from youtube_automation.domains.documents.review import ReviewCandidate, SelectionManifest
from youtube_automation.domains.documents.review_rendering import render_review_html, validate_review_html


def test_review_renderer_escapes_labels_and_exposes_only_allowlisted_form_fields(tmp_path: Path) -> None:
    media = tmp_path / "candidate.jpg"
    media.write_bytes(b"image")
    manifest = SelectionManifest.create(
        artifact="thumbnail",
        artifact_digest="a" * 64,
        candidates=(ReviewCandidate("candidate.jpg", "<script>alert(1)</script>", "b" * 64),),
        now=datetime(2026, 8, 16, tzinfo=UTC),
        lifetime=timedelta(minutes=5),
    )
    endpoint = f"http://127.0.0.1:43210/select/{manifest.token}"

    html = render_review_html(manifest, endpoint=endpoint, media={"candidate.jpg": media})

    validate_review_html(html, manifest=manifest, endpoint=endpoint, media={"candidate.jpg": media})
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html
    assert 'name="candidate_id" value="candidate.jpg"' in html
    assert 'name="artifact_digest" value="' + "a" * 64 + '"' in html
    assert "textarea" not in html
    assert "state_patch" not in html
    assert "command" not in html


def test_display_only_review_has_no_form_or_action(tmp_path: Path) -> None:
    media = tmp_path / "candidate.mp3"
    media.write_bytes(b"audio")
    manifest = SelectionManifest.create(
        artifact="audio",
        artifact_digest="a" * 64,
        candidates=(ReviewCandidate("candidate.mp3", "candidate", "b" * 64),),
        now=datetime(2026, 8, 16, tzinfo=UTC),
        lifetime=timedelta(minutes=5),
    )

    html = render_review_html(manifest, endpoint=None, media={"candidate.mp3": media})

    assert "<form" not in html
    assert "<button" not in html
