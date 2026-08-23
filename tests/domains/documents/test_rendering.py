from __future__ import annotations

import json
from html.parser import HTMLParser

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


def _document_css(html: str) -> str:
    return html.split("<style>", 1)[1].split("</style>", 1)[0]


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

    assert '<details class="view-details" id="section-evidence">' in html
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


def test_status_annotation_drives_value_style_and_top_approval_summary() -> None:
    status_view = {
        "statusMap": {"pass": "pass", "fail": "fail", "pending": "warning"},
        "statusSummary": True,
    }
    schema = {
        "title": "Approval",
        "properties": {
            "checks": {
                "title": "Checks",
                "x-view": {"presentation": "cards"},
                "items": {
                    "properties": {
                        "name": {"title": "Name"},
                        "status": {"title": "Status", "x-view": status_view},
                    }
                },
            }
        },
    }

    html = render_schema_document(
        {"checks": [{"name": "syntax", "status": "fail"}, {"name": "meaning", "status": "pending"}]},
        schema,
    )

    approval = html.split('<section class="approval-summary', 1)[1].split("</section>", 1)[0]
    assert "syntax · Status" in approval
    assert "meaning · Status" in approval
    assert 'class="status-chip status-fail">fail</span>' in approval
    assert 'class="status-chip status-warning">pending</span>' in approval
    assert html.index("承認サマリー") < html.index("<h2>Checks</h2>")


def test_status_summary_does_not_collect_annotations_below_collapsed_section() -> None:
    schema = {
        "properties": {
            "audit": {
                "title": "Audit",
                "x-view": {"collapsed": True},
                "properties": {
                    "status": {
                        "title": "Audit status",
                        "x-view": {"statusMap": {"pass": "pass"}, "statusSummary": True},
                    }
                },
            },
            "decision": {
                "title": "Decision",
                "x-view": {"statusMap": {"pass": "pass"}, "statusSummary": True},
            },
        }
    }

    html = render_schema_document({"audit": {"status": "pass"}, "decision": "pass"}, schema)
    approval = html.split('<section class="approval-summary', 1)[1].split("</section>", 1)[0]

    assert "Decision" in approval
    assert "Audit status" not in approval
    assert approval.count('class="status-chip') == 1


@pytest.mark.parametrize(
    "schema_name, expected_labels, expected_statuses",
    [
        (RepositorySchema.VIDEO_DESCRIPTION, ["Quality checks · Status"], ["pass"]),
        (
            RepositorySchema.MUSIC_PROMPT,
            ["Rain Window · Machine verification", "Rain Window · Semantic review"],
            ["pass", "pass"],
        ),
        (
            RepositorySchema.COLLECTION_PLAN,
            [
                "Rainy Midnight Focus · 選択 status",
                "Neon Study Session · 選択 status",
                "Quiet Window Beats · 選択 status",
            ],
            ["selected", "rejected", "proposed"],
        ),
    ],
)
def test_review_fixtures_show_real_statuses_above_collapsed_details(
    schema_name: RepositorySchema, expected_labels: list[str], expected_statuses: list[str]
) -> None:
    fixture = FIXTURES_DIR / "documents" / schema_name.value.replace(".schema", "")
    html = render_repository_document(schema_name, json.loads(fixture.read_text(encoding="utf-8")))
    approval = html.split('<section class="approval-summary', 1)[1].split("</section>", 1)[0]

    assert all(label in approval for label in expected_labels)
    assert all(f">{status}</span>" in approval for status in expected_statuses)
    assert approval.count('class="status-chip') == len(expected_statuses)
    assert html.index("承認サマリー") < html.index('class="review-nav"')


def test_collection_plan_uses_schema_label_and_group_order_across_navigation_comparison_and_cards() -> None:
    fixture = FIXTURES_DIR / "documents" / "collection-plan.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    # 採用候補を入力末尾へ置き、schema の itemGroups が表示順の正本になることを確認する。
    document["candidates"] = document["candidates"][1:] + document["candidates"][:1]

    html = render_repository_document(RepositorySchema.COLLECTION_PLAN, document)
    comparison = html.split('<section class="candidate-comparison">', 1)[1].split("</section>", 1)[0]

    titles = [candidate["final_title"] for candidate in document["candidates"]]
    selected_title = document["candidates"][-1]["final_title"]
    assert "Entry 1" not in html
    assert f"<h3>{selected_title}</h3>" in html
    assert f">{selected_title}</a>" in html
    assert comparison.index(selected_title) < comparison.index(titles[0])
    assert html.index(f">{selected_title}</a>") < html.index(f">{titles[0]}</a>")


def test_music_prompt_fixture_renders_style_as_copyable_content() -> None:
    fixture = FIXTURES_DIR / "documents" / "music-prompt.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))

    html = render_repository_document(RepositorySchema.MUSIC_PROMPT, document)

    style = document["entries"][0]["style"]
    copyable = html.split("Style / prompt</dt><dd>", 1)[1].split("</dd>", 1)[0]
    assert 'class="copyable-content"' in copyable
    assert style in copyable


