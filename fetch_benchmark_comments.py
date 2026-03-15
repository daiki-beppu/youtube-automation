#!/usr/bin/env python3
"""ベンチマーク動画のコメント収集・分析

ベンチマークチャンネルの1万再生以上の動画からコメントを取得し、
JSON に保存する。視聴者の声分析（CP4）のデータソース。

Usage:
    # チャンネルディレクトリから実行
    cd channels/fantasy-celtic-music

    python3 ../../automation/fetch_benchmark_comments.py                    # 1万再生以上の動画のコメント取得
    python3 ../../automation/fetch_benchmark_comments.py --min-views 5000   # 閾値変更
    python3 ../../automation/fetch_benchmark_comments.py --max-comments 50  # 動画あたりの取得数変更
    python3 ../../automation/fetch_benchmark_comments.py --force            # 既存データがあっても再取得
"""

import argparse
import json
import logging
from datetime import date, datetime

import utils._path_setup  # noqa: F401
from benchmark_collector import ensure_benchmark_fresh, load_benchmark_videos  # noqa: E402
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.youtube_service import get_youtube  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_MIN_VIEWS = 10000
DEFAULT_MAX_COMMENTS = 100


class BenchmarkCommentCollector:
    """ベンチマーク動画のコメント収集"""

    def __init__(self, min_views: int = DEFAULT_MIN_VIEWS, max_comments: int = DEFAULT_MAX_COMMENTS):
        self.channel_dir = ChannelConfig.channel_dir()
        self.data_dir = self.channel_dir / "data"
        self.min_views = min_views
        self.max_comments = max_comments
        self.youtube = None
        self.today = date.today()

    def _fetch_comments(self, video_id: str) -> list[dict]:
        """1動画のコメントを取得"""
        try:
            response = self.youtube.commentThreads().list(
                videoId=video_id,
                part="snippet",
                order="relevance",
                maxResults=self.max_comments,
            ).execute()
        except Exception as e:
            logger.warning("コメント取得失敗 %s: %s", video_id, e)
            return []

        comments = []
        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "author": snippet["authorDisplayName"],
                "text": snippet["textOriginal"],
                "likes": snippet["likeCount"],
                "published_at": snippet["publishedAt"],
                "comment_id": item["snippet"]["topLevelComment"]["id"],
            })

        return comments

    def collect(self, force: bool = False) -> dict:
        """全対象動画のコメントを収集"""
        output_path = self.data_dir / f"comments_{self.today.strftime('%Y%m%d')}.json"
        if output_path.exists() and not force:
            logger.info("本日分は収集済み: %s（--force で再取得）", output_path.name)
            with open(output_path) as f:
                return json.load(f)

        ensure_benchmark_fresh(self.data_dir)

        targets = load_benchmark_videos(self.data_dir, min_views=self.min_views)
        if not targets:
            logger.error("対象動画が見つかりません。先に /benchmark を実行してください。")
            return {}

        logger.info("対象動画: %d本（%s再生以上）", len(targets), f"{self.min_views:,}")

        logger.info("YouTube API 認証中...")
        self.youtube = get_youtube()
        logger.info("認証完了")

        result = {
            "collected_at": datetime.now().isoformat(),
            "min_views": self.min_views,
            "max_comments_per_video": self.max_comments,
            "videos": [],
            "summary": {
                "total_videos": 0,
                "total_comments": 0,
                "by_channel": {},
            },
        }

        for i, target in enumerate(targets, 1):
            vid = target["video_id"]
            logger.info(
                "[%d/%d] %s (%s views) — %s",
                i, len(targets), target["title"][:50], f"{target['views']:,}", target["channel_name"],
            )

            comments = self._fetch_comments(vid)
            logger.info("  → %d件取得", len(comments))

            result["videos"].append({**target, "comments": comments, "comment_count": len(comments)})

            ch_slug = target["channel_slug"]
            if ch_slug not in result["summary"]["by_channel"]:
                result["summary"]["by_channel"][ch_slug] = {"name": target["channel_name"], "video_count": 0, "comment_count": 0}
            result["summary"]["by_channel"][ch_slug]["video_count"] += 1
            result["summary"]["by_channel"][ch_slug]["comment_count"] += len(comments)
            result["summary"]["total_comments"] += len(comments)

        result["summary"]["total_videos"] = len(result["videos"])

        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info("保存完了: %s（%d動画, %d件コメント）", output_path.name, result["summary"]["total_videos"], result["summary"]["total_comments"])
        return result


def print_summary(data: dict):
    """収集結果のサマリーを表示"""
    summary = data.get("summary", {})
    print(f"\n📊 コメント収集サマリー")
    print(f"   対象動画: {summary.get('total_videos', 0)}本")
    print(f"   総コメント: {summary.get('total_comments', 0)}件")
    print()
    for slug, info in summary.get("by_channel", {}).items():
        print(f"   {info['name']}: {info['video_count']}本, {info['comment_count']}件")
    print(f"\n📁 動画別コメント数:")
    for v in data.get("videos", []):
        print(f"   {v['views']:>7,} views | {v['comment_count']:>3}件 | {v['title'][:55]}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="ベンチマーク動画のコメント収集")
    parser.add_argument("--min-views", type=int, default=DEFAULT_MIN_VIEWS, help=f"最低再生数（default: {DEFAULT_MIN_VIEWS:,}）")
    parser.add_argument("--max-comments", type=int, default=DEFAULT_MAX_COMMENTS, help=f"動画あたりの最大取得数（default: {DEFAULT_MAX_COMMENTS}）")
    parser.add_argument("--force", action="store_true", help="既存データがあっても再取得")
    args = parser.parse_args()

    collector = BenchmarkCommentCollector(min_views=args.min_views, max_comments=args.max_comments)
    result = collector.collect(force=args.force)
    if result:
        print_summary(result)


if __name__ == "__main__":
    main()
