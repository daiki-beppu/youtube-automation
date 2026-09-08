"""Shared collection of dimension metrics and view shares over returned categories."""

from youtube_automation.domains.analytics.ports import AnalyticsClient
from youtube_automation.domains.analytics.query_contract import (
    TARGETED_QUERY_VIEWS_METRIC,
    TARGETED_QUERY_VIEWS_SORT,
)

DEFAULT_VIEW_FIELDS = ("views", "watch_time_minutes", "avg_view_duration")


def collect_view_breakdown(
    analytics_client: AnalyticsClient,
    channel_id: str | None,
    start_date: str,
    end_date: str,
    *,
    dimension: str,
    fields: tuple[str, ...] = DEFAULT_VIEW_FIELDS,
    metrics: str = f"{TARGETED_QUERY_VIEWS_METRIC},estimatedMinutesWatched,averageViewDuration",
    sort: str = TARGETED_QUERY_VIEWS_SORT,
    **query: object,
) -> tuple[dict, int | float]:
    """Collect a dimension's metrics and compute shares over the returned categories."""
    response = analytics_client.query(
        ids=f"channel=={channel_id}",
        startDate=start_date,
        endDate=end_date,
        metrics=metrics,
        dimensions=dimension,
        sort=sort,
        **query,
    )
    categories = {
        row[0]: {field: row[index] for index, field in enumerate(fields, start=1)} for row in response.get("rows", [])
    }
    total_views = sum(category["views"] for category in categories.values())
    for category in categories.values():
        category["view_share_percent"] = round(category["views"] / total_views * 100, 1) if total_views > 0 else 0
    return categories, total_views
