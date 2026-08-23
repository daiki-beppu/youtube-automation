from __future__ import annotations

import json

import pytest

from tests.helpers.paths import FIXTURES_DIR
from youtube_automation.core.errors import DocumentRenderError, DocumentValidationError
from youtube_automation.domains.documents.rendering import (
    render_repository_document,
    render_schema_document,
    validate_generated_html,
)
from youtube_automation.domains.documents.schema_registry import RepositorySchema


def _view_schema() -> dict[str, object]:
    return {
        "title": "Review <board>",
        "description": "Structured review",
        "type": "object",
        "properties": {
            "summary": {
                "title": "Summary",
                "description": "Primary finding",
                "x-view": {"presentation": "card", "order": 2},
            },
            "rows": {
                "title": "Metrics",
                "x-view": {"presentation": "table", "order": 3},
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"title": "Name", "x-view": {"order": 2}},
                        "score": {"title": "Score", "x-view": {"order": 1}},
                    },
                },
            },
            "asset": {
                "title": "Preview",
                "x-view": {"presentation": "media", "mediaType": "image", "order": 1},
            },
        },
    }


def test_schema_annotations_render_card_table_and_local_media_in_view_order() -> None:
    html = render_schema_document(
        {
            "summary": "Ready",
            "rows": [{"name": "CTR", "score": 8.2}],
            "asset": "assets/preview.jpg",
        },
        _view_schema(),
    )

    assert html.index("Preview") < html.index("Summary") < html.index("Metrics")
    assert '<img src="assets/preview.jpg"' in html
    assert '<section class="view-card"' in html
    assert '<table class="view-table">' in html
    assert html.index("Score") < html.index("Name")
    validate_generated_html(html)


def test_table_keeps_additional_row_fields_after_declared_schema_columns() -> None:
    html = render_schema_document(
        {
            "summary": "Ready",
            "rows": [{"name": "CTR", "score": 8.2, "runtime_metric": "9.1%"}],
            "asset": "assets/preview.jpg",
        },
        _view_schema(),
    )

    assert html.index("Score") < html.index("Name") < html.index("runtime_metric")
    assert "9.1%" in html


def test_details_presentation_keeps_long_evidence_available_without_expanding_it() -> None:
    schema = _view_schema()
    schema["properties"]["evidence"] = {
        "title": "Evidence and provenance",
        "description": "Open this only when the source trail is needed.",
        "type": "object",
        "x-view": {"presentation": "details", "order": 4},
    }

    html = render_schema_document(
        {
            "summary": "Ready",
            "rows": [],
            "asset": "assets/preview.jpg",
            "evidence": {"source": "reports/source.json", "daily": [1, 2, 3]},
        },
        schema,
    )

    assert '<details class="view-details">' in html
    assert "<summary>Evidence and provenance</summary>" in html
    assert "reports/source.json" in html
    assert "<details open" not in html


def test_review_annotations_create_priority_summary_and_collapsed_content() -> None:
    schema = {
        "title": "Approval",
        "type": "object",
        "properties": {
            "decision": {
                "title": "Decision",
                "x-view": {"summary": True, "priority": "critical", "order": 1},
            },
            "audit": {
                "title": "Audit trail",
                "x-view": {"collapsed": True, "order": 2},
            },
        },
    }

    html = render_schema_document({"decision": "PASS", "audit": {"source": "plan.json"}}, schema)

    assert 'class="view-card view-summary view-priority-critical"' in html
    assert '<details class="view-details"' in html
    assert "<summary>Audit trail</summary>" in html


def test_copyable_and_diff_annotations_preserve_multiline_review_text() -> None:
    schema = {
        "title": "Publish review",
        "type": "object",
        "properties": {
            "description": {
                "title": "Final description",
                "x-view": {"copyable": True, "diff": True},
            }
        },
    }

    html = render_schema_document({"description": "first line\nsecond line"}, schema)

    assert 'class="copyable-content view-diff"' in html
    assert "first line\nsecond line" in html
    assert "コピー対象" in html


def test_analysis_report_prioritizes_decisions_and_preserves_additional_root_content() -> None:
    fixture = FIXTURES_DIR / "documents" / "analysis-report.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))

    html = render_repository_document(RepositorySchema.ANALYSIS_REPORT, document)

    assert html.index("再生初動は基準を上回る") < html.index("主要指標") < html.index("入力と根拠")
    assert "uv run yt-channel-trend" in html
    assert "<summary>入力と根拠</summary>" in html
    assert "<summary>実行 command</summary>" in html
    assert "<summary>daily_observations</summary>" in html
    assert "watch_hours" in html


