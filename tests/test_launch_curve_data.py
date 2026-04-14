import json
from pathlib import Path

import pandas as pd

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


def test_build_launch_curve_frame_has_required_columns():
    daily, meta = _load()
    df = build_launch_curve_frame(daily_data=daily, video_meta=meta)
    required = {
        "video_id", "date", "published_at", "days_since_publish",
        "daily_views", "cumulative_views", "daily_impressions", "ctr",
    }
    assert required.issubset(set(df.columns))
    assert isinstance(df, pd.DataFrame)
