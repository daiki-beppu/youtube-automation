"""yt-benchmark-comments CLI のユニットテスト."""

from __future__ import annotations

import sys

import pytest

from youtube_automation.scripts import fetch_benchmark_comments as mod
from youtube_automation.utils.exceptions import ConfigError


def _run_main_with_fake_collector(monkeypatch, argv: list[str], input_func=None) -> list[dict]:
    calls: list[dict] = []

    class FakeCollector:
        def __init__(self, *, min_views: int, max_comments: int, competitor_slug: str | None):
            calls.append({"min_views": min_views, "max_comments": max_comments, "competitor_slug": competitor_slug})

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
        {"min_views": 5000, "max_comments": 50, "competitor_slug": None},
        {"force": False},
    ]


def test_main_accepts_long_yes_and_skips_prompt(monkeypatch):
    """--yes も確認を skip して collector を呼ぶ。"""

    def fail_on_prompt(*_args, **_kwargs):
        raise AssertionError("prompted")

    calls = _run_main_with_fake_collector(monkeypatch, ["yt-benchmark-comments", "--yes"], fail_on_prompt)

    assert calls == [
        {"min_views": mod.DEFAULT_MIN_VIEWS, "max_comments": mod.DEFAULT_MAX_COMMENTS, "competitor_slug": None},
        {"force": False},
    ]


@pytest.mark.parametrize("answer", ["", "Y", "y"])
def test_main_continues_when_prompt_is_accepted(monkeypatch, answer):
    """未指定で Y/空入力なら collector を呼ぶ。"""
    calls = _run_main_with_fake_collector(monkeypatch, ["yt-benchmark-comments"], lambda *_args: answer)

    assert calls == [
        {"min_views": mod.DEFAULT_MIN_VIEWS, "max_comments": mod.DEFAULT_MAX_COMMENTS, "competitor_slug": None},
        {"force": False},
    ]


def test_main_validates_channel_dir_before_prompt(monkeypatch):
    """無効環境では n 入力でも設定解決エラーを先に返す。"""
    monkeypatch.setattr(sys, "argv", ["yt-benchmark-comments"])
    monkeypatch.setattr(mod, "_channel_dir", lambda: (_ for _ in ()).throw(ConfigError("missing CHANNEL_DIR")))

    def fail_on_prompt(*_args, **_kwargs):
        raise AssertionError("prompted")

    monkeypatch.setattr("builtins.input", fail_on_prompt)

    with pytest.raises(ConfigError, match="missing CHANNEL_DIR"):
        mod.main()


def test_main_cancels_when_prompt_is_rejected(monkeypatch, capsys):
    """n 入力では collect() を呼ばず正常終了する。"""
    calls: list[dict] = []

    class FakeCollector:
        def __init__(self, *, min_views: int, max_comments: int, competitor_slug: str | None):
            calls.append({"min_views": min_views, "max_comments": max_comments, "competitor_slug": competitor_slug})

        def collect(self, *, force: bool = False):
            calls.append({"force": force})
            return {}

    monkeypatch.setattr(sys, "argv", ["yt-benchmark-comments"])
    monkeypatch.setattr(mod, "BenchmarkCommentCollector", FakeCollector)
    monkeypatch.setattr("builtins.input", lambda *_args: "n")

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    assert calls == [
        {"min_views": mod.DEFAULT_MIN_VIEWS, "max_comments": mod.DEFAULT_MAX_COMMENTS, "competitor_slug": None}
    ]
    assert "キャンセルしました" in capsys.readouterr().out


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_main_cancels_on_prompt_interrupt(monkeypatch, capsys, error):
    """EOF/KeyboardInterrupt は collect() を呼ばず正常終了する。"""
    calls: list[dict] = []

    class FakeCollector:
        def __init__(self, *, min_views: int, max_comments: int, competitor_slug: str | None):
            calls.append({"min_views": min_views, "max_comments": max_comments, "competitor_slug": competitor_slug})

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
    assert calls == [
        {"min_views": mod.DEFAULT_MIN_VIEWS, "max_comments": mod.DEFAULT_MAX_COMMENTS, "competitor_slug": None}
    ]
    assert "キャンセルしました" in capsys.readouterr().out


