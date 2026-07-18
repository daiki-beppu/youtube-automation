"""
StrategicAnalyticsMixin の並列化ヘルパーのユニットテスト

テスト対象: utils/strategic_analytics.py
`_fetch_videos_analytics_parallel` 経由で `get_all_video_analytics` /
`get_recent_video_analytics` が
  - 動画情報と Analytics データを正しく merge する
  - 完了順に関わらず最終的に views 降順でソートされる
  - worker 内で予期せぬ例外が起きた動画はスキップして残りを返す
ことを検証する。
"""

from __future__ import annotations

from typing import Dict, List
from unittest.mock import MagicMock

import pytest

from youtube_automation.utils.strategic_analytics import (
    _MAX_WORKERS,
    StrategicAnalyticsMixin,
)

# get_video_analytics_by_id が返す Analytics 結果（views を視聴回数として差別化）
_ANALYTICS_BY_ID: Dict[str, Dict] = {
    "VID_A": {"video_id": "VID_A", "views": 100, "likes": 10, "subscribers_gained": 1},
    "VID_B": {"video_id": "VID_B", "views": 300, "likes": 30, "subscribers_gained": 3},
    "VID_C": {"video_id": "VID_C", "views": 200, "likes": 20, "subscribers_gained": 2},
}


def _video_meta(video_id: str, title: str) -> Dict:
    return {"video_id": video_id, "title": title, "published_at": "2026-01-01T00:00:00Z"}


class _StubCollector(StrategicAnalyticsMixin):
    """並列化ヘルパー検証用のスタブコレクター"""

    def __init__(self) -> None:
        self.analytics_service = MagicMock()
        self.youtube_service = MagicMock()
        self.channel_id = "UC_TEST"
        # 仕様: get_video_analytics_by_id を辞書ルックアップで模す
        self._raise_for: set[str] = set()
        self._call_log: List[str] = []
        # 親メソッドが呼ぶ全動画リスト / 直近投稿リスト
        self._all_videos: List[Dict] = []
        self._recent_videos: List[Dict] = []

    # AnalyticsBase が期待するインターフェース
    def initialize(self) -> None:  # pragma: no cover - 並列化テストでは未使用
        pass

    def _get_video_details(self, video_ids: List[str]) -> Dict:  # pragma: no cover
        return {}

    def get_all_channel_videos(self) -> List[Dict]:
        return self._all_videos

    def get_recent_videos(self, days: int = 30) -> List[Dict]:
        return self._recent_videos

    def get_video_analytics(self, start_date: str, end_date: str) -> List[Dict]:  # pragma: no cover
        return []

    def get_video_analytics_by_id(self, video_id: str, start_date: str, end_date: str) -> Dict:
        self._call_log.append(video_id)
        if video_id in self._raise_for:
            raise RuntimeError(f"simulated worker failure for {video_id}")
        return _ANALYTICS_BY_ID[video_id]


@pytest.fixture
def collector() -> _StubCollector:
    return _StubCollector()


class TestMaxWorkersConstant:
    def test_max_workers_is_eight(self) -> None:
        """指示書通り並列度は 8 固定"""
        assert _MAX_WORKERS == 8


class TestFetchVideosAnalyticsParallel:
    def test_merges_video_meta_with_analytics(self, collector: _StubCollector) -> None:
        """動画 meta と Analytics 結果が dict マージされる"""
        videos = [_video_meta("VID_A", "Title A")]

        result = collector._fetch_videos_analytics_parallel(videos, "2026-01-01", "2026-04-01", "test.section")

        assert len(result) == 1
        assert result[0]["video_id"] == "VID_A"
        assert result[0]["title"] == "Title A"
        assert result[0]["views"] == 100
        assert result[0]["likes"] == 10
        assert result[0]["subscriber_conversion_rate"] == 1.0

    def test_all_videos_returned_regardless_of_completion_order(self, collector: _StubCollector) -> None:
        """worker の完了順に関わらず全動画が結果に含まれる"""
        videos = [
            _video_meta("VID_A", "A"),
            _video_meta("VID_B", "B"),
            _video_meta("VID_C", "C"),
        ]

        result = collector._fetch_videos_analytics_parallel(videos, "2026-01-01", "2026-04-01", "test.section")

        assert {r["video_id"] for r in result} == {"VID_A", "VID_B", "VID_C"}

    def test_worker_exception_is_logged_and_skipped(
        self, collector: _StubCollector, caplog: pytest.LogCaptureFixture
    ) -> None:
        """worker 内で予期せぬ例外が起きた動画はスキップして残りを返す"""
        collector._raise_for = {"VID_B"}
        videos = [
            _video_meta("VID_A", "A"),
            _video_meta("VID_B", "B"),
            _video_meta("VID_C", "C"),
        ]

        with caplog.at_level("ERROR"):
            result = collector._fetch_videos_analytics_parallel(videos, "2026-01-01", "2026-04-01", "test.section")

        returned_ids = {r["video_id"] for r in result}
        assert returned_ids == {"VID_A", "VID_C"}
        assert any("VID_B" in rec.message for rec in caplog.records)

    def test_empty_video_list_returns_empty(self, collector: _StubCollector) -> None:
        """空リスト入力で空リスト返却・get_video_analytics_by_id 呼び出しなし"""
        result = collector._fetch_videos_analytics_parallel([], "2026-01-01", "2026-04-01", "test.section")

        assert result == []
        assert collector._call_log == []


