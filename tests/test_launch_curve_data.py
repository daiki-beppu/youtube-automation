import json
import sys
from pathlib import Path

import pandas as pd

from youtube_automation.scripts import launch_curve
from youtube_automation.utils.launch_curve_data import build_launch_curve_frame

FIXTURES = Path(__file__).parent / "fixtures" / "sample_launch_curve"


def _load():
    with open(FIXTURES / "daily_sample.json") as f:
        daily = json.load(f)
    with open(FIXTURES / "video_meta.json") as f:
        meta = json.load(f)
    return daily, meta


def test_build_launch_curve_frame_computes_days_since_publish():
    daily, meta = _load()
    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)

    vid_a_day0 = df[(df["video_id"] == "vid_A") & (df["days_since_publish"] == 0)]
    assert vid_a_day0["daily_views"].iloc[0] == 100

    vid_b_day0 = df[(df["video_id"] == "vid_B") & (df["days_since_publish"] == 0)]
    assert vid_b_day0["daily_views"].iloc[0] == 200


def test_build_launch_curve_frame_computes_cumulative_views():
    daily, meta = _load()
    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)

    vid_a = df[df["video_id"] == "vid_A"].sort_values("days_since_publish")
    assert list(vid_a["cumulative_views"]) == [100, 180, 240]


def test_build_launch_curve_frame_normalizes_publish_time_of_day():
    """published_at の時刻成分で day が 1 日ズレない（深夜 00:00 に正規化）"""
    daily = {
        "rows": [
            {"video_id": "v1", "date": "2026-04-01", "views": 10, "impressions": 0, "impression_ctr": 0.0},
            {"video_id": "v1", "date": "2026-04-02", "views": 20, "impressions": 0, "impression_ctr": 0.0},
        ]
    }
    # 公開時刻が午前 2 時でも、公開日（2026-04-01）は day 0 になるべき
    meta = {"v1": {"title": "v1", "published_at": "2026-04-01T02:00:00Z"}}
    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)
    day0 = df[df["days_since_publish"] == 0]
    assert day0["daily_views"].iloc[0] == 10
    day1 = df[df["days_since_publish"] == 1]
    assert day1["daily_views"].iloc[0] == 20


def test_build_launch_curve_frame_has_required_columns():
    daily, meta = _load()
    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)
    required = {
        "video_id",
        "date",
        "published_at",
        "days_since_publish",
        "daily_views",
        "cumulative_views",
        "daily_impressions",
        "ctr",
        "reporting_ctr_snapshot",
        "reporting_impressions_snapshot",
    }
    assert required.issubset(set(df.columns))
    assert isinstance(df, pd.DataFrame)


def test_build_launch_curve_frame_handles_missing_impressions_and_ctr_columns():
    daily = {
        "rows": [
            {"video_id": "v1", "date": "2026-04-01", "views": 10},
            {"video_id": "v1", "date": "2026-04-02", "views": 20},
        ]
    }
    meta = {"v1": {"title": "v1", "published_at": "2026-04-01T00:00:00Z"}}

    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)

    assert list(df["daily_impressions"]) == [0, 0]
    assert df["ctr"].isna().all()
    assert list(df["cumulative_views"]) == [10, 30]


def test_launch_curve_latest_handles_missing_impressions_and_ctr_columns(tmp_path, monkeypatch, capsys):
    daily_dir = tmp_path / "data" / "analytics" / "daily_per_video"
    daily_dir.mkdir(parents=True)
    with open(daily_dir / "2026-04-02.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "rows": [
                    {"video_id": "v1", "date": "2026-04-01", "views": 10},
                    {"video_id": "v2", "date": "2026-04-02", "views": 20},
                ]
            },
            f,
        )

    with open(tmp_path / "data" / "analytics_data_2026-04-02.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "video_analytics": {
                    "v1": {"title": "older", "published_at": "2026-04-01T00:00:00Z"},
                    "v2": {"title": "latest", "published_at": "2026-04-02T00:00:00Z"},
                }
            },
            f,
        )

    monkeypatch.setattr(launch_curve, "_channel_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["yt-launch-curve", "--latest"])

    assert launch_curve.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["target"]["video_id"] == "v2"
    assert payload["target"]["trace"][0]["daily_impressions"] == 0
    assert payload["target"]["trace"][0]["ctr"] is None
    assert payload["all_videos"][0]["latest_ctr"] is None


def test_build_launch_curve_frame_merges_reporting_snapshot():
    """Reporting API snapshot があれば per_video CTR / impressions が broadcast される (#84)。"""
    daily, meta = _load()
    snapshot = {
        "per_video": [
            {"video_id": "vid_A", "ctr_percentage": 5.5, "impressions": 1234},
            {"video_id": "vid_B", "ctr_percentage": 4.0, "impressions": 2345},
        ]
    }
    df = build_launch_curve_frame(daily_data=daily, video_meta=meta, reporting_snapshot=snapshot)

    vid_a = df[df["video_id"] == "vid_A"].iloc[0]
    assert vid_a["reporting_ctr_snapshot"] == 5.5
    assert vid_a["reporting_impressions_snapshot"] == 1234

    vid_b = df[df["video_id"] == "vid_B"].iloc[0]
    assert vid_b["reporting_ctr_snapshot"] == 4.0


def test_build_launch_curve_frame_without_reporting_snapshot_keeps_columns():
    daily, meta = _load()
    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)
    assert df["reporting_ctr_snapshot"].isna().all()
    assert df["reporting_impressions_snapshot"].isna().all()
