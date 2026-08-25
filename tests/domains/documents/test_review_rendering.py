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


def test_review_renderer_embeds_aac_with_browser_audio_player(tmp_path: Path) -> None:
    media = tmp_path / "final.aac"
    media.write_bytes(b"audio")
    manifest = SelectionManifest.create(
        artifact="audio",
        artifact_digest="a" * 64,
        candidates=(ReviewCandidate("worktree:final.aac", "final.aac", "b" * 64),),
        now=datetime(2026, 8, 16, tzinfo=UTC),
        lifetime=timedelta(minutes=5),
    )

    html = render_review_html(manifest, endpoint=None, media={"worktree:final.aac": media})

    assert f'<audio src="{media.resolve().as_uri()}" controls preload="metadata"></audio>' in html


def test_plan_review_card_shows_comparison_details_and_preview(tmp_path: Path) -> None:
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"preview")
    manifest = SelectionManifest.create(
        artifact="plan",
        artifact_digest="a" * 64,
        candidates=(
            ReviewCandidate(
                "plan-a",
                "静かな雨の夜",
                "b" * 64,
                details=(("対象視聴者", "夜に集中したい人"), ("映像方針", "固定構図")),
            ),
        ),
        now=datetime(2026, 8, 16, tzinfo=UTC),
        lifetime=timedelta(minutes=5),
    )
    endpoint = f"http://127.0.0.1:43123/select/{manifest.token}"

    html = render_review_html(manifest, endpoint=endpoint, media={"plan-a": preview})

    assert "夜に集中したい人" in html
    assert "映像方針" in html
    assert preview.resolve().as_uri() in html


def test_each_candidate_has_unique_accessible_label_preview_qa_and_action(tmp_path: Path) -> None:
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"preview")
    manifest = SelectionManifest.create(
        artifact="thumbnail",
        artifact_digest="a" * 64,
        candidates=(
            ReviewCandidate("candidate-a", "候補 A", "b" * 64, details=(("固定 QA", "pass"),)),
            ReviewCandidate("candidate-b", "候補 B", "c" * 64, details=(("固定 QA", "warn"),)),
        ),
        now=datetime(2026, 8, 16, tzinfo=UTC),
        lifetime=timedelta(minutes=5),
    )
    endpoint = f"http://127.0.0.1:43123/select/{manifest.token}"

    html = render_review_html(
        manifest,
        endpoint=endpoint,
        media={"candidate-a": preview, "candidate-b": preview},
    )

    assert 'class="review-grid"' in html
    assert "Hallmark · macrostructure: Comparison Ledger" in html
    assert "theme: Midnight" in html
    assert "color-scheme: dark" in html
    assert 'class="page-header review-header"' in html
    assert 'class="candidate-index" aria-hidden="true">01</p>' in html
    assert 'class="candidate-index" aria-hidden="true">02</p>' in html
    assert 'aria-labelledby="candidate-1-title"' in html
    assert 'aria-labelledby="candidate-2-title"' in html
    assert 'aria-label="候補 A を選ぶ"' in html
    assert 'aria-label="候補 B を選ぶ"' in html
    first = html.index('data-candidate-id="candidate-a"')
    second = html.index('data-candidate-id="candidate-b"')
    assert first < html.index("候補 A 原寸", first) < html.index("確認項目", first) < html.index("候補 A を選ぶ", first)
    assert (
        second
        < html.index("候補 B 原寸", second)
        < html.index("確認項目", second)
        < html.index("候補 B を選ぶ", second)
    )


def test_video_and_text_candidates_keep_the_same_comparison_hierarchy(tmp_path: Path) -> None:
    video = tmp_path / "candidate.mp4"
    video.write_bytes(b"video")
    manifest = SelectionManifest.create(
        artifact="mixed",
        artifact_digest="a" * 64,
        candidates=(
            ReviewCandidate("video", "映像候補", "b" * 64, details=(("固定 QA", "pass"),)),
            ReviewCandidate("text", "テキスト候補", "c" * 64, details=(("本文", "静かな夜"),)),
        ),
        now=datetime(2026, 8, 16, tzinfo=UTC),
        lifetime=timedelta(minutes=5),
    )

    html = render_review_html(manifest, endpoint=None, media={"video": video})

    assert f'<video src="{video.resolve().as_uri()}" controls preload="metadata"></video>' in html
    assert html.count("確認項目") == 2
    assert "静かな夜" in html
    assert "button:focus-visible" in html