class TestGetAllVideoAnalyticsParallel:
    def test_sort_by_views_desc(self, collector: _StubCollector) -> None:
        """`get_all_video_analytics` は views 降順でソートして返す"""
        collector._all_videos = [
            _video_meta("VID_A", "A"),  # views=100
            _video_meta("VID_B", "B"),  # views=300
            _video_meta("VID_C", "C"),  # views=200
        ]

        result = collector.get_all_video_analytics("2026-01-01", "2026-04-01")

        assert [r["video_id"] for r in result] == ["VID_B", "VID_C", "VID_A"]
        assert [r["subscriber_conversion_rate"] for r in result] == [1.0, 1.0, 1.0]

    def test_empty_all_videos_returns_empty(self, collector: _StubCollector) -> None:
        """`get_all_channel_videos` が空なら早期リターン"""
        collector._all_videos = []

        result = collector.get_all_video_analytics("2026-01-01", "2026-04-01")

        assert result == []
        assert collector._call_log == []


class TestGetRecentVideoAnalyticsParallel:
    def test_sort_by_views_desc(self, collector: _StubCollector) -> None:
        """`get_recent_video_analytics` は views 降順でソートして返す"""
        collector._recent_videos = [
            _video_meta("VID_A", "A"),  # views=100
            _video_meta("VID_B", "B"),  # views=300
        ]

        result = collector.get_recent_video_analytics("2026-01-01", "2026-04-01", days=30)

        assert [r["video_id"] for r in result] == ["VID_B", "VID_A"]
        assert [r["subscriber_conversion_rate"] for r in result] == [1.0, 1.0]

    def test_empty_recent_videos_returns_empty(self, collector: _StubCollector) -> None:
        """`get_recent_videos` が空なら早期リターン"""
        collector._recent_videos = []

        result = collector.get_recent_video_analytics("2026-01-01", "2026-04-01", days=30)

        assert result == []
        assert collector._call_log == []


class TestSubscriberConversionRanking:
    def test_combined_analytics_adds_conversion_rate(self, collector: _StubCollector) -> None:
        """統合取得の公開メソッドが上位動画へ転換率を付与する。"""
        collector._all_videos = [_video_meta("VID_A", "A")]
        collector.analytics_service.reports().query().execute.return_value = {
            "rows": [["VID_A", 200, 1000, 120, 10, 0, 1, 2, 6]]
        }

        result = collector.get_combined_analytics("2026-01-01", "2026-04-01")

        assert result["top_videos"][0]["subscriber_conversion_rate"] == 3.0

    def test_top_video_analytics_adds_conversion_rate(self, collector: _StubCollector) -> None:
        """上位動画取得の公開メソッドが転換率を付与する。"""
        collector.analytics_service.reports().query().execute.return_value = {
            "rows": [["VID_A", 200, 1000, 120, 10, 0, 1, 2, 6]]
        }

        result = collector.get_top_video_analytics("2026-01-01", "2026-04-01")

        assert result[0]["subscriber_conversion_rate"] == 3.0

    @pytest.mark.parametrize(
        ("mode", "method_name", "result_key"),
        [
            ("efficient", "get_combined_analytics", "top_videos"),
            ("comprehensive", "get_all_video_analytics", "all_videos"),
            ("top_only", "get_top_video_analytics", "top_videos"),
            ("recent_only", "get_recent_video_analytics", "recent_videos"),
        ],
    )
    def test_all_modes_add_conversion_rate_and_ranking(
        self, collector: _StubCollector, monkeypatch: pytest.MonkeyPatch, mode: str, method_name: str, result_key: str
    ) -> None:
        """各取得モードが転換率を動画へ付与し、率降順ランキングを返す"""
        videos = [
            {"video_id": "VID_HIGH", "title": "High", "duration": "PT2M", "views": 50, "subscribers_gained": 5},
            {"video_id": "VID_ZERO", "title": "Zero", "duration": "PT3M", "views": 0, "subscribers_gained": 10},
            {"video_id": "VID_LOW", "title": "Low", "duration": "PT4M", "views": 100, "subscribers_gained": 1},
        ]

        if mode == "efficient":
            monkeypatch.setattr(
                collector,
                method_name,
                lambda start_date, end_date, top_count, recent_days: {
                    "top_videos": videos,
                    "recent_videos": [],
                },
            )
        elif mode == "top_only":
            monkeypatch.setattr(
                collector,
                method_name,
                lambda start_date, end_date, top_count: videos,
            )
        elif mode == "recent_only":
            monkeypatch.setattr(
                collector,
                method_name,
                lambda start_date, end_date, days: videos,
            )
        else:
            monkeypatch.setattr(collector, method_name, lambda start_date, end_date: videos)

        result = collector.get_strategic_video_analytics("2026-01-01", "2026-04-01", mode=mode)

        assert [video["subscriber_conversion_rate"] for video in result[result_key]] == [10.0, 0, 1.0]
        assert [video["video_id"] for video in result["subscriber_conversion_ranking"]] == [
            "VID_HIGH",
            "VID_LOW",
            "VID_ZERO",
        ]
        assert result["subscriber_conversion_ranking"][0] == {
            "video_id": "VID_HIGH",
            "title": "High",
            "duration": "PT2M",
            "views": 50,
            "subscribers_gained": 5,
            "subscriber_conversion_rate": 10.0,
        }
