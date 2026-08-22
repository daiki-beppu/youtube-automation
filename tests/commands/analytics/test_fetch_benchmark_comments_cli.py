"""yt-benchmark-comments CLI のユニットテスト."""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_automation.commands.analytics import fetch_benchmark_comments as mod
from youtube_automation.core.errors import ConfigError, YouTubeAPIError


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

    assert mod.main() == 1


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

    assert mod.main() == 0
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

    assert mod.main() == 0
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

    def fake_ensure_benchmark_fresh(data_dir, **factories):
        calls.append(("fresh", data_dir, factories))

    def fake_load_benchmark_videos(data_dir, *, min_views: int, competitor_slug: str | None):
        calls.append(("load", data_dir, min_views, competitor_slug))
        return [target]

    def fake_youtube_service():
        calls.append(("youtube-full-scope",))
        return object()

    def fake_fetch_comments(video_id: str):
        calls.append(("fetch", video_id))
        return [comment]

    monkeypatch.setattr(mod, "ensure_benchmark_fresh", fake_ensure_benchmark_fresh)
    monkeypatch.setattr(mod, "load_benchmark_videos", fake_load_benchmark_videos)

    class FakeClients:
        @property
        def youtube(self):
            return fake_youtube_service()

    collector.youtube_clients = FakeClients()
    monkeypatch.setattr(collector, "_fetch_comments", fake_fetch_comments)

    result = collector.collect()

    assert calls == [
        (
            "fresh",
            collector.data_dir,
            {
                "collector_factory": mod.BenchmarkCollector,
                "analyzer_factory": mod.BenchmarkThumbnailAnalyzer,
                "reporter_factory": mod.BenchmarkReportGenerator,
            },
        ),
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


def _collector_for_date(tmp_path):
    collector = mod.BenchmarkCommentCollector.__new__(mod.BenchmarkCommentCollector)
    collector.data_dir = tmp_path
    collector.today = mod.date(2026, 6, 30)
    collector.min_views = 10000
    collector.max_comments = 100
    collector.competitor_slug = None
    collector.youtube = None
    return collector


def test_collect_reuses_same_day_cache_without_refresh_or_api(monkeypatch, tmp_path):
    collector = _collector_for_date(tmp_path)
    cached = {"collected_at": "cached", "videos": [], "summary": {"total_videos": 0}}
    output = tmp_path / "comments_20260630.json"
    output.write_text(json.dumps(cached), encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "ensure_benchmark_fresh",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("refreshed")),
    )
    monkeypatch.setattr(
        mod,
        "load_benchmark_videos",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("loaded targets")),
    )

    assert collector.collect() == cached


def test_collect_empty_targets_returns_without_authentication_or_save(monkeypatch, tmp_path):
    collector = _collector_for_date(tmp_path)
    calls = []
    monkeypatch.setattr(mod, "ensure_benchmark_fresh", lambda *_args, **_kwargs: calls.append("fresh"))
    monkeypatch.setattr(mod, "load_benchmark_videos", lambda *_args, **_kwargs: [])

    class Clients:
        @property
        def youtube(self):
            raise AssertionError("authenticated")

    collector.youtube_clients = Clients()

    assert collector.collect() == {}
    assert calls == ["fresh"]
    assert collector.youtube is None
    assert not (tmp_path / "comments_20260630.json").exists()


