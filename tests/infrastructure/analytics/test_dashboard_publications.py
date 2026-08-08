import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from youtube_automation.infrastructure.analytics import dashboard_publications
from youtube_automation.infrastructure.analytics.dashboard_publications import (
    build_dashboard_publications,
    load_fresh_dashboard_publications,
    save_dashboard_publications,
)


def _publication_payload(fetched_at: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "fetched_at": fetched_at,
        "timezone": "UTC",
        "days": {"2026-08-08": 2},
    }


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


def test_save_dashboard_publications_replaces_with_complete_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "dashboard_publications.json"
    payload = {"schema_version": 1, "days": {"2026-08-08": 2}}
    real_replace = os.replace
    observed_temporary: Path | None = None

    def inspect_then_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        nonlocal observed_temporary
        observed_temporary = Path(source)
        assert observed_temporary.parent == destination.parent
        assert json.loads(observed_temporary.read_text(encoding="utf-8")) == payload
        real_replace(source, target)

    monkeypatch.setattr(dashboard_publications.os, "replace", inspect_then_replace)

    save_dashboard_publications(destination, payload)

    assert json.loads(destination.read_text(encoding="utf-8")) == payload
    assert observed_temporary is not None
    assert not observed_temporary.exists()


def test_save_dashboard_publications_preserves_destination_and_cleans_temp_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "dashboard_publications.json"
    original = b'{"existing": true}\n'
    destination.write_bytes(original)
    observed_temporary: Path | None = None

    def fail_replace(source: str | os.PathLike[str], _target: str | os.PathLike[str]) -> None:
        nonlocal observed_temporary
        observed_temporary = Path(source)
        raise OSError("injected replace failure")

    monkeypatch.setattr(dashboard_publications.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        save_dashboard_publications(destination, {"replacement": True})

    assert destination.read_bytes() == original
    assert observed_temporary is not None
    assert not observed_temporary.exists()


def test_load_fresh_dashboard_publications_should_return_payload_when_cache_is_24_hours_old(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dashboard_publications.json"
    payload = _publication_payload("2026-08-07T12:00:00+00:00")
    source.write_text(json.dumps(payload), encoding="utf-8")

    result = load_fresh_dashboard_publications(
        source,
        now=datetime(2026, 8, 8, 12, tzinfo=UTC),
    )

    assert result == payload


def test_load_fresh_dashboard_publications_should_return_none_when_cache_is_older_than_24_hours(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dashboard_publications.json"
    source.write_text(
        json.dumps(_publication_payload("2026-08-07T11:59:59+00:00")),
        encoding="utf-8",
    )

    result = load_fresh_dashboard_publications(
        source,
        now=datetime(2026, 8, 8, 12, tzinfo=UTC),
    )

    assert result is None


@pytest.mark.parametrize(
    "content",
    [
        "{not-json",
        json.dumps({"schema_version": 2, "fetched_at": "2026-08-08T11:00:00+00:00"}),
        json.dumps(_publication_payload("not-a-timestamp")),
    ],
)
def test_load_fresh_dashboard_publications_should_return_none_when_cache_is_corrupt(
    tmp_path: Path,
    content: str,
) -> None:
    source = tmp_path / "dashboard_publications.json"
    source.write_text(content, encoding="utf-8")

    result = load_fresh_dashboard_publications(
        source,
        now=datetime(2026, 8, 8, 12, tzinfo=UTC),
    )

    assert result is None


def test_load_fresh_dashboard_publications_should_return_none_when_cache_is_missing(
    tmp_path: Path,
) -> None:
    result = load_fresh_dashboard_publications(
        tmp_path / "dashboard_publications.json",
        now=datetime(2026, 8, 8, 12, tzinfo=UTC),
    )

    assert result is None
