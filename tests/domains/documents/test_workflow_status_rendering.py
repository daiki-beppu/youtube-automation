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


def test_renderer_provides_css_only_client_filters_for_all_statuses() -> None:
    html = render_workflow_status(_snapshot())

    for status in ("all", "planning", "live", "complete"):
        assert f'id="filter-{status}"' in html
    assert 'data-status="planning"' in html
    assert "#filter-planning:checked ~ .collection-grid [data-status]:not([data-status=planning])" in html


def test_empty_snapshot_renders_an_explicit_empty_state() -> None:
    snapshot = WorkflowStatusSnapshot(
        generated_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        collections=(),
    )

    html = render_workflow_status(snapshot)

    assert "コレクションはありません" in html
    validate_workflow_status_html(html)
