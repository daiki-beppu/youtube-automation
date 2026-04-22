import pandas as pd

from youtube_automation.utils.launch_curve_plotter import plot_launch_curve


def _make_frame():
    records = []
    for vid in ["vid_0", "vid_1", "vid_2", "vid_3", "vid_4"]:
        for day in range(31):
            records.append(
                {
                    "video_id": vid,
                    "days_since_publish": day,
                    "cumulative_views": (int(vid.split("_")[1]) + 1) * day * 10,
                    "daily_views": (int(vid.split("_")[1]) + 1) * 10,
                    "daily_impressions": 500,
                    "ctr": 2.0,
                }
            )
    return pd.DataFrame(records)


def test_plot_launch_curve_writes_png(tmp_path):
    df = _make_frame()
    out = tmp_path / "curve.png"
    plot_launch_curve(
        df=df,
        target_video_id="vid_4",
        output_path=out,
        window=30,
    )
    assert out.exists()
    assert out.stat().st_size > 1000
