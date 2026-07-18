"""TTP 健全性判定と CLI の契約テスト。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from youtube_automation.scripts import ttp_health_cli
from youtube_automation.utils.ttp_health import evaluate_ttp_health

REFERENCE_DATE = "2026-07-15"
CONFIG_CHANNEL = {"slug": "rival", "name": "Rival", "id": "UC_RIVAL"}


def _video(published_at: str, views: int) -> dict:
    return {"published_at": published_at, "views": views}


def _benchmark(
    videos: list[dict],
    *,
    latest: str | None = None,
    oldest: str | None = None,
    complete: bool = True,
) -> dict:
    dates = [video["published_at"] for video in videos]
    return {
        "collected_at": REFERENCE_DATE,
        "channels": [
            {
                "slug": "rival",
                "name": "Rival",
                "channel_id": "UC_RIVAL",
                "upload_scan": {
                    "scanned_count": len(videos),
                    "complete": complete,
                    "latest_upload_at": latest if latest is not None else (max(dates) if dates else None),
                    "oldest_upload_at": oldest if oldest is not None else (min(dates) if dates else None),
                    "videos": videos,
                },
            }
        ],
    }


def _channel_result(benchmark: dict, **kwargs) -> dict:
    return evaluate_ttp_health([CONFIG_CHANNEL], benchmark, **kwargs)["channels"][0]


def test_stale_posting_alert_contains_days_and_threshold() -> None:
    result = _channel_result(_benchmark([_video("2026-04-20", 42_000)], latest="2026-04-20", complete=True))

    stale = next(alert for alert in result["alerts"] if alert["type"] == "stale_posting")
    assert result["status"] == "alert"
    assert stale["days_since_last_upload"] == 86
    assert "86 日" in stale["reason"]
    assert "60 日" in stale["reason"]


def test_views_decline_contains_ratio_averages_and_windows() -> None:
    result = _channel_result(
        _benchmark(
            [
                _video("2026-02-01", 40_000),
                _video("2026-03-01", 44_000),
                _video("2026-06-01", 10_000),
                _video("2026-07-01", 14_000),
            ]
        )
    )

    alert = next(alert for alert in result["alerts"] if alert["type"] == "views_decline")
    assert alert["recent_avg_views"] == 12_000
    assert alert["prior_avg_views"] == 42_000
    assert alert["ratio"] == 0.29
    assert alert["recent_window"]["start"] == "2026-04-16"
    assert alert["prior_window"]["start"] == "2026-01-16"
    assert alert["prior_window"]["end"] == "2026-04-15"


def test_healthy_when_recent_upload_and_views_are_above_threshold() -> None:
    result = _channel_result(_benchmark([_video("2026-02-01", 10_000), _video("2026-06-15", 8_000)]))

    assert result["status"] == "healthy"
    assert result["alerts"] == []
    assert result["insufficiencies"] == []


def test_incomplete_coverage_is_insufficient_not_healthy() -> None:
    result = _channel_result(
        _benchmark(
            [_video("2026-03-17", 20_000), _video("2026-06-15", 5_000)],
            oldest="2026-03-17",
            complete=False,
        )
    )

    assert result["status"] == "insufficient_data"
    assert result["alerts"] == []
    assert {item["kind"] for item in result["insufficiencies"]} == {"incomplete_window_coverage"}


def test_missing_benchmark_entry_is_missing_data() -> None:
    result = _channel_result({"collected_at": REFERENCE_DATE, "channels": []})

    assert result["status"] == "missing_data"
    assert result["insufficiencies"][0]["kind"] == "missing_benchmark_entry"


def test_legacy_entry_without_upload_scan_is_missing_data() -> None:
    benchmark = {"collected_at": REFERENCE_DATE, "channels": [{"slug": "rival", "videos": []}]}

    result = _channel_result(benchmark)

    assert result["status"] == "missing_data"
    assert result["insufficiencies"][0]["kind"] == "missing_upload_scan"


def test_stale_and_decline_threshold_boundaries_are_inclusive() -> None:
    result = _channel_result(
        _benchmark(
            [_video("2026-02-01", 20_000), _video("2026-05-16", 10_000)],
            latest="2026-05-16",
        )
    )

    assert result["days_since_last_upload"] == 60
    assert {alert["type"] for alert in result["alerts"]} == {"stale_posting", "views_decline"}


def test_no_prior_uploads_is_insufficient_while_stale_check_remains_independent() -> None:
    result = _channel_result(_benchmark([_video("2026-06-01", 10_000)], complete=True))

    assert result["status"] == "insufficient_data"
    assert result["alerts"] == []
    assert result["insufficiencies"][0]["kind"] == "no_prior_window_uploads"


def test_no_recent_uploads_counts_as_zero_and_triggers_decline() -> None:
    result = _channel_result(_benchmark([_video("2026-02-01", 20_000)], complete=True))

    decline = next(alert for alert in result["alerts"] if alert["type"] == "views_decline")
    assert decline["recent_avg_views"] == 0
    assert decline["ratio"] == 0
    assert "投稿なし" in decline["reason"]


def test_stale_and_decline_can_both_be_reported() -> None:
    result = _channel_result(_benchmark([_video("2026-02-01", 20_000)], complete=True))

    assert result["status"] == "alert"
    assert {alert["type"] for alert in result["alerts"]} == {"stale_posting", "views_decline"}


def test_custom_thresholds_change_evaluation_and_output() -> None:
    report = evaluate_ttp_health(
        [CONFIG_CHANNEL],
        _benchmark([_video("2026-02-01", 10_000), _video("2026-06-15", 8_000)]),
        stale_days=30,
        decline_ratio=0.9,
        window_days=90,
    )

    assert report["thresholds"] == {"stale_days": 30, "decline_ratio": 0.9, "window_days": 90}
    assert {alert["type"] for alert in report["channels"][0]["alerts"]} == {
        "stale_posting",
        "views_decline",
    }


def test_invalid_video_date_is_not_silently_dropped() -> None:
    result = _channel_result(
        _benchmark(
            [_video("not-a-date", 99), _video("2026-02-01", 10_000), _video("2026-06-15", 8_000)],
            latest="2026-06-15",
            oldest="2026-02-01",
        )
    )

    assert result["status"] == "insufficient_data"
    assert "invalid_upload_date" in {item["kind"] for item in result["insufficiencies"]}


def test_cli_returns_unavailable_when_benchmark_json_is_missing(tmp_path, monkeypatch) -> None:
    config = SimpleNamespace(analytics=SimpleNamespace(benchmark=SimpleNamespace(channels=[CONFIG_CHANNEL])))
    monkeypatch.setattr(ttp_health_cli, "load_config", lambda: config)

    report = ttp_health_cli.build_report(data_dir=tmp_path)

    assert report["status"] == "unavailable"
    assert report["reason"] == "no_benchmark_json"


def test_cli_loads_latest_json_and_preserves_source_name(tmp_path, monkeypatch) -> None:
    config = SimpleNamespace(analytics=SimpleNamespace(benchmark=SimpleNamespace(channels=[CONFIG_CHANNEL])))
    monkeypatch.setattr(ttp_health_cli, "load_config", lambda: config)
    benchmark_path = tmp_path / "benchmark_20260715.json"
    benchmark_path.write_text(
        json.dumps(_benchmark([_video("2026-02-01", 10_000), _video("2026-06-15", 8_000)])),
        encoding="utf-8",
    )

    report = ttp_health_cli.build_report(data_dir=tmp_path)

    assert report["status"] == "ok"
    assert report["source"] == benchmark_path.name
    assert report["channels"][0]["status"] == "healthy"