@pytest.mark.parametrize("label_field", ["", 42, ["title"]])
def test_cards_label_field_annotation_rejects_invalid_types(label_field: object) -> None:
    schema = {
        "properties": {
            "entries": {
                "x-view": {"presentation": "cards", "labelField": label_field},
                "items": {"properties": {"final_title": {}}},
            }
        }
    }

    with pytest.raises(DocumentRenderError, match="labelField"):
        render_schema_document({"entries": [{"final_title": "Plan"}]}, schema)


@pytest.mark.parametrize("item", [{}, {"final_title": 42}, {"final_title": ""}])
def test_cards_label_field_fails_closed_when_item_has_no_nonempty_string(item: dict[str, object]) -> None:
    schema = {
        "properties": {
            "entries": {
                "x-view": {"presentation": "cards", "labelField": "final_title"},
                "items": {"properties": {"final_title": {}}},
            }
        }
    }

    with pytest.raises(DocumentRenderError, match="labelField"):
        render_schema_document({"entries": [item]}, schema)


@pytest.mark.parametrize("presentation", ["card", "table", "cards", "media"])
def test_collapsed_section_preserves_its_presentation_and_review_modifiers(presentation: str) -> None:
    values = {
        "card": ({"name": "A"}, {"properties": {"name": {}}}),
        "table": ([{"name": "A"}], {"items": {"properties": {"name": {}}}}),
        "cards": ([{"title": "A"}], {"items": {"properties": {"title": {}}}}),
        "media": ("assets/a.jpg", {}),
    }
    value, extra = values[presentation]
    view = {
        "presentation": presentation,
        "collapsed": True,
        "summary": True,
        "priority": "high",
    }
    if presentation == "media":
        view["mediaType"] = "image"
    section = {"title": "Review", "x-view": view, **extra}
    html = render_schema_document({"review": value}, {"properties": {"review": section}})

    assert 'class="view-details view-summary view-priority-high"' in html
    assert {
        "card": "<dl>",
        "table": "view-table",
        "cards": "entry-card-grid",
        "media": "<img",
    }[presentation] in html


@pytest.mark.parametrize("presentation", ["card", "table", "cards", "media"])
def test_collapsed_section_renders_its_heading_and_description_once(presentation: str) -> None:
    values = {
        "card": ({"name": "A"}, {"properties": {"name": {}}}),
        "table": ([{"name": "A"}], {"items": {"properties": {"name": {}}}}),
        "cards": ([{"title": "A"}], {"items": {"properties": {"title": {}}}}),
        "media": ("assets/a.jpg", {}),
    }
    value, extra = values[presentation]
    view = {"presentation": presentation, "collapsed": True}
    if presentation == "media":
        view["mediaType"] = "image"
    section = {
        "title": "Unique section heading",
        "description": "Unique section description",
        "x-view": view,
        **extra,
    }

    html = render_schema_document({"review": value}, {"properties": {"review": section}})

    assert html.count("<summary>Unique section heading</summary>") == 1
    assert html.count("Unique section description") == 1
    assert "<h2>Unique section heading</h2>" not in html


def test_collapsed_details_presentation_does_not_nest_a_second_disclosure() -> None:
    schema = {
        "title": "Approval",
        "type": "object",
        "properties": {
            "audit": {
                "title": "Audit trail",
                "x-view": {"presentation": "details", "collapsed": True},
            }
        },
    }

    html = render_schema_document({"audit": {"source": "plan.json"}}, schema)
    body = html.split("<main>", 1)[1].split("</main>", 1)[0]

    assert body.count("<details") == 1
    assert "<summary>Audit trail</summary>" in body
    assert "詳細を表示" not in body


def test_priority_critical_and_high_are_visually_distinguishable() -> None:
    css = _document_css(
        render_schema_document(
            {"summary": "Ready", "rows": [], "asset": "assets/preview.jpg"},
            _view_schema(),
        )
    )
    declarations = {
        selector: css.split(f"{selector} {{", 1)[1].split("}", 1)[0].strip()
        for selector in (".view-priority-critical", ".view-priority-high")
    }

    assert declarations[".view-priority-critical"] != declarations[".view-priority-high"]


def test_review_view_offers_sticky_toc_and_explains_csp_safe_copy_and_search() -> None:
    html = render_schema_document(
        {"description": "line one\nline two", "tracks": [{"title": "Opening"}]},
        {
            "title": "Release review",
            "properties": {
                "description": {"title": "Final description", "x-view": {"copyable": True}},
                "tracks": {
                    "title": "Tracks",
                    "x-view": {"presentation": "cards"},
                    "items": {"properties": {"title": {}}},
                },
            },
        },
    )

    assert 'class="review-nav"' in html
    assert 'href="#section-description"' in html
    assert 'id="section-description"' in html
    assert 'href="#section-tracks-1"' in html
    assert "Ctrl/⌘+F" in html
    assert "選択してコピー" in html
    assert "position: sticky" in html
    assert "@media (max-width: 39.99rem)" in html


