#!/usr/bin/env python3
"""YouTube Analytics データ収集

YouTube Analytics API を使用してデータを収集し、JSON ファイルに保存する。
認証テストは auth_test.py、データ表示は analytics_display.py を使用。
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta

from youtube_automation.utils.analytics_collector import YouTubeAnalyticsCollector  # noqa: E402
from youtube_automation.utils.config import channel_dir, load_config  # noqa: E402

logger = logging.getLogger(__name__)


class AnalyticsSystem:
    """YouTube Analytics データ収集システム"""

    def __init__(self):
        """システム初期化"""
        config = load_config()
        logger.info(f"🎵 {config.meta.channel_name} - Analytics System v1.0")

        self.collector = YouTubeAnalyticsCollector()
        self.authenticated = False

    def authenticate(self, force_reauth=False):
        """
        YouTube API認証

        Args:
            force_reauth (bool): 強制再認証フラグ
        """
        logger.info("🔐 YouTube API認証中...")

        try:
            from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

            handler = YouTubeOAuthHandler()
            handler.authenticate(force_reauth=force_reauth)

            if handler.test_connection():
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
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            analytics_data = self.collector.collect_basic_analytics(
                start_date=start_date.strftime("%Y-%m-%d"), end_date=end_date.strftime("%Y-%m-%d")
            )

            if save_data:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                data_file = channel_dir() / "data" / f"analytics_data_{timestamp}.json"
                data_file.parent.mkdir(exist_ok=True)

                with open(data_file, "w", encoding="utf-8") as f:
                    json.dump(analytics_data, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 データ保存完了: {data_file}")

                # --- 動画×日次データを別ファイルに保存（launch curve 分析用）---
                try:
                    video_list = self.collector.get_all_channel_videos()
                    video_ids = [v["video_id"] for v in video_list]
                    daily_rows = self.collector.get_video_daily_analytics(
                        start_date.strftime("%Y-%m-%d"),
                        end_date.strftime("%Y-%m-%d"),
                        video_ids=video_ids,
                    )
                    daily_dir = channel_dir() / "data" / "analytics" / "daily_per_video"
                    daily_dir.mkdir(parents=True, exist_ok=True)
                    daily_file = daily_dir / (
                        f"{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.json"
                    )
                    with open(daily_file, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "start_date": start_date.strftime("%Y-%m-%d"),
                                "end_date": end_date.strftime("%Y-%m-%d"),
                                "video_ids": video_ids,
                                "rows": daily_rows,
                            },
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
                    logger.info(f"💾 動画×日次データ保存完了: {daily_file}")
                except Exception as e:
                    logger.warning(f"⚠️ 動画×日次データ保存失敗（続行）: {e}")

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
        config = load_config()
        logger.info(f"🚀 {config.meta.channel_short} YouTube Analytics データ収集開始...")
        logger.info(f"📊 収集期間: 過去{days}日間")

        results = {"success": False}

        if not self.authenticate():
            results["error"] = "Authentication failed"
            return results

        try:
            analytics_data = self.collect_analytics_data(days=days)
            if not analytics_data:
                results["error"] = "Data collection failed"
                logger.error("🛑 データ収集に失敗したため処理を終了します")
                return results
        except Exception as e:
            results["error"] = f"Data collection error: {e}"
            logger.error("🛑 データ収集エラーのため処理を終了します")
            return results

        logger.info("✅ YouTube Analyticsデータ収集完了")

        results["success"] = True
        results["analytics_data"] = analytics_data

        logger.info("🎉 データ収集完了！")

        return results


def main():
    """メイン関数 - CLI実行用"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config = load_config()
    parser = argparse.ArgumentParser(description=f"{config.meta.channel_short} Analytics データ収集")
    parser.add_argument("--days", type=int, default=30, help="データ収集期間（日数）")
    parser.add_argument("--all-time", action="store_true", help="全期間データを取得（チャンネル開設から現在まで）")

    args = parser.parse_args()

    system = AnalyticsSystem()

    if args.all_time:
        print("🌟 全期間データ取得モード（チャンネル開設～現在）")
        collection_days = 365
    else:
        collection_days = args.days

    results = system.run_data_collection(days=collection_days)

    if not results["success"]:
        print(f"\n❌ データ収集失敗: {results.get('error', 'Unknown error')}")
        sys.exit(1)

    print("\n📁 データ収集が正常に完了しました")
    print("💡 データ表示は analytics_display.py を使用してください:")
    print("   python3 analytics_display.py --data-file <FILE> --show-all")

    sys.exit(0)


if __name__ == "__main__":
    main()