def test_main_force_skips_prompt(monkeypatch):
    """--force は確認を skip し、force=True で collector を呼ぶ。"""

    def fail_on_prompt(*_args, **_kwargs):
        raise AssertionError("prompted")

    calls = _run_main_with_fake_collector(monkeypatch, ["yt-benchmark-comments", "--force"], fail_on_prompt)

    assert calls == [
        {"min_views": mod.DEFAULT_MIN_VIEWS, "max_comments": mod.DEFAULT_MAX_COMMENTS, "competitor_slug": None},
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


def test_main_passes_competitor_to_collector(monkeypatch):
    calls = _run_main_with_fake_collector(
        monkeypatch,
        ["yt-benchmark-comments", "--yes", "--competitor", "benchmark-channel"],
    )

    assert calls[0]["competitor_slug"] == "benchmark-channel"


def test_removed_channel_flag_names_competitor_replacement(capsys):
    with pytest.raises(SystemExit) as exc_info:
        mod._build_parser().parse_args(["--channel", "benchmark-channel"])

    assert exc_info.value.code == 2
    assert "--channel は --competitor に変わりました" in capsys.readouterr().err


def test_collect_checks_benchmark_freshness(monkeypatch, tmp_path):
    """collect() は fresh 更新経路を確認してから対象動画を読む。"""
    collector = mod.BenchmarkCommentCollector.__new__(mod.BenchmarkCommentCollector)
    collector.data_dir = tmp_path
    collector.today = mod.date(2026, 6, 30)
    collector.min_views = 10000
    collector.max_comments = 100
    collector.competitor_slug = None
    collector.youtube = None

    calls: list[tuple] = []
    target = {
        "video_id": "video-1",
        "title": "Benchmark video",
        "views": 12000,
        "channel_name": "Benchmark Channel",
        "channel_slug": "benchmark-channel",
        "published_at": "2026-06-01T00:00:00Z",
        "thumbnail_url": "https://example.com/thumb.jpg",
    }
    comment = {
        "author": "viewer",
        "text": "great",
        "likes": 3,
        "published_at": "2026-06-02T00:00:00Z",
        "comment_id": "comment-1",
    }

    def fake_ensure_benchmark_fresh(data_dir):
        calls.append(("fresh", data_dir))

    def fake_load_benchmark_videos(data_dir, *, min_views: int, competitor_slug: str | None):
        calls.append(("load", data_dir, min_views, competitor_slug))
        return [target]

    def fake_get_youtube():
        calls.append(("youtube-full-scope",))
        return object()

    def fake_fetch_comments(video_id: str):
        calls.append(("fetch", video_id))
        return [comment]

    monkeypatch.setattr(mod, "ensure_benchmark_fresh", fake_ensure_benchmark_fresh)
    monkeypatch.setattr(mod, "load_benchmark_videos", fake_load_benchmark_videos)
    monkeypatch.setattr(mod, "get_youtube", fake_get_youtube)
    monkeypatch.setattr(collector, "_fetch_comments", fake_fetch_comments)

    result = collector.collect()

    assert calls == [
        ("fresh", collector.data_dir),
        ("load", collector.data_dir, 10000, None),
        ("youtube-full-scope",),
        ("fetch", "video-1"),
    ]
    assert result["summary"] == {
        "total_videos": 1,
        "total_comments": 1,
        "by_channel": {
            "benchmark-channel": {
                "name": "Benchmark Channel",
                "video_count": 1,
                "comment_count": 1,
            }
        },
    }
    assert result["videos"] == [{**target, "comments": [comment], "comment_count": 1}]
    assert (tmp_path / "comments_20260630.json").exists()
