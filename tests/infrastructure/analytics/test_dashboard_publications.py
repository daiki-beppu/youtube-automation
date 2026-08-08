from datetime import UTC, datetime, timedelta

from youtube_automation.infrastructure.analytics.dashboard_publications import (
    build_dashboard_publications,
)


def test_build_dashboard_publications_groups_by_local_calendar_day() -> None:
    fetched_at = datetime(2026, 8, 9, 12, tzinfo=UTC)

    payload = build_dashboard_publications(
        [
            "2026-08-07T15:30:00Z",
            "2026-08-08T14:59:00Z",
            "2026-08-08T15:00:00Z",
        ],
        timezone="Asia/Tokyo",
        fetched_at=fetched_at,
    )

    assert payload == {
        "schema_version": 1,
        "fetched_at": "2026-08-09T12:00:00+00:00",
        "timezone": "Asia/Tokyo",
        "days": {
            "2026-08-08": 2,
            "2026-08-09": 1,
        },
    }


def test_build_dashboard_publications_includes_cutoff_and_excludes_older_timestamp() -> None:
    fetched_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    cutoff = fetched_at - timedelta(days=365)

    payload = build_dashboard_publications(
        [
            (cutoff - timedelta(microseconds=1)).isoformat(),
            cutoff.isoformat(),
            fetched_at.isoformat(),
        ],
        timezone="UTC",
        fetched_at=fetched_at,
    )

    assert payload["days"] == {
        "2025-08-08": 1,
        "2026-08-08": 1,
    }


def test_build_dashboard_publications_normalizes_fetched_at_to_utc() -> None:
    fetched_at = datetime.fromisoformat("2026-08-08T21:00:00+09:00")

    payload = build_dashboard_publications([], timezone="UTC", fetched_at=fetched_at)

    assert payload["fetched_at"] == "2026-08-08T12:00:00+00:00"
