import pandas as pd

from youtube_automation.utils.theme_performance import (
    analyze_theme_performance,
    classify_videos_by_theme,
)


def _make_launch_frame():
    """2 テーマ × 各2動画 × 日0..6"""
    records = []
    # theme adventure: vid_a1 (高初速), vid_a2 (低初速)
    for vid, rate in [("vid_a1", 100), ("vid_a2", 30)]:
        for day in range(7):
            records.append(
                {
                    "video_id": vid,
                    "days_since_publish": day,
                    "cumulative_views": rate * (day + 1),
                    "daily_views": rate,
                    "daily_impressions": 0,
                    "ctr": 0.0,
                }
            )
    # theme battle: vid_b1 (中速), vid_b2 (中速)
    for vid, rate in [("vid_b1", 50), ("vid_b2", 60)]:
        for day in range(7):
            records.append(
                {
                    "video_id": vid,
                    "days_since_publish": day,
                    "cumulative_views": rate * (day + 1),
                    "daily_views": rate,
                    "daily_impressions": 0,
                    "ctr": 0.0,
                }
            )
    return pd.DataFrame(records)


def test_classify_videos_by_theme_matches_keywords():
    meta = {
        "vid_a1": {"title": "Adventure theme song", "published_at": "2026-04-01"},
        "vid_a2": {"title": "Epic adventure journey", "published_at": "2026-04-01"},
        "vid_b1": {"title": "Battle Royale", "published_at": "2026-04-01"},
        "vid_b2": {"title": "Boss battle music", "published_at": "2026-04-01"},
    }
    theme_keywords = {
        "adventure": ["adventure", "journey"],
        "battle": ["battle", "fight"],
    }
    result = classify_videos_by_theme(meta, theme_keywords)
    assert set(result["adventure"]) == {"vid_a1", "vid_a2"}
    assert set(result["battle"]) == {"vid_b1", "vid_b2"}


def test_classify_videos_unmatched_go_to_other():
    meta = {"vid_x": {"title": "Random title", "published_at": "2026-04-01"}}
    result = classify_videos_by_theme(meta, {"adventure": ["adventure"]})
    assert result.get("other", []) == ["vid_x"]


def test_analyze_theme_performance_computes_mean_curves():
    df = _make_launch_frame()
    theme_map = {"adventure": ["vid_a1", "vid_a2"], "battle": ["vid_b1", "vid_b2"]}
    result = analyze_theme_performance(df, theme_map)
    themes = {t["theme"]: t for t in result["themes"]}

    # adventure day 0 平均: (100 + 30) / 2 = 65
    adv_day0 = next(p for p in themes["adventure"]["mean_curve"] if p["day"] == 0)
    assert adv_day0["mean_cumulative_views"] == 65
    assert themes["adventure"]["video_count"] == 2

    # battle day 3 平均: (50*4 + 60*4) / 2 = 220
    bat_day3 = next(p for p in themes["battle"]["mean_curve"] if p["day"] == 3)
    assert bat_day3["mean_cumulative_views"] == 220


def test_analyze_theme_performance_identifies_best_themes():
    df = _make_launch_frame()
    theme_map = {"adventure": ["vid_a1", "vid_a2"], "battle": ["vid_b1", "vid_b2"]}
    result = analyze_theme_performance(df, theme_map, peak_days=(3, 6))

    # day3 平均: adventure=(400+120)/2=260, battle=(200+240)/2=220 → adventure
    assert result["best_theme_by_initial_velocity"] == "adventure"
    # day6 平均: adventure=(700+210)/2=455, battle=(350+420)/2=385 → adventure
    assert result["best_theme_by_long_tail"] == "adventure"


def test_analyze_theme_performance_excludes_empty_themes():
    df = _make_launch_frame()
    theme_map = {
        "adventure": ["vid_a1", "vid_a2"],
        "empty_theme": [],
    }
    result = analyze_theme_performance(df, theme_map)
    themes = {t["theme"] for t in result["themes"]}
    assert "empty_theme" not in themes
