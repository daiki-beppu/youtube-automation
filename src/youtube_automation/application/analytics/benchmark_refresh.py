"""Application service for keeping benchmark data available to consumers."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Protocol

from youtube_automation.application.analytics.benchmark_query import find_latest_benchmark_json
from youtube_automation.core.errors import ConfigError, DocumentPairMismatchError, YouTubeAPIError

logger = logging.getLogger(__name__)


BenchmarkData = dict[str, object]


class _BenchmarkChannels(Protocol):
    channels: Sequence[Mapping[str, str]]


class _AnalyticsConfig(Protocol):
    benchmark: _BenchmarkChannels


class _CollectorConfig(Protocol):
    analytics: _AnalyticsConfig


class _BenchmarkCollector(Protocol):
    config: _CollectorConfig
    benchmark_config: Mapping[str, object]
    benchmarks_dir: Path
    today: date

    def check_freshness(self) -> list[Mapping[str, str]]: ...

    def initialize(self) -> None: ...

    def collect_all(self, *, force: bool) -> BenchmarkData: ...

    def download_thumbnails(self, data: BenchmarkData, *, force: bool) -> None: ...

    def save_json(self, data: BenchmarkData) -> Path: ...


class _ThumbnailAnalyzer(Protocol):
    def analyze_thumbnails(self, data: BenchmarkData, *, keep: bool) -> BenchmarkData: ...


class _BenchmarkReporter(Protocol):
    def generate_markdown(self, data: BenchmarkData) -> Mapping[str, str]: ...

    def write_markdown(self, md_map: Mapping[str, str]) -> None: ...


def ensure_benchmark_fresh(
    data_dir: Path,
    *,
    collector_factory: Callable[[], _BenchmarkCollector],
    analyzer_factory: Callable[[Path], _ThumbnailAnalyzer],
    reporter_factory: Callable[[object, Path, date], _BenchmarkReporter],
) -> None:
    """Ensure benchmark data contains every configured channel and is current."""
    collector = collector_factory()

    if not collector.config.analytics.benchmark.channels:
        raise ConfigError(
            "ベンチマーク対象チャンネルが未設定です。"
            "config/channel/analytics.json の benchmark.channels を設定してください。"
        )

    expected_slugs = {channel["slug"] for channel in collector.config.analytics.benchmark.channels}
    latest = find_latest_benchmark_json(data_dir)
    need_update = latest is None

    if latest is not None:
        latest_data = json.loads(latest.read_text(encoding="utf-8"))
        found_slugs = {channel.get("slug") for channel in latest_data.get("channels", [])}
        missing = expected_slugs - found_slugs
        if missing:
            logger.info("ベンチマーク: 最新 JSON に %s が欠けている → 全チャンネル更新", missing)
            need_update = True
        else:
            try:
                stale = collector.check_freshness()
            except DocumentPairMismatchError as error:
                # 公開済み HTML だけが renderer 更新に追従できていない状態。
                # 収集済み JSON は全チャンネル揃っているため、stale HTML を使わず
                # そのまま呼び出し元へ返して処理を継続させる。
                logger.warning(
                    "ベンチマーク: 文書 pair が不整合のため鮮度確認をスキップします（%s）。"
                    "stale HTML は使用せず収集済み JSON で続行します。"
                    "文書を再発行するには channel repository で "
                    "`uv run yt-document-render --fix --all .` を実行してください。",
                    error,
                )
                return
            if stale:
                logger.info("ベンチマーク: %d チャンネルが古い → 全チャンネル更新", len(stale))
                need_update = True
    else:
        logger.info("ベンチマーク: JSON が存在しない → 全チャンネル更新")

    if not need_update:
        logger.info("ベンチマーク: 全チャンネル最新（%d チャンネル）", len(expected_slugs))
        return

    collector.initialize()
    data = collector.collect_all(force=True)
    if data.get("skipped") or not data.get("channels"):
        raise YouTubeAPIError(
            "ベンチマークの最新化に失敗しました（収集結果が空）。"
            "API 認証・クォータ・benchmark.channels の設定を確認のうえ "
            "`/channel-research --benchmark`（uv run yt-benchmark-collect）を再実行してください。"
        )

    collector.download_thumbnails(data, force=True)
    if collector.benchmark_config.get("gemini_thumbnail_analysis", False):
        analyzer = analyzer_factory(collector.benchmarks_dir)
        data = analyzer.analyze_thumbnails(data, keep=True)

    collector.save_json(data)
    reporter = reporter_factory(collector.config, collector.benchmarks_dir, collector.today)
    reporter.write_markdown(reporter.generate_markdown(data))
    logger.info("ベンチマーク更新完了")
