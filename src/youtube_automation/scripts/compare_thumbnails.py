#!/usr/bin/env python3
"""サムネイル比較検証ツール

ベンチマーク動画のサムネイルをダウンロードし、自チャンネルのサムネイルと並べて
比較できるようにする。320px 縮小版も自動生成。

Usage:
    # チャンネルディレクトリから実行
    cd channels/fantasy-celtic-music

    python3 ../../automation/compare_thumbnails.py                    # DL + 縮小 + open
    python3 ../../automation/compare_thumbnails.py --min-views 5000   # 閾値変更
    python3 ../../automation/compare_thumbnails.py --no-open          # open しない
    python3 ../../automation/compare_thumbnails.py --small-only       # 縮小版のみ表示
"""

import argparse
import logging
import os
import subprocess
import urllib.request
from pathlib import Path

from youtube_automation.scripts.benchmark_collector import (  # noqa: E402
    ensure_benchmark_fresh,
    load_benchmark_videos,
)
from youtube_automation.utils.channel_config import ChannelConfig  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_MIN_VIEWS = 10000
SMALL_WIDTH = 320
SMALL_HEIGHT = 180


class ThumbnailComparer:
    """サムネイル比較検証"""

    def __init__(self, min_views: int = DEFAULT_MIN_VIEWS):
        self.config = ChannelConfig.load()
        self.channel_dir = ChannelConfig.channel_dir()
        self.data_dir = self.channel_dir / "data"
        self.min_views = min_views

        self.channel_slug = self.config.raw.get("channel", {}).get("short", "channel").lower()
        self.compare_dir = self.data_dir / "thumbnail_compare"
        self.benchmark_dir = self.compare_dir / "benchmark"
        self.channel_thumb_dir = self.compare_dir / self.channel_slug
        self.small_dir = self.compare_dir / "small"

    def _collect_channel_thumbnails(self) -> list[Path]:
        """自チャンネルの全サムネイルパスを収集"""
        collections_dir = self.channel_dir / "collections" / "live"
        return sorted(collections_dir.glob("*/10-assets/thumbnail.jpg"))

    def _download_thumbnail(self, url: str, output_path: Path) -> bool:
        if output_path.exists():
            return True
        try:
            urllib.request.urlretrieve(url, str(output_path))
            return True
        except Exception as e:
            logger.warning("ダウンロード失敗 %s: %s", url, e)
            return False

    def _resize_thumbnail(self, input_path: Path, output_path: Path) -> bool:
        if output_path.exists():
            return True
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(input_path), "-vf", f"scale={SMALL_WIDTH}:{SMALL_HEIGHT}", "-y", str(output_path)],
                capture_output=True, check=True,
            )
            return True
        except FileNotFoundError:
            logger.error("FFmpeg がインストールされていません")
            return False
        except subprocess.CalledProcessError as e:
            logger.warning("リサイズ失敗 %s: %s", input_path.name, e)
            return False

    def collect_and_compare(self, no_open: bool = False, small_only: bool = False):
        """サムネイルを収集・縮小・表示"""
        ensure_benchmark_fresh(self.data_dir)

        for d in [self.benchmark_dir, self.channel_thumb_dir, self.small_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # ベンチマークサムネイルをダウンロード
        bench_videos = load_benchmark_videos(self.data_dir, min_views=self.min_views, require_thumbnail=True)
        logger.info("ベンチマーク対象: %d本（%s再生以上）", len(bench_videos), f"{self.min_views:,}")

        downloaded_bench = []
        for v in bench_videos:
            views_k = v["views"] // 1000
            filename = f"{v['channel_slug']}_{views_k}k_{v['video_id']}.jpg"
            output_path = self.benchmark_dir / filename
            if self._download_thumbnail(v["thumbnail_url"], output_path):
                downloaded_bench.append(output_path)
                logger.info("  ✅ %s (%dK views)", v["title"][:40], views_k)

        # 自チャンネルのサムネイルをシンボリックリンク
        channel_thumbs = self._collect_channel_thumbnails()
        logger.info("自チャンネルサムネイル: %d本", len(channel_thumbs))

        channel_copies = []
        for thumb in channel_thumbs:
            # コレクション名からテーマを抽出（例: 20260304-clm-fairy-forest-collection → fairy-forest）
            collection_name = thumb.parent.parent.name
            parts = collection_name.split("-")
            theme = "-".join(parts[2:-1]) if len(parts) > 3 else collection_name
            dest = self.channel_thumb_dir / f"{self.channel_slug}_{theme}.jpg"
            if not dest.exists():
                try:
                    os.symlink(thumb.resolve(), dest)
                except OSError:
                    import shutil
                    shutil.copy2(thumb, dest)
            channel_copies.append(dest)

        # 全サムネイルを 320x180 に縮小
        all_originals = downloaded_bench + channel_copies
        small_paths = []
        for orig in all_originals:
            small_path = self.small_dir / f"small_{orig.name}"
            if self._resize_thumbnail(orig, small_path):
                small_paths.append(small_path)

        logger.info("縮小版生成: %d枚", len(small_paths))

        print(f"\n📁 サムネイル比較ディレクトリ: {self.compare_dir}")
        print(f"   benchmark/  — ベンチマーク {len(downloaded_bench)}枚（原寸）")
        print(f"   {self.channel_slug}/        — 自チャンネル {len(channel_copies)}枚（原寸）")
        print(f"   small/      — 全 {len(small_paths)}枚（{SMALL_WIDTH}x{SMALL_HEIGHT}px モバイル表示）")

        if not no_open:
            subprocess.run(["open", str(self.small_dir if small_only else self.compare_dir)])


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="サムネイル比較検証")
    parser.add_argument(
        "--min-views", type=int, default=DEFAULT_MIN_VIEWS,
        help=f"最低再生数（default: {DEFAULT_MIN_VIEWS:,}）",
    )
    parser.add_argument("--no-open", action="store_true", help="ディレクトリを open しない")
    parser.add_argument("--small-only", action="store_true", help="縮小版のみ表示")
    args = parser.parse_args()

    comparer = ThumbnailComparer(min_views=args.min_views)
    comparer.collect_and_compare(no_open=args.no_open, small_only=args.small_only)


if __name__ == "__main__":
    main()