def test_common_view_uses_local_japanese_fonts_and_visible_keyboard_focus() -> None:
    html = render_schema_document(
        {"summary": "Ready", "rows": [], "asset": "assets/preview.jpg"},
        _view_schema(),
    )

    assert '"Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic", Meiryo' in html
    assert ":focus-visible" in html


def test_common_view_carries_hallmark_austere_tokens_and_mobile_containment() -> None:
    html = render_schema_document(
        {"summary": "Ready", "rows": [], "asset": "assets/preview.jpg"},
        _view_schema(),
    )

    assert "Hallmark · macrostructure: Long Document" in html
    assert "Hallmark · pre-emit critique: P5 H5 E5 S5 R5 V4" in html
    assert "--color-paper:" in html
    assert "--font-body:" in html
    assert "--space-page:" in html
    assert "html,\nbody" in html
    assert "overflow-x: clip" in html
    assert "box-shadow:" not in html


def test_render_escapes_markup_and_embedded_json_script_boundary() -> None:
    malicious = '</script><script>alert("owned")</script>& {{CSS}} {{DATA}} $CSS'
    html = render_schema_document(
        {"summary": malicious, "rows": [], "asset": "assets/preview.jpg"},
        _view_schema(),
    )

    assert malicious not in html
    assert "&lt;/script&gt;&lt;script&gt;alert(&quot;owned&quot;)" in html
    assert "\\u003c/script\\u003e\\u003cscript\\u003e" in html
    assert "{{CSS}} {{DATA}} $CSS" in html
    embedded = html.split('<script id="document-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert json.loads(embedded)["summary"] == malicious


def test_music_prompt_entries_render_as_readable_cards_with_album_flow() -> None:
    document = {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "engine": "minimax",
        "collection_id": "night-drive",
        "provenance": {"producer": "music", "source_paths": ["plan.json"]},
        "entries": [
            {
                "name": "01-opening",
                "title": "Neon <Drive>",
                "style": "synthwave\nslow build",
                "lyrics": "[Instrumental]",
                "sections": ["intro", "build", "outro"],
                "quality": {"score": 92, "summary": "cohesive"},
                "options": {"model": "music-2.0"},
                "track_role": "opening",
                "review": {"verify_status": "pass", "semantic_status": "pass", "notes": []},
            }
        ],
    }

    html = render_repository_document(RepositorySchema.MUSIC_PROMPT, document)

    assert 'class="card-flow"' in html
    assert 'class="entry-card"' in html
    assert "Neon &lt;Drive&gt;" in html
    assert "synthwave\nslow build" in html
    assert html.index("Song title") < html.index("Style / prompt") < html.index("Lyrics")


@pytest.mark.parametrize(
    "asset",
    [
        "https://example.com/image.jpg",
        "//example.com/image.jpg",
        "../secret.jpg",
        "assets/%2e%2e/secret.jpg",
    ],
)
def test_media_rejects_non_local_asset_references(asset: str) -> None:
    with pytest.raises(DocumentRenderError, match="local asset"):
        render_schema_document({"summary": "Ready", "rows": [], "asset": asset}, _view_schema())


def test_repository_renderer_validates_before_rendering() -> None:
    with pytest.raises(DocumentValidationError, match="pointer=/"):
        render_repository_document(RepositorySchema.WEEKLY_VOTE_LOG, {"entries": []})


def test_repository_renderer_resolves_local_ref_for_table_columns() -> None:
    html = render_repository_document(
        RepositorySchema.WEEKLY_VOTE_LOG,
        {
            "schema_version": 1,
            "entries": [
                {
                    "week_start": "2026-08-10",
                    "axes": [{"key": "calm", "label": "Calm", "votes": 3}],
                    "top_axis": "calm",
                }
            ],
        },
    )

    assert "<th>week_start</th>" in html
    assert "<th>notes</th>" in html


def test_same_document_schema_and_resources_are_byte_stable() -> None:
    document = {"summary": "Ready", "rows": [{"name": "CTR", "score": 8.2}], "asset": "assets/a.jpg"}
    schema = _view_schema()

    assert render_schema_document(document, schema) == render_schema_document(document, schema)


@pytest.mark.parametrize(
    "html",
    [
        "<!doctype html><html><body><script>alert(1)</script></body></html>",
        '<!doctype html><html><body><img src="https://example.com/a.jpg"></body></html>',
    ],
)
def test_generated_html_validator_rejects_executable_or_external_content(html: str) -> None:
    with pytest.raises(DocumentRenderError):
        validate_generated_html(html)
