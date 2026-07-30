import pandas as pd
import pytest

from youtube_automation.domains.analytics.analysis.launch_curve_analyzer import (
    compute_benchmark,
    judge_video_vs_benchmark,
)


def _make_frame():
    # 5 動画の day 0..6 累積 views
    # day 3 → cumulative_views = [100, 200, 300, 400, 500] (p25=200, p50=300, p75=400)
    records = []
    base_cumvals = [
        [10, 30, 60, 100, 150, 210, 280],
        [20, 60, 120, 200, 300, 420, 560],
        [30, 90, 180, 300, 450, 630, 840],
        [40, 120, 240, 400, 600, 840, 1120],
        [50, 150, 300, 500, 750, 1050, 1400],
    ]
    for i, vals in enumerate(base_cumvals):
        for day, cum in enumerate(vals):
            records.append(
                {
                    "video_id": f"vid_{i}",
                    "days_since_publish": day,
                    "cumulative_views": cum,
                    "daily_views": cum - (vals[day - 1] if day > 0 else 0),
                    "daily_impressions": 0,
                    "ctr": 0.0,
                }
            )
    return pd.DataFrame(records)


def test_compute_benchmark_returns_percentiles_per_day():
    df = _make_frame()
    bench = compute_benchmark(df, metric="cumulative_views")
    row = bench.loc[bench["days_since_publish"] == 3].iloc[0]
    assert row["p50"] == 300
    assert row["p25"] == 200
    assert row["p75"] == 400
    assert row["sample_size"] == 5


def test_compute_benchmark_excludes_target_video():
    df = _make_frame()
    bench = compute_benchmark(df, metric="cumulative_views", exclude_video_id="vid_4")
    row = bench.loc[bench["days_since_publish"] == 3].iloc[0]
    # Without vid_4: [100, 200, 300, 400] → p50=250
    assert row["p50"] == 250
    assert row["sample_size"] == 4


def test_judge_video_vs_benchmark_labels_quartile():
    df = _make_frame()
    bench = compute_benchmark(df, metric="cumulative_views", exclude_video_id="vid_4")
    judgement = judge_video_vs_benchmark(
        df,
        bench,
        video_id="vid_4",
        at_day=3,
        metric="cumulative_views",
    )
    assert judgement["value"] == 500
    assert judgement["benchmark_median"] == 250
    assert judgement["ratio_vs_median"] == pytest.approx(2.0)
    assert judgement["quartile_label"] == "上位25%"


def test_compute_benchmark_flags_small_sample():
    df = _make_frame().head(2)
    bench = compute_benchmark(df, metric="cumulative_views")
    assert (bench["sample_size"] < 3).all()


def test_judge_reports_missing_target_day():
    judgement = judge_video_vs_benchmark(
        _make_frame(),
        compute_benchmark(_make_frame()),
        video_id="missing",
        at_day=3,
    )

    assert judgement == {"error": "video missing has no data at day 3"}


@pytest.mark.parametrize(
    ("benchmark", "expected_sample_size"),
    [
        (pd.DataFrame(columns=["days_since_publish", "sample_size"]), 0),
        (
            pd.DataFrame(
                [
                    {
                        "days_since_publish": 3,
                        "p25": 200,
                        "p50": 300,
                        "p75": 400,
                        "sample_size": 2,
                    }
                ]
            ),
            2,
        ),
    ],
)
def test_judge_reports_missing_or_small_benchmark_sample(benchmark, expected_sample_size):
    judgement = judge_video_vs_benchmark(_make_frame(), benchmark, video_id="vid_4", at_day=3)

    assert judgement["benchmark_median"] is None
    assert judgement["ratio_vs_median"] is None
    assert judgement["quartile_label"] == "サンプル不足"
    assert judgement["sample_size"] == expected_sample_size


@pytest.mark.parametrize(
    ("value", "expected_label"),
    [
        (400, "上位25%"),
        (300, "中央値〜上位25%"),
        (200, "下位25%〜中央値"),
        (199, "下位25%"),
    ],
)
def test_judge_labels_exact_quartile_boundaries(value, expected_label):
    target = pd.DataFrame([{"video_id": "target", "days_since_publish": 3, "cumulative_views": value}])
    benchmark = pd.DataFrame(
        [
            {
                "days_since_publish": 3,
                "p25": 200,
                "p50": 300,
                "p75": 400,
                "sample_size": 5,
            }
        ]
    )

    judgement = judge_video_vs_benchmark(target, benchmark, video_id="target", at_day=3)

    assert judgement["quartile_label"] == expected_label


def test_judge_avoids_division_when_benchmark_median_is_zero():
    target = pd.DataFrame([{"video_id": "target", "days_since_publish": 0, "cumulative_views": 1}])
    benchmark = pd.DataFrame(
        [
            {
                "days_since_publish": 0,
                "p25": 0,
                "p50": 0,
                "p75": 2,
                "sample_size": 3,
            }
        ]
    )

    judgement = judge_video_vs_benchmark(target, benchmark, video_id="target", at_day=0)

    assert judgement["ratio_vs_median"] is None
    assert judgement["quartile_label"] == "中央値〜上位25%"
