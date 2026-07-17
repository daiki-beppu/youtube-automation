"""utils/traffic_trend.py と yt-traffic-trend CLI のユニットテスト"""

import json

import pytest

from youtube_automation.utils.traffic_trend import analyze_traffic_trend


def _snapshot(end_date, sources, devices=None, search_terms=None, collected_at=None):
    total_views = sum(s["views"] for s in sources.values())
    traffic = {"sources": sources, "total_views": total_views}
    if search_terms is not None:
        traffic["search_terms"] = search_terms
    snapshot = {
        "collection_period": {
            "start_date": "2026-06-01",
            "end_date": end_date,
            "collected_at": collected_at or f"{end_date}T12:00:00",
        },
        "traffic_sources": traffic,
    }
    if devices is not None:
        snapshot["audience"] = {
            "by_device": {
                "devices": devices,
                "total_views": sum(d["views"] for d in devices.values()),
            }
        }
    return snapshot


class TestAnalyzeTrafficTrend:
    def test_latest_shares_and_summary(self):
        snapshot = _snapshot(
            "2026-07-01",
            sources={
                "YT_SEARCH": {"views": 300, "view_share_percent": 50.0},
                "BROWSE": {"views": 200, "view_share_percent": 33.3},
                "EXT_URL": {"views": 100, "view_share_percent": 16.7},
            },
            devices={
                "MOBILE": {"views": 400},
                "DESKTOP": {"views": 200},
            },
        )

        result = analyze_traffic_trend([snapshot])

        assert result["snapshots_analyzed"] == 1
        assert result["summary"]["top_source"] == "YT_SEARCH"
        assert result["summary"]["top_source_share_percent"] == 50.0
        assert result["summary"]["top_device"] == "MOBILE"
        assert result["summary"]["top_device_share_percent"] == pytest.approx(66.7)
        assert result["latest"]["total_views"] == 600
        assert result["share_trend"][0]["source_share"]["BROWSE"] == pytest.approx(33.3)

    def test_share_trend_and_delta_across_snapshots(self):
        older = _snapshot(
            "2026-06-15",
            sources={"YT_SEARCH": {"views": 40}, "BROWSE": {"views": 60}},
        )
        newer = _snapshot(
            "2026-07-01",
            sources={"YT_SEARCH": {"views": 60}, "BROWSE": {"views": 40}},
        )

        result = analyze_traffic_trend([older, newer])

        assert result["snapshots_analyzed"] == 2
        assert [t["end_date"] for t in result["share_trend"]] == ["2026-06-15", "2026-07-01"]
        assert result["share_trend"][0]["source_share"]["YT_SEARCH"] == 40.0
        assert result["share_trend"][1]["source_share"]["YT_SEARCH"] == 60.0
        assert result["summary"]["share_delta"]["YT_SEARCH"] == 20.0
        assert result["summary"]["share_delta"]["BROWSE"] == -20.0

    def test_search_terms_sorted_and_truncated(self):
        terms = [{"detail": f"term {i}", "views": i, "watch_time_minutes": i} for i in range(1, 13)]
        snapshot = _snapshot(
            "2026-07-01",
            sources={"YT_SEARCH": {"views": 100}},
            search_terms=terms,
        )

        result = analyze_traffic_trend([snapshot], top_search=3)

        details = [t["detail"] for t in result["latest"]["search_terms"]]
        assert details == ["term 12", "term 11", "term 10"]
        assert result["summary"]["top_search_terms"] == details

    def test_snapshots_without_traffic_sources_are_skipped(self):
        basic_only = {"collection_period": {"end_date": "2026-06-01"}}
        with_traffic = _snapshot("2026-07-01", sources={"BROWSE": {"views": 10}})

        result = analyze_traffic_trend([basic_only, with_traffic])

        assert result["snapshots_analyzed"] == 1
        assert result["summary"]["share_delta"] == {}

    def test_empty_input(self):
        result = analyze_traffic_trend([])

        assert result["snapshots_analyzed"] == 0
        assert result["latest"] is None
        assert result["share_trend"] == []
        assert result["summary"]["top_source"] is None


class TestTrafficTrendCli:
    @pytest.fixture
    def channel_with_data(self, tmp_path, monkeypatch):
        from youtube_automation.scripts import traffic_trend

        monkeypatch.setattr(traffic_trend, "_channel_dir", lambda: tmp_path)
        (tmp_path / "data").mkdir()
        return tmp_path

    def _write_snapshot(self, channel, name, snapshot):
        (channel / "data" / name).write_text(json.dumps(snapshot), encoding="utf-8")

    def test_main_outputs_json(self, channel_with_data, monkeypatch, capsys):
        from youtube_automation.scripts import traffic_trend

        self._write_snapshot(
            channel_with_data,
            "analytics_data_20260701_120000.json",
            _snapshot(
                "2026-07-01",
                sources={"YT_SEARCH": {"views": 60}, "BROWSE": {"views": 40}},
                devices={"MOBILE": {"views": 70}, "TV": {"views": 30}},
                search_terms=[{"detail": "lofi music", "views": 30, "watch_time_minutes": 90}],
            ),
        )
        monkeypatch.setattr("sys.argv", ["yt-traffic-trend"])

        assert traffic_trend.main() == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["top_source"] == "YT_SEARCH"
        assert payload["latest"]["search_terms"][0]["detail"] == "lofi music"

    def test_main_without_data_returns_2(self, channel_with_data, monkeypatch, capsys):
        from youtube_automation.scripts import traffic_trend

        monkeypatch.setattr("sys.argv", ["yt-traffic-trend"])

        assert traffic_trend.main() == 2

    def test_main_without_traffic_sources_returns_2(self, channel_with_data, monkeypatch):
        from youtube_automation.scripts import traffic_trend

        self._write_snapshot(
            channel_with_data,
            "analytics_data_20260701_120000.json",
            {"collection_period": {"end_date": "2026-07-01"}, "collection_depth": "basic"},
        )
        monkeypatch.setattr("sys.argv", ["yt-traffic-trend"])

        assert traffic_trend.main() == 2

    def test_main_text_output(self, channel_with_data, monkeypatch, capsys):
        from youtube_automation.scripts import traffic_trend

        self._write_snapshot(
            channel_with_data,
            "analytics_data_20260701_120000.json",
            _snapshot("2026-07-01", sources={"BROWSE": {"views": 40, "view_share_percent": 100.0}}),
        )
        monkeypatch.setattr("sys.argv", ["yt-traffic-trend", "--text"])

        assert traffic_trend.main() == 0
        out = capsys.readouterr().out
        assert "流入源・デバイス分析" in out
        assert "BROWSE" in out
