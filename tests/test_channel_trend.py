import pandas as pd
import pytest

from youtube_automation.utils.channel_trend import (
    analyze_channel_trend,
    build_trend_frame,
    detect_anomalies,
)


def _daily_metrics(dates, views_list, subs_list=None):
    subs_list = subs_list or [0] * len(dates)
    return [
        {
            "date": d,
            "views": v,
            "watch_time": v * 10,
            "subscribers_gained": s,
            "subscribers_lost": 0,
        }
        for d, v, s in zip(dates, views_list, subs_list, strict=True)
    ]


def test_build_trend_frame_computes_rolling_means():
    dates = [f"2026-04-{i:02d}" for i in range(1, 31)]
    views = list(range(10, 40))  # linearly increasing
    df = build_trend_frame(_daily_metrics(dates, views))
    assert len(df) == 30
    assert "views_7d_ma" in df.columns
    # 7日目の MA は過去7日の平均
    day7 = df.iloc[6]
    assert day7["views_7d_ma"] == pytest.approx(sum(views[:7]) / 7)


def test_detect_anomalies_flags_spike():
    dates = [f"2026-04-{i:02d}" for i in range(1, 21)]
    views = [10] * 15 + [100] + [10] * 4  # day 16 スパイク
    df = build_trend_frame(_daily_metrics(dates, views))
    anomalies = detect_anomalies(df, z_threshold=2.0)
    assert any(a["date"] == "2026-04-16" and a["type"] == "spike" for a in anomalies)


def test_detect_anomalies_uses_a_baseline_that_excludes_the_spike_day():
    dates = pd.date_range("2026-04-01", periods=16).strftime("%Y-%m-%d").tolist()
    views = [24, 6, 15, 26, 13, 7, 27, 30, 24, 23, 30, 10, 8, 19, 29, 41]

    result = analyze_channel_trend(_daily_metrics(dates, views))

    assert any(anomaly["date"] == "2026-04-16" and anomaly["type"] == "spike" for anomaly in result["anomalies"])


def test_detect_anomalies_flags_dip():
    dates = [f"2026-04-{i:02d}" for i in range(1, 21)]
    views = [100] * 15 + [5] + [100] * 4
    df = build_trend_frame(_daily_metrics(dates, views))
    anomalies = detect_anomalies(df, z_threshold=2.0)
    assert any(a["date"] == "2026-04-16" and a["type"] == "dip" for a in anomalies)


def test_analyze_channel_trend_marks_z_score_as_undetermined_before_min_periods():
    dates = pd.date_range("2026-04-01", periods=7).strftime("%Y-%m-%d").tolist()
    result = analyze_channel_trend(_daily_metrics(dates, list(range(10, 17))))

    assert [day["views_z_score"] for day in result["daily_series"]] == [None] * 7
    assert result["anomalies"] == []


def test_analyze_channel_trend_produces_summary():
    dates = [f"2026-04-{i:02d}" for i in range(1, 15)]
    views = list(range(10, 24))  # 成長傾向
    subs = [1] * 14
    result = analyze_channel_trend(_daily_metrics(dates, views, subs))
    assert result["summary"]["total_views"] == sum(views)
    assert result["summary"]["total_subs_gained"] == 14
    assert result["summary"]["trend_direction"] in {"up", "flat", "down"}
    assert "daily_series" in result
    assert "anomalies" in result
    assert "week_over_week" in result


def test_analyze_channel_trend_detects_upward_trend():
    dates = pd.date_range("2026-04-01", periods=56).strftime("%Y-%m-%d").tolist()
    views = [100] * 28 + [100] * 7 + [140] * 14 + [80] * 7
    result = analyze_channel_trend(_daily_metrics(dates, views))
    assert result["summary"]["trend_direction"] == "up"


def test_analyze_channel_trend_handles_empty():
    result = analyze_channel_trend([])
    assert result["summary"]["total_views"] == 0
    assert result["daily_series"] == []
    assert result["anomalies"] == []


def test_week_over_week_includes_delta_pct():
    # 月曜開始 (2026-03-02 は月曜) で 3 週揃え、各週の total が 70/140/105 になるよう設計
    dates = pd.date_range("2026-03-02", periods=21).strftime("%Y-%m-%d").tolist()
    views = [10] * 7 + [20] * 7 + [15] * 7
    result = analyze_channel_trend(_daily_metrics(dates, views))
    wow = result["week_over_week"]
    totals = {w["week_starting"]: w["views"] for w in wow}
    assert totals.get("2026-03-02") == 70
    assert totals.get("2026-03-09") == 140
    assert totals.get("2026-03-16") == 105
    # 2週目 (3/9 開始) の delta_pct は (140-70)/70 = +100%
    w2 = next(w for w in wow if w["week_starting"] == "2026-03-09")
    assert w2["delta_pct"] == pytest.approx(100.0, abs=0.01)
    w3 = next(w for w in wow if w["week_starting"] == "2026-03-16")
    assert w3["delta_pct"] == pytest.approx(-25.0, abs=0.01)


def test_week_over_week_excludes_leading_and_trailing_partial_weeks():
    dates = pd.date_range("2026-03-04", periods=24).strftime("%Y-%m-%d").tolist()
    views = [100] * 5 + [10] * 7 + [20] * 7 + [100] * 5

    result = analyze_channel_trend(_daily_metrics(dates, views))

    assert result["week_over_week"] == [
        {"week_starting": "2026-03-09", "views": 70, "delta_pct": None},
        {"week_starting": "2026-03-16", "views": 140, "delta_pct": 100.0},
    ]
    assert result["summary"]["wow_growth_rate"] == 100.0
