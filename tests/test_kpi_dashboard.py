"""成長 KPI 定点ビュー（utils/kpi_dashboard.py, scripts/kpi_dashboard.py）のテスト"""

import json

import pandas as pd
import pytest

from youtube_automation.utils.kpi_dashboard import (
    MULTI_SNAPSHOT_NOTE,
    analyze_kpi_dashboard,
    build_weekly_kpi,
    merge_snapshot_series,
    render_markdown,
)


def _daily_metrics(dates, views, subs_gained=0, subs_lost=0, avp=40.0):
    return [
        {
            "date": d,
            "views": v,
            "subscribers_gained": subs_gained,
            "subscribers_lost": subs_lost,
            "avg_view_percentage": avp,
        }
        for d, v in zip(dates, views, strict=True)
    ]


def _impressions_daily(dates, impressions, ctr):
    return [{"date": d, "impressions": impressions, "ctr_percentage": ctr} for d in dates]


def _snapshot(daily_metrics=None, impressions_daily=None):
    snapshot = {"channel_analytics": {"daily_metrics": daily_metrics or []}}
    if impressions_daily is not None:
        snapshot["reporting_api"] = {"impressions_summary": {"per_day": impressions_daily}}
    return snapshot


def _week_dates(monday):
    return list(pd.date_range(monday, periods=7).strftime("%Y-%m-%d"))


WEEK1 = _week_dates("2026-01-05")  # 月曜開始
WEEK2 = _week_dates("2026-01-12")
WEEK3 = _week_dates("2026-01-19")


class TestMergeSnapshotSeries:
    def test_later_snapshot_wins_on_duplicate_dates(self):
        older = _snapshot(_daily_metrics(WEEK1, [100] * 7))
        newer = _snapshot(_daily_metrics(WEEK1[3:] + WEEK2, [999] * 11))
        merged = merge_snapshot_series([older, newer])

        by_date = {row["date"]: row["views"] for row in merged["daily_metrics"]}
        assert by_date[WEEK1[0]] == 100  # 新しい側に無い日は古い値が残る
        assert by_date[WEEK1[3]] == 999  # 重複日は後（新しいスナップショット）勝ち
        assert len(merged["daily_metrics"]) == 14

    def test_impressions_merged_across_snapshots(self):
        s1 = _snapshot([], _impressions_daily(WEEK1, 1000, 4.0))
        s2 = _snapshot([], _impressions_daily(WEEK2, 2000, 5.0))
        merged = merge_snapshot_series([s1, s2])
        assert len(merged["impressions_daily"]) == 14

    def test_missing_sections_tolerated(self):
        merged = merge_snapshot_series([{}, {"channel_analytics": {}}, {"reporting_api": {}}])
        assert merged == {"daily_metrics": [], "impressions_daily": []}


class TestBuildWeeklyKpi:
    def test_weekly_values_and_delta(self):
        """要件 1・3: 5 KPI の週次値と前週比が付く"""
        daily = _daily_metrics(WEEK1, [100] * 7, subs_gained=3, subs_lost=1, avp=40.0) + _daily_metrics(
            WEEK2, [110] * 7, subs_gained=2, subs_lost=1, avp=50.0
        )
        imps = _impressions_daily(WEEK1, 1000, 4.0) + _impressions_daily(WEEK2, 1000, 5.0)
        weekly = build_weekly_kpi(daily, imps)

        assert [w["week_starting"] for w in weekly] == ["2026-01-05", "2026-01-12"]
        w1, w2 = weekly
        assert w1["views"] == 700
        assert w1["subs_net"] == 14
        assert w1["avg_view_percentage"] == pytest.approx(40.0)
        assert w1["impressions"] == 7000
        assert w1["ctr_percentage"] == pytest.approx(4.0)
        assert w1["views_delta_pct"] is None  # 先頭週に前週は無い

        assert w2["views"] == 770
        assert w2["views_delta_pct"] == pytest.approx(10.0)
        assert w2["impressions_delta_pct"] == pytest.approx(0.0)
        assert w2["ctr_delta_pts"] == pytest.approx(1.0)
        assert w2["avg_view_percentage_delta_pts"] == pytest.approx(10.0)
        assert w2["subs_net_delta"] == -7

    def test_missing_week_is_explicit_not_interpolated(self):
        """要件 4: 欠測週は欠測として明示され、ゼロや直前値で補間されない"""
        daily = _daily_metrics(WEEK1, [100] * 7) + _daily_metrics(WEEK3, [200] * 7)
        weekly = build_weekly_kpi(daily, [])

        assert [w["week_starting"] for w in weekly] == ["2026-01-05", "2026-01-12", "2026-01-19"]
        gap = weekly[1]
        assert gap["missing"] is True
        assert gap["days_covered"] == 0
        assert gap["views"] is None
        assert gap["subs_net"] is None
        assert gap["avg_view_percentage"] is None
        # 欠測週自体と、欠測週を前週に持つ週の前週比はどちらも None
        assert gap["views_delta_pct"] is None
        assert weekly[2]["views_delta_pct"] is None
        assert weekly[2]["views"] == 1400

    def test_impressions_beyond_daily_coverage_included(self):
        """要件 2: daily に無い過去週（60 日超相当）の Imp / CTR も時系列に含まれる"""
        old_week = _week_dates("2025-10-06")  # daily カバレッジより約 3 か月前
        daily = _daily_metrics(WEEK1, [100] * 7)
        imps = _impressions_daily(old_week, 500, 3.0) + _impressions_daily(WEEK1, 1000, 4.0)
        weekly = build_weekly_kpi(daily, imps)

        by_week = {w["week_starting"]: w for w in weekly}
        old = by_week["2025-10-06"]
        assert old["impressions"] == 3500
        assert old["ctr_percentage"] == pytest.approx(3.0)
        assert old["views"] is None  # daily 欠測は欠測のまま
        assert old["missing"] is False  # impressions がある週は欠測扱いにしない
        # 間の週は両系列とも欠測
        assert by_week["2025-11-03"]["missing"] is True

    def test_empty_inputs(self):
        assert build_weekly_kpi([], []) == []

    def test_partial_week_days_covered_exposed(self):
        daily = _daily_metrics(WEEK1[:3], [100] * 3)
        weekly = build_weekly_kpi(daily, [])
        assert weekly[0]["days_covered"] == 3
        assert weekly[0]["views"] == 300


