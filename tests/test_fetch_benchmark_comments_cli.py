"""yt-benchmark-comments CLI のユニットテスト."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from youtube_automation.scripts import fetch_benchmark_comments as mod


def test_main_accepts_yes_and_passes_to_collector(monkeypatch):
    """-y/--yes を parse して collector に渡す。"""
    calls: list[dict] = []

    class FakeCollector:
        def __init__(self, *, min_views: int, max_comments: int):
            calls.append({"min_views": min_views, "max_comments": max_comments})

        def collect(self, *, force: bool = False, yes: bool = False):
            calls.append({"force": force, "yes": yes})
            return {}

    monkeypatch.setattr(sys, "argv", ["yt-benchmark-comments", "-y", "--min-views", "5000", "--max-comments", "50"])
    monkeypatch.setattr(mod, "BenchmarkCommentCollector", FakeCollector)
    monkeypatch.setattr(mod, "print_summary", lambda _data: None)

    def fail_on_prompt(*_args, **_kwargs):
        raise AssertionError("prompted")

    monkeypatch.setattr("builtins.input", fail_on_prompt)

    mod.main()

    assert calls == [
        {"min_views": 5000, "max_comments": 50},
        {"force": False, "yes": True},
    ]


def test_collect_passes_yes_to_benchmark_freshness_check(monkeypatch, tmp_path):
    """collect(yes=True) は fresh 更新経路へ確認スキップ指定を渡す。"""
    collector = mod.BenchmarkCommentCollector.__new__(mod.BenchmarkCommentCollector)
    collector.data_dir = tmp_path
    collector.today = mod.date(2026, 6, 30)
    collector.min_views = 10000
    collector.max_comments = 100
    collector.youtube = MagicMock()

    calls: list[dict] = []

    def fake_ensure_benchmark_fresh(data_dir, *, assume_yes: bool = False):
        calls.append({"data_dir": data_dir, "assume_yes": assume_yes})

    monkeypatch.setattr(mod, "ensure_benchmark_fresh", fake_ensure_benchmark_fresh)
    monkeypatch.setattr(mod, "load_benchmark_videos", lambda *_args, **_kwargs: [])

    result = collector.collect(yes=True)

    assert result == {}
    assert calls == [{"data_dir": collector.data_dir, "assume_yes": True}]
