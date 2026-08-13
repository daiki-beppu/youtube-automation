from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from youtube_automation.commands.analytics import vpd_rank as cli
from youtube_automation.core.errors import ValidationError
from youtube_automation.infrastructure.analytics.vpd_metrics import (
    build_vpd_ranking,
    collect_all_video_statistics,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)


def _video(
    video_id: str,
    published_at: str,
    views: object,
    *,
    duration: object = "PT1M",
) -> dict[str, object]:
    return {
        "video_id": video_id,
        "title": f"title-{video_id}",
        "published_at": published_at,
        "cumulative_views": views,
        "duration": duration,
    }


class _Collector:
    def __init__(self) -> None:
        self.video_ids = [f"v{i:02d}" for i in range(51)]
        self.pages_refreshed: list[bool] = []
        self.batches: list[list[str]] = []

    def get_all_channel_videos(self, refresh: bool = False) -> list[dict[str, str]]:
        self.pages_refreshed.append(refresh)
        return [
            {
                "video_id": video_id,
                "title": f"title-{video_id}",
                "published_at": "2026-07-01T00:00:00Z",
            }
            for video_id in self.video_ids
        ]

    def get_video_details(self, video_ids: list[str]) -> dict[str, dict[str, object]]:
        self.batches.append(video_ids)
        return {
            video_id: {
                "view_count": str(index + 1),
                "duration": f"PT{int(video_id.removeprefix('v')) + 1}M",
            }
            for index, video_id in enumerate(video_ids)
        }


def test_collects_every_paginated_upload_and_batches_statistics_at_fifty() -> None:
    collector = _Collector()

    result = collect_all_video_statistics(collector)

    assert collector.pages_refreshed == [True]
    assert [len(batch) for batch in collector.batches] == [50, 1]
    assert [item["video_id"] for item in result] == collector.video_ids
    assert result[-1]["cumulative_views"] == 1
    assert result[0]["duration"] == "PT1M"
    assert result[49]["duration"] == "PT50M"
    assert result[50]["duration"] == "PT51M"


@pytest.mark.parametrize(
    "details",
    [
        {"view_count": "1"},
        {"view_count": "1", "duration": None},
        {"view_count": "1", "duration": ""},
        {"view_count": "1", "duration": "not-a-duration"},
        {"view_count": "1", "duration": "PT0S"},
        {"view_count": "1", "duration": 60},
    ],
)
def test_missing_or_invalid_duration_is_explicitly_undetermined(details: dict[str, object]) -> None:
    collector = _Collector()
    collector.video_ids = ["v00"]
    collector.get_video_details = lambda _ids: {"v00": details}  # type: ignore[method-assign]

    result = collect_all_video_statistics(collector)

    assert result[0]["duration"] is None


@pytest.mark.parametrize("details", [{}, {"v00": {}}, {"v00": {"view_count": "invalid"}}])
def test_missing_or_invalid_view_count_fails_closed(details: dict[str, object]) -> None:
    collector = _Collector()
    collector.video_ids = ["v00"]
    collector.get_video_details = lambda _ids: details  # type: ignore[method-assign]

    with pytest.raises(ValidationError, match="viewCount"):
        collect_all_video_statistics(collector)


def test_ranks_by_vpd_then_video_id_and_uses_utc_calendar_age() -> None:
    result = build_vpd_ranking(
        [
            _video("b", "2026-08-12T23:59:00-05:00", 100),  # UTC 8/13: age 0 -> 1
            _video("a", "2026-08-13T00:01:00+09:00", 100),  # UTC 8/12: age 1
            _video("c", "2026-08-11T00:00:00Z", 100),
            _video("d", "2026-08-09T00:00:00Z", 10),
        ],
        now=NOW,
        min_age_days=0,
    )

    assert result["k"] == 1
    assert [(item["video_id"], item["days_since_publish"]) for item in result["ranking"]] == [
        ("a", 1),
        ("b", 1),
        ("c", 2),
        ("d", 4),
    ]


def test_min_age_default_and_quartile_size_partition_the_population() -> None:
    videos = [_video(f"v{i}", f"2026-07-{i + 1:02d}T00:00:00Z", i + 1) for i in range(7)]
    videos.append(_video("recent", "2026-08-13T00:00:00Z", 100))

    result = build_vpd_ranking(videos, now=NOW)

    assert result["n"] == 7
    assert result["k"] == 2
    assert result["min_age_days"] == 7
    assert result["excluded_count"] == 1
    assert [result["groups"][name]["count"] for name in ("top", "middle", "bottom")] == [2, 3, 2]


def test_fewer_than_two_eligible_videos_fails() -> None:
    with pytest.raises(ValidationError, match="2 本以上"):
        build_vpd_ranking([_video("v", "2026-01-01T00:00:00Z", 1)], now=NOW)


@pytest.mark.parametrize("top_count", [0, 3])
def test_top_count_must_keep_top_and_bottom_disjoint(top_count: int) -> None:
    videos = [_video(f"v{i}", "2026-01-01T00:00:00Z", i) for i in range(4)]

    with pytest.raises(ValidationError, match="top-count"):
        build_vpd_ranking(videos, now=NOW, top_count=top_count)


def test_top_count_override_and_empty_middle_group_are_supported() -> None:
    result = build_vpd_ranking(
        [_video("a", "2026-01-01T00:00:00Z", 2), _video("b", "2026-01-01T00:00:00Z", 1)],
        now=NOW,
        top_count=1,
    )

    assert result["k"] == 1
    assert result["groups"]["middle"] == {"count": 0, "min_vpd": None, "max_vpd": None, "items": []}


def test_json_and_text_render_the_same_ranking(monkeypatch, capsys) -> None:
    ranking = build_vpd_ranking(
        [
            _video("a", "2026-01-01T00:00:00Z", 20, duration="PT2M"),
            _video("b", "2026-01-01T00:00:00Z", 10, duration="invalid"),
        ],
        now=NOW,
    )
    monkeypatch.setattr(cli, "_load_ranking", lambda **_kwargs: ranking)

    assert cli.main([]) == 0
    json_output = json.loads(capsys.readouterr().out)
    assert cli.main(["--text"]) == 0
    text_output = capsys.readouterr().out

    assert json_output == ranking
    assert [item["duration"] for item in ranking["ranking"]] == ["PT2M", None]
    for item in ranking["ranking"]:
        assert item["video_id"] in text_output
        assert str(item["vpd"]) in text_output
        assert f"duration={item['duration'] or 'undetermined'}" in text_output
