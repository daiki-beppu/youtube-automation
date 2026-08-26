from __future__ import annotations

from datetime import UTC, datetime

from youtube_automation.application.workflow_status import (
    ArtifactStatusView,
    CollectionStatusView,
    WorkflowStatusSnapshot,
)
from youtube_automation.domains.documents.workflow_status_rendering import (
    render_workflow_status,
    validate_workflow_status_html,
)


def _snapshot(name: str = "Night & Rain <script>alert(1)</script>") -> WorkflowStatusSnapshot:
    artifact = ArtifactStatusView(
        key="plan",
        label="企画",
        status="complete",
        detail="20-documentation/plan_proposals.json",
    )
    collection = CollectionStatusView(
        name=name,
        slug="night-rain",
        status="planning",
        phase="prepared",
        blocker="なし",
        next_action="/wf-next",
        updated_at="2026-08-16 10:00 UTC",
        stalled_for="2時間",
        stale=False,
        warnings=(),
        artifacts=(artifact,),
    )
    return WorkflowStatusSnapshot(
        generated_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        collections=(collection,),
    )


def test_renderer_escapes_untrusted_values_and_keeps_page_read_only() -> None:
    html = render_workflow_status(_snapshot())

    validate_workflow_status_html(html)
    assert "Night &amp; Rain &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html
    assert "<form" not in html
    assert "<button" not in html
    assert "href=" not in html
    assert "Content-Security-Policy" in html
    assert "theme: Midnight" in html
    assert "color-scheme: dark" in html


def test_renderer_embeds_shared_foundation_before_workflow_styles() -> None:
    html = render_workflow_status(_snapshot())

    assert html.count("--color-paper: oklch(13.5% 0.028 250deg)") == 1
    assert html.index("/* Documents design foundation") < html.index("/* Hallmark · macrostructure: Operational Queue")


def test_renderer_defers_page_gutters_to_shared_foundation() -> None:
    css = render_workflow_status(_snapshot()).split("<style>", 1)[1].split("</style>", 1)[0]
    screen_css = css.split("/* Hallmark · macrostructure: Operational Queue", 1)[1]

    assert css.count("padding: var(--space-page)") == 1
    assert "body {" not in screen_css
    assert "main {" not in screen_css


def test_renderer_provides_css_only_client_filters_for_all_statuses() -> None:
    html = render_workflow_status(_snapshot())

    for status in ("all", "planning", "live", "complete"):
        assert f'id="filter-{status}"' in html
    assert 'data-status="planning"' in html
    assert '<span class="filter-selected" aria-hidden="true">選択中 · </span>' in html
    assert ".filter-control:focus-visible" in html
    assert "#filter-planning:checked ~ .collection-grid [data-status]:not([data-status=planning])" in html
    assert 'aria-keyshortcuts="ArrowLeft ArrowRight Space"' in html
    assert "現在の表示" in html


def test_renderer_exposes_an_operational_overview_before_collection_rows() -> None:
    snapshot = WorkflowStatusSnapshot(
        generated_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        collections=(
            _snapshot().collections[0],
            CollectionStatusView(
                name="Published",
                slug="published",
                status="complete",
                phase="complete",
                blocker="なし",
                next_action="なし",
                updated_at="2026-08-16 11:00 UTC",
                stalled_for="1時間",
                stale=False,
                warnings=(),
                artifacts=(),
            ),
        ),
    )

    html = render_workflow_status(snapshot)

    assert html.index("運用サマリー") < html.index("Night &amp; Rain")
    assert '<strong class="overview-value">2</strong><span>全件</span>' in html
    assert '<strong class="overview-value">0</strong><span>要対応</span>' in html
    assert "Hallmark · pre-emit critique: P5 H5 E5 S5 R5 V5" in html
    assert "overflow-x: clip" in html


def test_attention_collections_and_missing_artifacts_render_before_normal_details() -> None:
    healthy = CollectionStatusView(
        name="Healthy collection",
        slug="healthy",
        status="complete",
        phase="complete",
        blocker="なし",
        next_action="なし",
        updated_at="2026-08-16 11:00 UTC",
        stalled_for="1時間",
        stale=False,
        warnings=(),
        artifacts=(ArtifactStatusView(key="plan", label="企画", status="complete", detail="plan.json"),),
    )
    attention = CollectionStatusView(
        name="Needs attention",
        slug="attention",
        status="planning",
        phase="prepared",
        blocker="master missing",
        next_action="/music --master",
        updated_at="2026-08-10 11:00 UTC",
        stalled_for="6日",
        stale=True,
        warnings=("workflow state が古い",),
        artifacts=(
            ArtifactStatusView(key="master", label="Master", status="missing", detail="01-master/master.mp3"),
            ArtifactStatusView(key="plan", label="企画", status="complete", detail="plan.json"),
        ),
    )
    snapshot = WorkflowStatusSnapshot(
        generated_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        collections=(healthy, attention),
    )

    html = render_workflow_status(snapshot)

    assert html.index("Needs attention") < html.index("Healthy collection")
    attention_start = html.index('data-slug="attention"')
    healthy_start = html.index('data-slug="healthy"')
    segment = html[attention_start:healthy_start]
    assert segment.index("phase") < segment.index("要対応") < segment.index("成果物の詳細")
    assert "停滞: 6日" in segment
    assert "Master: 未生成" in segment
    assert "workflow state が古い" in segment
    assert ".collection-card[data-attention=true]" not in html
    assert "border-bottom: 1px solid var(--color-rule-strong)" in html


def test_empty_snapshot_renders_an_explicit_empty_state() -> None:
    snapshot = WorkflowStatusSnapshot(
        generated_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        collections=(),
    )

    html = render_workflow_status(snapshot)

    assert "コレクションはありません" in html
    validate_workflow_status_html(html)
