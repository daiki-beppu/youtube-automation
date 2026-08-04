"""Issue #1948: benchmark CLI の competitor 語彙契約。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_automation.commands.analytics import benchmark_collector
from youtube_automation.commands.thumbnail import compare_thumbnails


@pytest.mark.parametrize(
    "build_parser",
    [benchmark_collector._build_parser, compare_thumbnails._build_parser],
)
def test_parsers_accept_competitor(build_parser):
    args = build_parser().parse_args(["--competitor", "celtic-music"])

    assert args.competitor == "celtic-music"


@pytest.mark.parametrize(
    "build_parser",
    [benchmark_collector._build_parser, compare_thumbnails._build_parser],
)
@pytest.mark.parametrize("legacy_args", [["--channel", "celtic-music"], ["--channel=celtic-music"]])
def test_removed_channel_flag_names_competitor_replacement(build_parser, legacy_args, capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(legacy_args)

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "usage:" in stderr
    assert "--channel は --competitor に変わりました" in stderr


def test_thumbnail_compare_refreshes_benchmark_before_loading_videos(monkeypatch, tmp_path):
    comparer = compare_thumbnails.ThumbnailComparer.__new__(compare_thumbnails.ThumbnailComparer)
    comparer.data_dir = tmp_path / "data"
    comparer.compare_dir = comparer.data_dir / "thumbnail_compare"
    comparer.benchmark_dir = comparer.compare_dir / "benchmark"
    comparer.channel_thumb_dir = comparer.compare_dir / "channel"
    comparer.small_dir = comparer.compare_dir / "small"
    comparer.min_views = 10000
    comparer.competitor_slug = None
    comparer.channel_slug = "channel"

    calls: list[tuple[str, object]] = []

    def fake_refresh(data_dir: Path, **factories: object) -> None:
        calls.append(("refresh", (data_dir, factories)))

    monkeypatch.setattr(compare_thumbnails, "ensure_benchmark_fresh", fake_refresh)
    monkeypatch.setattr(compare_thumbnails, "load_benchmark_videos", lambda *args, **kwargs: [])
    monkeypatch.setattr(comparer, "_collect_channel_thumbnails", lambda: [])

    comparer.collect_and_compare(no_open=True)

    assert calls == [
        (
            "refresh",
            (
                comparer.data_dir,
                {
                    "collector_factory": compare_thumbnails.BenchmarkCollector,
                    "analyzer_factory": compare_thumbnails.BenchmarkThumbnailAnalyzer,
                    "reporter_factory": compare_thumbnails.BenchmarkReportGenerator,
                },
            ),
        )
    ]


def test_thumbnail_compare_stops_before_side_effects_when_refresh_fails(monkeypatch, tmp_path):
    comparer = compare_thumbnails.ThumbnailComparer.__new__(compare_thumbnails.ThumbnailComparer)
    comparer.data_dir = tmp_path / "data"
    comparer.compare_dir = comparer.data_dir / "thumbnail_compare"
    comparer.benchmark_dir = comparer.compare_dir / "benchmark"
    comparer.channel_thumb_dir = comparer.compare_dir / "channel"
    comparer.small_dir = comparer.compare_dir / "small"
    comparer.min_views = 10000
    comparer.competitor_slug = None
    comparer.channel_slug = "channel"

    def fail_refresh(*args, **kwargs):
        raise RuntimeError("benchmark refresh failed")

    monkeypatch.setattr(compare_thumbnails, "ensure_benchmark_fresh", fail_refresh)
    load_videos = MagicMock(wraps=compare_thumbnails.load_benchmark_videos)
    collect_thumbnails = MagicMock(wraps=comparer._collect_channel_thumbnails)
    monkeypatch.setattr(compare_thumbnails, "load_benchmark_videos", load_videos)
    monkeypatch.setattr(comparer, "_collect_channel_thumbnails", collect_thumbnails)

    with pytest.raises(RuntimeError, match="benchmark refresh failed"):
        comparer.collect_and_compare(no_open=True)

    load_videos.assert_not_called()
    collect_thumbnails.assert_not_called()
    assert not comparer.compare_dir.exists()
