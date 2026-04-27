#!/usr/bin/env python3
"""
YouTube Analytics データ収集ユーティリティ
YouTube Analytics API を使用したチャンネル分析データの取得・処理

Features:
- チャンネル全体の統計データ取得
- 動画別パフォーマンス分析
- CTR・視聴時間・エンゲージメント分析
- 戦略用メトリクス収集

Note:
    メソッドは3つの Mixin に分割されています:
    - channel_analytics.py: チャンネル全体統計
    - video_listing.py: 動画一覧取得
    - video_analytics.py: 動画別分析（コア）
    - strategic_analytics.py: 戦略的統合分析
    - ctr_analytics.py: CTR・コレクション分析
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Any

from youtube_automation.utils.audience_analytics import AudienceAnalyticsMixin
from youtube_automation.utils.channel_analytics import ChannelAnalyticsMixin
from youtube_automation.utils.ctr_analytics import CTRAnalyticsMixin
from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.reporting_analytics import ReportingAPIMixin
from youtube_automation.utils.retention_analytics import RetentionAnalyticsMixin
from youtube_automation.utils.strategic_analytics import StrategicAnalyticsMixin
from youtube_automation.utils.traffic_source_analytics import TrafficSourceMixin
from youtube_automation.utils.video_analytics import VideoAnalyticsMixin
from youtube_automation.utils.video_daily_analytics import VideoDailyAnalyticsMixin
from youtube_automation.utils.video_listing import VideoListingMixin
from youtube_automation.utils.youtube_service import get_analytics, get_youtube

logger = logging.getLogger(__name__)


class YouTubeAnalyticsCollector(
    ChannelAnalyticsMixin,
    VideoListingMixin,
    VideoAnalyticsMixin,
    VideoDailyAnalyticsMixin,
    StrategicAnalyticsMixin,
    CTRAnalyticsMixin,
    TrafficSourceMixin,
    AudienceAnalyticsMixin,
    RetentionAnalyticsMixin,
    ReportingAPIMixin,
):
    """YouTube Analytics データ収集クラス"""

    def __init__(self):
        """初期化"""
        self.youtube_service: Any = None
        self.analytics_service: Any = None
        self.channel_id: str | None = None

    def initialize(self):
        """YouTube API 初期化"""
        logger.info("YouTube Analytics API 認証中...")

        self.youtube_service = get_youtube()
        self.analytics_service = get_analytics()

        # チャンネルID取得
        self.channel_id = self._get_channel_id()

        logger.info("YouTube Analytics API 準備完了")

    def _get_channel_id(self) -> str:
        """チャンネルID取得"""
        try:
            response = self.youtube_service.channels().list(part="id,snippet", mine=True).execute()

            if response["items"]:
                channel = response["items"][0]
                self.channel_id = channel["id"]
                logger.info(f"チャンネル: {channel['snippet']['title']} ({self.channel_id})")
                return self.channel_id
            else:
                raise YouTubeAPIError("チャンネル情報が取得できませんでした")

        except YouTubeAPIError:
            raise
        except Exception as e:
            logger.error(f"チャンネルID取得エラー: {e}")
            raise


def main():
    """メイン関数 - スタンドアロン実行用"""
    import argparse

    parser = argparse.ArgumentParser(description="YouTube Analytics 収集")
    parser.add_argument("--days", "-d", type=int, default=30, help="過去の日数")
    parser.add_argument("--ctr-only", action="store_true", help="CTR分析のみ")
    parser.add_argument("--collections", action="store_true", help="コレクション分析")

    args = parser.parse_args()

    try:
        collector = YouTubeAnalyticsCollector()
        collector.initialize()

        # 日付範囲計算
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

        print("📊 YouTube Analytics 分析")
        print(f"📅 期間: {start_date} - {end_date}")
        print("=" * 60)

        if args.ctr_only:
            # CTR分析のみ
            ctr_data = collector.get_ctr_analysis(start_date, end_date)
            print(json.dumps(ctr_data, indent=2, ensure_ascii=False))

        elif args.collections:
            # コレクション分析
            collection_data = collector.get_collection_performance(start_date, end_date)
            print(json.dumps(collection_data, indent=2, ensure_ascii=False))

        else:
            # 全体分析
            channel_data = collector.get_channel_analytics(start_date, end_date)
            video_data = collector.get_video_analytics(start_date, end_date)

            print("📊 チャンネル統計:")
            print(json.dumps(channel_data["summary"], indent=2, ensure_ascii=False))

            print("\n🎬 トップ動画:")
            for i, video in enumerate(video_data[:5], 1):
                print(f"  {i}. {video['title']} - {video['views']:,} views")

    except KeyboardInterrupt:
        print("\n🛑 分析が中断されました")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