def test_collect_skips_comments_disabled_video_and_records_metadata(monkeypatch, tmp_path):
    collector = _collector_for_date(tmp_path)
    targets = [
        {
            "video_id": video_id,
            "title": title,
            "views": 12000,
            "channel_name": "Benchmark Channel",
            "channel_slug": "benchmark-channel",
        }
        for video_id, title in (("disabled", "Comments off"), ("enabled", "Comments on"))
    ]
    monkeypatch.setattr(mod, "ensure_benchmark_fresh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "load_benchmark_videos", lambda *_args, **_kwargs: targets)
    collector.youtube_clients = SimpleNamespace(youtube=object())

    def fetch(video_id: str):
        if video_id == "disabled":
            raise YouTubeAPIError("comments disabled", status_code=403, reason="commentsDisabled")
        return [_comment_item("comment-1")]

    monkeypatch.setattr(collector, "_fetch_comments", fetch)

    result = collector.collect()

    assert [video["video_id"] for video in result["videos"]] == ["enabled"]
    assert result["skipped_videos"] == [{"video_id": "disabled", "title": "Comments off", "reason": "commentsDisabled"}]
    assert result["summary"]["total_videos"] == 1


def test_collect_fails_loud_for_other_403(monkeypatch, tmp_path):
    collector = _collector_for_date(tmp_path)
    target = {
        "video_id": "forbidden",
        "title": "Forbidden",
        "views": 12000,
        "channel_name": "Benchmark Channel",
        "channel_slug": "benchmark-channel",
    }
    monkeypatch.setattr(mod, "ensure_benchmark_fresh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "load_benchmark_videos", lambda *_args, **_kwargs: [target])
    collector.youtube_clients = SimpleNamespace(youtube=object())
    monkeypatch.setattr(
        collector,
        "_fetch_comments",
        lambda _video_id: (_ for _ in ()).throw(
            YouTubeAPIError("quota exceeded", status_code=403, reason="quotaExceeded")
        ),
    )

    with pytest.raises(YouTubeAPIError, match="quota exceeded"):
        collector.collect()


def _comment_item(comment_id: str) -> dict:
    return {
        "snippet": {
            "topLevelComment": {
                "id": comment_id,
                "snippet": {
                    "authorDisplayName": f"author-{comment_id}",
                    "textOriginal": f"text-{comment_id}",
                    "likeCount": 1,
                    "publishedAt": "2026-07-31T00:00:00Z",
                },
            }
        }
    }


def test_fetch_comments_paginates_to_requested_limit_and_passes_page_token(tmp_path):
    collector = _collector_for_date(tmp_path)
    collector.max_comments = 3
    youtube = MagicMock()
    first = MagicMock()
    first.execute.return_value = {
        "items": [_comment_item("c1"), _comment_item("c2")],
        "nextPageToken": "next-token",
    }
    second = MagicMock()
    second.execute.return_value = {"items": [_comment_item("c3"), _comment_item("c4")]}
    youtube.commentThreads.return_value.list.side_effect = [first, second]
    collector.youtube = youtube

    comments = collector._fetch_comments("video")

    assert [comment["comment_id"] for comment in comments] == ["c1", "c2", "c3"]
    assert youtube.commentThreads.return_value.list.call_args_list[0].kwargs == {
        "videoId": "video",
        "part": "snippet",
        "order": "relevance",
        "maxResults": 3,
    }
    assert youtube.commentThreads.return_value.list.call_args_list[1].kwargs == {
        "videoId": "video",
        "part": "snippet",
        "order": "relevance",
        "maxResults": 1,
        "pageToken": "next-token",
    }


def test_fetch_comments_partial_api_failure_is_not_reported_as_empty_success(tmp_path):
    collector = _collector_for_date(tmp_path)
    collector.max_comments = 3
    youtube = MagicMock()
    first = MagicMock()
    first.execute.return_value = {
        "items": [_comment_item("c1")],
        "nextPageToken": "next-token",
    }
    second = MagicMock()
    second.execute.side_effect = RuntimeError("quota exhausted")
    youtube.commentThreads.return_value.list.side_effect = [first, second]
    collector.youtube = youtube

    with pytest.raises(YouTubeAPIError, match="1件取得後"):
        collector._fetch_comments("video")


def test_atomic_save_failure_preserves_existing_artifact_and_cleans_temp(monkeypatch, tmp_path):
    output = tmp_path / "comments.json"
    output.write_text('{"existing": true}\n', encoding="utf-8")
    before = output.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        mod._write_json_atomic(output, {"replacement": True})

    assert output.read_bytes() == before
    assert not list(tmp_path.glob(".comments.json.*.tmp"))


@pytest.mark.parametrize(
    "error",
    [YouTubeAPIError("api unavailable"), OSError("disk full")],
)
def test_main_reports_collection_failure_on_stderr_and_returns_nonzero(monkeypatch, capsys, error):
    class FailingCollector:
        def __init__(self, **_kwargs):
            pass

        def collect(self, *, force: bool = False):
            raise error

    monkeypatch.setattr(sys, "argv", ["yt-benchmark-comments", "--yes"])
    monkeypatch.setattr(mod, "BenchmarkCommentCollector", FailingCollector)

    assert mod.main() == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err
    assert str(error) in captured.err
