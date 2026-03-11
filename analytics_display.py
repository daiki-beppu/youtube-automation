#!/usr/bin/env python3
"""YouTube Analytics データ表示・分析

収集済みの JSON データファイルを読み込み、サマリー・トレンド・ランキングを表示する。
"""

import argparse
import json
import logging
import sys

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402

logger = logging.getLogger(__name__)


class AnalyticsDisplay:
    """アナリティクスデータ表示クラス"""

    def display_channel_summary(self, analytics_data):
        """
        チャンネル全体サマリー表示

        Args:
            analytics_data (Dict): アナリティクスデータ
        """
        print("\n" + "=" * 80)
        config = ChannelConfig.load()
        print(f"📊 {config.channel_name} ({config.channel_short}) - チャンネル全体統計")
        print("=" * 80)

        # 基本統計
        if 'channel_analytics' in analytics_data and 'summary' in analytics_data['channel_analytics']:
            summary = analytics_data['channel_analytics']['summary']
            period = analytics_data['collection_period']

            print(f"📅 分析期間: {period['start_date']} 〜 {period['end_date']}")
            print(f"🎯 総視聴回数: {summary['total_views']:,} views")
            print(f"⏱️  総視聴時間: {summary['total_watch_time']:,} 分 ({summary['total_watch_time']/60:.1f} 時間)")
            print(f"👥 純登録者増: {summary['net_subscribers']} 人")
            print(f"💬 総エンゲージメント: {summary['total_engagement']} (いいね+コメント+シェア)")

            # CTR情報があれば表示
            if 'average_ctr' in summary and summary['average_ctr'] > 0:
                ctr_value = summary['average_ctr']
                if ctr_value > 100:  # 数値が大きすぎる場合は補正
                    ctr_value = ctr_value / 10000  # パーセンテージに変換
                print(f"🎯 平均CTR: {ctr_value:.2f}%")

        # 動画統計
        if 'video_analytics' in analytics_data:
            videos = analytics_data['video_analytics']
            print("\n🎬 動画データ概要")
            print(f"📹 分析対象動画数: {len(videos)}本")

            # 上位動画
            sorted_videos = sorted(videos.items(), key=lambda x: x[1].get('views', 0), reverse=True)
            print("\n🏆 上位5本の動画:")
            for i, (video_id, video) in enumerate(sorted_videos[:5], 1):
                title = video.get('title', 'Unknown')[:60]
                views = video.get('views', 0)
                watch_time = video.get('estimated_minutes_watched', 0)
                print(f"  {i}. {title}...")
                print(f"     📊 {views:,} views | ⏱️ {watch_time:,} 分")

        # 戦略的分析サマリー
        if 'strategic_analysis' in analytics_data:
            strategic = analytics_data['strategic_analysis']['summary']
            print("\n📈 戦略的分析サマリー")
            print(f"🎯 上位動画: {strategic['top_videos_count']}本")
            print(f"📅 直近投稿: {strategic['recent_videos_count']}本")
            print(f"📊 総分析動画: {strategic['total_videos_analyzed']}本")

        print("=" * 80)

    def display_daily_trends(self, analytics_data, show_days=7):
        """
        日別トレンド表示

        Args:
            analytics_data (Dict): アナリティクスデータ
            show_days (int): 表示する日数
        """
        print("\n" + "=" * 60)
        print(f"📈 直近{show_days}日間の日別トレンド")
        print("=" * 60)

        if 'channel_analytics' in analytics_data and 'daily_metrics' in analytics_data['channel_analytics']:
            daily_data = analytics_data['channel_analytics']['daily_metrics']
            recent_days = daily_data[-show_days:]  # 最新N日間

            print("日付        | 視聴回数 | 視聴時間 | 登録者増減 | いいね")
            print("-" * 60)

            for day in recent_days:
                date = day['date']
                views = day['views']
                watch_time = day['watch_time']
                subs_gained = day['subscribers_gained']
                subs_lost = day['subscribers_lost']
                likes = day['likes']
                net_subs = subs_gained - subs_lost

                print(f"{date} | {views:8,} | {watch_time:6,}分 | {net_subs:8,} | {likes:6,}")
        else:
            print("❌ 日別データが見つかりません")

        print("=" * 60)

    def display_video_ranking(self, analytics_data, top_count=10):
        """
        動画ランキング表示

        Args:
            analytics_data (Dict): アナリティクスデータ
            top_count (int): 表示する動画数
        """
        print("\n" + "=" * 80)
        print(f"🏆 動画パフォーマンス ランキング TOP {top_count}")
        print("=" * 80)

        if 'video_analytics' in analytics_data:
            videos = analytics_data['video_analytics']
            sorted_videos = sorted(videos.items(), key=lambda x: x[1].get('views', 0), reverse=True)

            print("順位 | 視聴回数 | 視聴時間 | タイトル")
            print("-" * 80)

            for i, (video_id, video) in enumerate(sorted_videos[:top_count], 1):
                title = video.get('title', 'Unknown')[:50]
                views = video.get('views', 0)
                watch_time = video.get('estimated_minutes_watched', 0)

                print(f"{i:2d}位 | {views:8,} | {watch_time:6,}分 | {title}...")
        else:
            print("❌ 動画データが見つかりません")

        print("=" * 80)


def main():
    """CLI エントリーポイント"""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f'{config.channel_short} Analytics データ表示')
    parser.add_argument('--data-file', type=str, required=True, help='読み込む JSON データファイル')
    parser.add_argument('--show-summary', action='store_true', help='チャンネル全体サマリー表示')
    parser.add_argument('--show-trends', action='store_true', help='日別トレンド表示')
    parser.add_argument('--show-ranking', action='store_true', help='動画ランキング表示')
    parser.add_argument('--show-all', action='store_true', help='全ての分析結果を表示')
    parser.add_argument('--top-count', type=int, default=10, help='ランキング表示する動画数')
    parser.add_argument('--trend-days', type=int, default=7, help='トレンド表示する日数')

    args = parser.parse_args()

    # データファイル読み込み
    try:
        print(f"📂 データファイル読み込み中: {args.data_file}")
        with open(args.data_file, 'r', encoding='utf-8') as f:
            analytics_data = json.load(f)
        print("✅ データファイル読み込み完了")
    except Exception as e:
        print(f"❌ データファイル読み込みエラー: {e}")
        sys.exit(1)

    display = AnalyticsDisplay()
    display_anything = False

    if args.show_summary or args.show_all:
        display.display_channel_summary(analytics_data)
        display_anything = True

    if args.show_trends or args.show_all:
        display.display_daily_trends(analytics_data, show_days=args.trend_days)
        display_anything = True

    if args.show_ranking or args.show_all:
        display.display_video_ranking(analytics_data, top_count=args.top_count)
        display_anything = True

    if not display_anything:
        print("\n💡 表示オプションを指定してください:")
        print("   --show-summary     チャンネル全体サマリー")
        print("   --show-trends      日別トレンド")
        print("   --show-ranking     動画ランキング")
        print("   --show-all         全ての分析結果")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
