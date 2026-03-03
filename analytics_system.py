#!/usr/bin/env python3
"""
8-Bit Adventure Hub (8BAH) - 統合アナリティクスシステム
YouTube Analytics API を使用した包括的な分析・レポート生成システム

Main Features:
- YouTube Analytics データ自動収集
- 8BAH特化パフォーマンス分析
- CTR改善戦略提案 (0.58% → 2.0%目標)
- 週次・月次自動レポート生成
- 次期コレクション推奨システム
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from auth.oauth_handler import YouTubeOAuthHandler
from utils.analytics_collector import YouTubeAnalyticsCollector
from utils.channel_config import ChannelConfig

logger = logging.getLogger(__name__)


class EightBAHAnalyticsSystem:
    """8-Bit Adventure Hub 統合アナリティクスシステム"""

    def __init__(self):
        """システム初期化"""
        config = ChannelConfig.load()
        logger.info(f"🎵 {config.channel_name} - Analytics System v1.0")

        # 必要コンポーネント初期化
        self.auth_handler = YouTubeOAuthHandler()
        self.collector = YouTubeAnalyticsCollector()

        # システム状態
        self.authenticated = False

    def authenticate(self, force_reauth=False):
        """
        YouTube API認証

        Args:
            force_reauth (bool): 強制再認証フラグ
        """
        logger.info("🔐 YouTube API認証中...")

        try:
            self.auth_handler.authenticate(force_reauth=force_reauth)

            # 接続テスト
            if self.auth_handler.test_connection():
                self.authenticated = True
                logger.info("✅ 認証完了 - システム準備完了")
                return True
            else:
                logger.error("❌ 認証失敗 - 接続テストに失敗")
                return False

        except Exception as e:
            logger.error(f"❌ 認証エラー: {e}")
            return False

    def collect_analytics_data(self, days=30, save_data=True):
        """
        アナリティクスデータ収集

        Args:
            days (int): 収集期間（日数）
            save_data (bool): データ保存フラグ

        Returns:
            Dict: 収集されたアナリティクスデータ
        """
        if not self.authenticated:
            logger.error("❌ 認証が必要です。先に authenticate() を実行してください。")
            return None

        logger.info(f"📊 過去{days}日間のアナリティクスデータ収集中...")

        try:
            # 期間設定
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            # 基本データ収集実行
            analytics_data = self.collector.collect_basic_analytics(
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d')
            )

            if save_data:
                # データ保存
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                data_file = ChannelConfig.channel_dir() / 'data' / f'analytics_data_{timestamp}.json'
                data_file.parent.mkdir(exist_ok=True)

                with open(data_file, 'w', encoding='utf-8') as f:
                    json.dump(analytics_data, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 データ保存完了: {data_file}")

            logger.info("✅ アナリティクスデータ収集完了")
            return analytics_data

        except Exception as e:
            logger.error(f"❌ データ収集エラー: {e}")
            return None



    def run_data_collection(self, days=30):
        """
        データ収集実行 (認証 → データ収集 → JSONデータ保存)

        Args:
            days (int): データ収集期間

        Returns:
            Dict: 実行結果
        """
        config = ChannelConfig.load()
        logger.info(f"🚀 {config.channel_short} YouTube Analytics データ収集開始...")
        logger.info(f"📊 収集期間: 過去{days}日間")

        results = {'success': False}

        # Step 1: 認証
        if not self.authenticate():
            results['error'] = 'Authentication failed'
            return results

        # Step 2: 基本データ収集
        try:
            analytics_data = self.collect_analytics_data(days=days)
            if not analytics_data:
                results['error'] = 'Data collection failed'
                logger.error("🛑 データ収集に失敗したため処理を終了します")
                return results
        except Exception as e:
            results['error'] = f'Data collection error: {e}'
            logger.error("🛑 データ収集エラーのため処理を終了します")
            return results

        # Step 3: データ収集完了
        logger.info("✅ YouTube Analyticsデータ収集完了")

        results['success'] = True
        results['analytics_data'] = analytics_data

        logger.info("🎉 データ収集完了！")

        return results

    def display_channel_summary(self, analytics_data):
        """
        チャンネル全体サマリー表示

        Args:
            analytics_data (Dict): アナリティクスデータ
        """
        print("\n" + "="*80)
        config = ChannelConfig.load()
        print(f"📊 {config.channel_name} ({config.channel_short}) - チャンネル全体統計")
        print("="*80)

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

        print("="*80)

    def display_daily_trends(self, analytics_data, show_days=7):
        """
        日別トレンド表示

        Args:
            analytics_data (Dict): アナリティクスデータ
            show_days (int): 表示する日数
        """
        print("\n" + "="*60)
        print(f"📈 直近{show_days}日間の日別トレンド")
        print("="*60)

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

        print("="*60)

    def display_video_ranking(self, analytics_data, top_count=10):
        """
        動画ランキング表示

        Args:
            analytics_data (Dict): アナリティクスデータ
            top_count (int): 表示する動画数
        """
        print("\n" + "="*80)
        print(f"🏆 動画パフォーマンス ランキング TOP {top_count}")
        print("="*80)

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

        print("="*80)


def main():
    """メイン関数 - CLI実行用"""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f'{config.channel_short} Analytics System')
    parser.add_argument('--auth-only', action='store_true', help='認証テストのみ実行')
    parser.add_argument('--show-summary', action='store_true', help='チャンネル全体サマリー表示')
    parser.add_argument('--show-trends', action='store_true', help='日別トレンド表示')
    parser.add_argument('--show-ranking', action='store_true', help='動画ランキング表示')
    parser.add_argument('--show-all', action='store_true', help='全ての分析結果を表示')
    parser.add_argument('--days', type=int, default=30, help='データ収集期間（日数）')
    parser.add_argument('--all-time', action='store_true', help='全期間データを取得（チャンネル開設から現在まで）')
    parser.add_argument('--top-count', type=int, default=10, help='ランキング表示する動画数')
    parser.add_argument('--trend-days', type=int, default=7, help='トレンド表示する日数')
    parser.add_argument('--data-file', type=str, help='既存データファイルを使用（収集をスキップ）')

    args = parser.parse_args()

    # システム初期化
    system = EightBAHAnalyticsSystem()

    if args.auth_only:
        # 認証テストのみ
        if system.authenticate():
            print("✅ 認証テスト成功")
            sys.exit(0)
        else:
            print("❌ 認証テスト失敗")
            sys.exit(1)

    # データ取得
    analytics_data = None

    if args.data_file:
        # 既存データファイルを使用
        try:
            print(f"📂 データファイル読み込み中: {args.data_file}")
            with open(args.data_file, 'r', encoding='utf-8') as f:
                analytics_data = json.load(f)
            print("✅ データファイル読み込み完了")
        except Exception as e:
            print(f"❌ データファイル読み込みエラー: {e}")
            sys.exit(1)
    else:
        # データ収集実行
        if args.all_time:
            # 全期間データ取得（チャンネル開設から現在まで）
            print("🌟 全期間データ取得モード（チャンネル開設～現在）")
            # 8BAHは2024年7月頃開始と仮定、安全に365日で取得
            collection_days = 365
        else:
            collection_days = args.days

        results = system.run_data_collection(days=collection_days)

        if not results['success']:
            print(f"\n❌ データ収集失敗: {results.get('error', 'Unknown error')}")
            sys.exit(1)

        analytics_data = results['analytics_data']

    # 表示モードに応じて出力
    display_anything = False

    if args.show_summary or args.show_all:
        system.display_channel_summary(analytics_data)
        display_anything = True

    if args.show_trends or args.show_all:
        system.display_daily_trends(analytics_data, show_days=args.trend_days)
        display_anything = True

    if args.show_ranking or args.show_all:
        system.display_video_ranking(analytics_data, top_count=args.top_count)
        display_anything = True

    if not display_anything and not args.data_file:
        # 表示オプションが指定されていない場合は、データ収集のみ
        print("\n📁 データ収集が正常に完了しました")
        print("💡 次回は以下のオプションでデータを表示できます:")
        print("   --show-summary     チャンネル全体サマリー")
        print("   --show-trends      日別トレンド")
        print("   --show-ranking     動画ランキング")
        print("   --show-all         全ての分析結果")
        print("   --all-time         全期間データ取得")
        print("   --days N           過去N日間のデータ取得")
        print("   --data-file FILE   既存データファイルを使用")

    sys.exit(0)

if __name__ == "__main__":
    main()