def test_cards_anchors_are_namespaced_per_section_so_two_card_lists_do_not_collide() -> None:
    cards_view = {"presentation": "cards"}
    item_schema = {"properties": {"title": {}}}
    html = render_schema_document(
        {"tracks": [{"title": "Opening"}], "candidates": [{"title": "Plan A"}]},
        {
            "title": "Release review",
            "properties": {
                "tracks": {"title": "Tracks", "x-view": cards_view, "items": item_schema},
                "candidates": {"title": "Candidates", "x-view": cards_view, "items": item_schema},
            },
        },
    )

    assert 'id="section-tracks-1"' in html
    assert 'id="section-candidates-1"' in html
    assert 'href="#section-candidates-1"' in html
    assert 'id="track-1"' not in html


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
    assert 'id="section-entries-1"' in html
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


@pytest.mark.parametrize(
    ("fixture_name", "schema"),
    [
        ("collection-plan.json", RepositorySchema.COLLECTION_PLAN),
        ("music-prompt.json", RepositorySchema.MUSIC_PROMPT),
        ("video-description.json", RepositorySchema.VIDEO_DESCRIPTION),
    ],
)
def test_representative_review_fixture_validates_and_renders_end_to_end(
    fixture_name: str, schema: RepositorySchema
) -> None:
    document = json.loads((FIXTURES_DIR / "documents" / fixture_name).read_text(encoding="utf-8"))

    html = render_repository_document(schema, document)

    assert '<nav class="review-nav"' in html
    assert "<main>" in html
    validate_generated_html(html)


def test_collection_plan_review_prioritizes_selection_and_compares_then_collapses_others() -> None:
    document = json.loads((FIXTURES_DIR / "documents" / "collection-plan.json").read_text(encoding="utf-8"))

    html = render_repository_document(RepositorySchema.COLLECTION_PLAN, document)

    assert '<section class="candidate-comparison"><h3>候補比較</h3>' in html
    assert html.index("採用候補") < html.index("Rainy Midnight Focus", html.index("採用候補"))
    assert "<summary>未採用・検討中候補</summary>" in html
    assert html.index("採用候補") < html.index("未採用・検討中候補")
    assert "選択 status" in html


@pytest.mark.parametrize("presentation", ["card", "cards", "details", "table", "media"])
@pytest.mark.parametrize("collapsed", [False, True])
def test_navigation_anchor_is_the_section_root_without_extra_grid_item(presentation: str, collapsed: bool) -> None:
    values = {
        "card": ({"name": "A"}, {"properties": {"name": {}}}),
        "cards": ([{"title": "A"}], {"items": {"properties": {"title": {}}}}),
        "details": ({"name": "A"}, {"properties": {"name": {}}}),
        "table": ([{"name": "A"}], {"items": {"properties": {"name": {}}}}),
        "media": ("assets/a.jpg", {}),
    }
    value, extra = values[presentation]
    view: dict[str, object] = {"presentation": presentation, "collapsed": collapsed}
    if presentation == "media":
        view["mediaType"] = "image"
    schema = {"properties": {"review unsafe": {"title": "Review", "x-view": view, **extra}}}

    html = render_schema_document({"review unsafe": value}, schema)

    class MainChildrenParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.depth = 0
            self.children: list[tuple[str, dict[str, str | None]]] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "main":
                self.depth = 1
            elif self.depth:
                if self.depth == 1:
                    self.children.append((tag, dict(attrs)))
                if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}:
                    self.depth += 1

        def handle_endtag(self, tag: str) -> None:
            if self.depth:
                self.depth -= 1

    parser = MainChildrenParser()
    parser.feed(html)
    anchored = [(tag, attrs) for tag, attrs in parser.children if attrs.get("id") == "section-review-unsafe"]
    href_target = html.split('href="#section-review-unsafe"', 1)

    assert len(href_target) == 2
    assert len(anchored) == 1
    assert anchored[0][0] in {"section", "details"}
    assert "section-anchor" not in html
    # 承認サマリーなしでは、本文 section と nav だけが main grid item になる。
    assert len(parser.children) == 2


def test_collection_plan_resolved_rejection_is_neutral_but_proposal_warns() -> None:
    fixture = FIXTURES_DIR / "documents" / "collection-plan.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    document["candidates"] = [
        candidate for candidate in document["candidates"] if candidate["selection_status"] != "proposed"
    ]

    resolved_html = render_repository_document(RepositorySchema.COLLECTION_PLAN, document)
    unresolved_document = json.loads(fixture.read_text(encoding="utf-8"))
    unresolved_html = render_repository_document(RepositorySchema.COLLECTION_PLAN, unresolved_document)

    assert 'class="status-chip status-neutral">rejected</span>' in resolved_html
    assert 'class="approval-summary approval-pass"' in resolved_html
    assert 'class="approval-summary approval-warning"' not in resolved_html
    assert 'class="status-chip status-warning">proposed</span>' in unresolved_html
    assert 'class="approval-summary approval-warning"' in unresolved_html
