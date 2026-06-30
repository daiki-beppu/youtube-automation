"""yt-benchmark-comments CLI のユニットテスト."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from youtube_automation.scripts import fetch_benchmark_comments as mod


def _run_main_with_fake_collector(monkeypatch, argv: list[str], input_func=None) -> list[dict]:
    calls: list[dict] = []

    class FakeCollector:
        def __init__(self, *, min_views: int, max_comments: int):
            calls.append({"min_views": min_views, "max_comments": max_comments})

        def collect(self, *, force: bool = False):
            calls.append({"force": force})
            return {}

    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(mod, "BenchmarkCommentCollector", FakeCollector)
    monkeypatch.setattr(mod, "print_summary", lambda _data: None)
    if input_func is not None:
        monkeypatch.setattr("builtins.input", input_func)

    mod.main()
    return calls


def test_main_accepts_short_yes_and_skips_prompt(monkeypatch):
    """-y は確認を skip して collector を呼ぶ。"""

    def fail_on_prompt(*_args, **_kwargs):
        raise AssertionError("prompted")

    calls = _run_main_with_fake_collector(
        monkeypatch,
        ["yt-benchmark-comments", "-y", "--min-views", "5000", "--max-comments", "50"],
        fail_on_prompt,
    )

    assert calls == [
        {"min_views": 5000, "max_comments": 50},
        {"force": False},
    ]


def test_main_accepts_long_yes_and_skips_prompt(monkeypatch):
    """--yes も確認を skip して collector を呼ぶ。"""

    def fail_on_prompt(*_args, **_kwargs):
        raise AssertionError("prompted")

    calls = _run_main_with_fake_collector(monkeypatch, ["yt-benchmark-comments", "--yes"], fail_on_prompt)

    assert calls == [
        {"min_views": mod.DEFAULT_MIN_VIEWS, "max_comments": mod.DEFAULT_MAX_COMMENTS},
        {"force": False},
    ]


@pytest.mark.parametrize("answer", ["", "Y", "y"])
def test_main_continues_when_prompt_is_accepted(monkeypatch, answer):
    """未指定で Y/空入力なら collector を呼ぶ。"""
    calls = _run_main_with_fake_collector(monkeypatch, ["yt-benchmark-comments"], lambda *_args: answer)

    assert calls == [
        {"min_views": mod.DEFAULT_MIN_VIEWS, "max_comments": mod.DEFAULT_MAX_COMMENTS},
        {"force": False},
    ]


def test_main_cancels_when_prompt_is_rejected(monkeypatch, capsys):
    """n 入力では collector を呼ばず正常終了する。"""
    calls: list[dict] = []

    class FakeCollector:
        def __init__(self, *, min_views: int, max_comments: int):
            calls.append({"min_views": min_views, "max_comments": max_comments})

        def collect(self, *, force: bool = False):
            calls.append({"force": force})
            return {}

    monkeypatch.setattr(sys, "argv", ["yt-benchmark-comments"])
    monkeypatch.setattr(mod, "BenchmarkCommentCollector", FakeCollector)
    monkeypatch.setattr("builtins.input", lambda *_args: "n")

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    assert calls == []
    assert "キャンセルしました" in capsys.readouterr().out


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_main_cancels_on_prompt_interrupt(monkeypatch, capsys, error):
    """EOF/KeyboardInterrupt は collector を呼ばず正常終了する。"""
    calls: list[dict] = []

    class FakeCollector:
        def __init__(self, *, min_views: int, max_comments: int):
            calls.append({"min_views": min_views, "max_comments": max_comments})

        def collect(self, *, force: bool = False):
            calls.append({"force": force})
            return {}

    def raise_error(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(sys, "argv", ["yt-benchmark-comments"])
    monkeypatch.setattr(mod, "BenchmarkCommentCollector", FakeCollector)
    monkeypatch.setattr("builtins.input", raise_error)

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    assert calls == []
    assert "キャンセルしました" in capsys.readouterr().out


def test_main_force_skips_prompt(monkeypatch):
    """--force は確認を skip し、force=True で collector を呼ぶ。"""

    def fail_on_prompt(*_args, **_kwargs):
        raise AssertionError("prompted")

    calls = _run_main_with_fake_collector(monkeypatch, ["yt-benchmark-comments", "--force"], fail_on_prompt)

    assert calls == [
        {"min_views": mod.DEFAULT_MIN_VIEWS, "max_comments": mod.DEFAULT_MAX_COMMENTS},
        {"force": True},
    ]


def test_help_includes_yes_option(monkeypatch, capsys):
    """--help に -y/--yes の説明が出る。"""
    monkeypatch.setattr(sys, "argv", ["yt-benchmark-comments", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "-y, --yes" in out
    assert "確認プロンプトをスキップ" in out


def test_collect_checks_benchmark_freshness(monkeypatch, tmp_path):
    """collect() は fresh 更新経路を確認してから対象動画を読む。"""
    collector = mod.BenchmarkCommentCollector.__new__(mod.BenchmarkCommentCollector)
    collector.data_dir = tmp_path
    collector.today = mod.date(2026, 6, 30)
    collector.min_views = 10000
    collector.max_comments = 100
    collector.youtube = MagicMock()

    calls: list[dict] = []

    def fake_ensure_benchmark_fresh(data_dir):
        calls.append({"data_dir": data_dir})

    monkeypatch.setattr(mod, "ensure_benchmark_fresh", fake_ensure_benchmark_fresh)
    monkeypatch.setattr(mod, "load_benchmark_videos", lambda *_args, **_kwargs: [])

    result = collector.collect()

    assert result == {}
    assert calls == [{"data_dir": collector.data_dir}]