class TestAnalyzeKpiDashboard:
    def test_multiple_snapshots_no_note(self):
        snapshots = [
            _snapshot(_daily_metrics(WEEK1, [100] * 7), _impressions_daily(WEEK1, 1000, 4.0)),
            _snapshot(_daily_metrics(WEEK2, [110] * 7), _impressions_daily(WEEK2, 1000, 5.0)),
        ]
        analysis = analyze_kpi_dashboard(snapshots)
        assert analysis["schema_version"] == 1
        assert analysis["snapshot_count"] == 2
        assert analysis["notes"] == []
        assert analysis["period"]["start_date"] == WEEK1[0]
        assert analysis["period"]["end_date"] == WEEK2[-1]
        assert len(analysis["weekly_kpi"]) == 2

    @pytest.mark.parametrize("snapshots", [[], [_snapshot(_daily_metrics(WEEK1, [100] * 7))]])
    def test_single_or_no_snapshot_yields_guidance_note(self, snapshots):
        """要件 5: スナップショット 1 件以下はエラーではなく案内"""
        analysis = analyze_kpi_dashboard(snapshots)
        assert MULTI_SNAPSHOT_NOTE in analysis["notes"]


class TestRenderMarkdown:
    def test_table_and_missing_marker(self):
        snapshots = [
            _snapshot(_daily_metrics(WEEK1, [100] * 7)),
            _snapshot(_daily_metrics(WEEK3, [200] * 7)),
        ]
        md = render_markdown(analyze_kpi_dashboard(snapshots))
        assert "| 週 (月曜開始) |" in md
        assert "2026-01-12 (欠測)" in md
        assert "—" in md  # 欠測セルは補間せずダッシュ表示

    def test_note_rendered(self):
        md = render_markdown(analyze_kpi_dashboard([]))
        assert MULTI_SNAPSHOT_NOTE in md


class TestCli:
    def _write_snapshots(self, channel_root):
        data_dir = channel_root / "data"
        data_dir.mkdir(parents=True)
        for stamp, week, imp_ctr in (
            ("20260112", WEEK1, 4.0),
            ("20260119", WEEK2, 5.0),
        ):
            snapshot = _snapshot(_daily_metrics(week, [100] * 7), _impressions_daily(week, 1000, imp_ctr))
            (data_dir / f"analytics_data_{stamp}.json").write_text(json.dumps(snapshot), encoding="utf-8")

    def test_cli_outputs_json_and_saves_reports(self, tmp_path, monkeypatch, capsys):
        """要件 1: CLI 実行で週次推移テーブルが Markdown と JSON で出力される"""
        from youtube_automation.scripts import kpi_dashboard as cli

        self._write_snapshots(tmp_path)
        monkeypatch.setattr(cli, "_channel_dir", lambda: tmp_path)
        monkeypatch.setattr("sys.argv", ["yt-kpi-dashboard", "--save"])

        assert cli.main() == 0
        analysis = json.loads(capsys.readouterr().out)
        assert analysis["snapshot_count"] == 2
        assert len(analysis["weekly_kpi"]) == 2
        assert analysis["weekly_kpi"][1]["ctr_delta_pts"] == pytest.approx(1.0)

        saved = sorted((tmp_path / "reports").iterdir())
        assert [p.suffix for p in saved] == [".json", ".md"]

    def test_cli_markdown_mode(self, tmp_path, monkeypatch, capsys):
        from youtube_automation.scripts import kpi_dashboard as cli

        self._write_snapshots(tmp_path)
        monkeypatch.setattr(cli, "_channel_dir", lambda: tmp_path)
        monkeypatch.setattr("sys.argv", ["yt-kpi-dashboard", "--markdown"])

        assert cli.main() == 0
        assert "| 週 (月曜開始) |" in capsys.readouterr().out

    def test_cli_skips_broken_snapshot(self, tmp_path, monkeypatch, capsys):
        from youtube_automation.scripts import kpi_dashboard as cli

        self._write_snapshots(tmp_path)
        (tmp_path / "data" / "analytics_data_20260120.json").write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(cli, "_channel_dir", lambda: tmp_path)
        monkeypatch.setattr("sys.argv", ["yt-kpi-dashboard"])

        assert cli.main() == 0
        assert json.loads(capsys.readouterr().out)["snapshot_count"] == 2
