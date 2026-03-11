"""
8BAH - チャンネル全体統計 Mixin
YouTubeAnalyticsCollector のチャンネルレベル分析メソッド群
"""

from datetime import datetime
from typing import Dict


class ChannelAnalyticsMixin:
    """チャンネル全体の統計データ取得・処理"""

    def get_channel_analytics(self, start_date: str, end_date: str) -> Dict:
        """
        チャンネル全体のアナリティクス取得

        Args:
            start_date (str): 開始日 (YYYY-MM-DD)
            end_date (str): 終了日 (YYYY-MM-DD)

        Returns:
            Dict: チャンネル統計データ
        """
        if not self.analytics_service:
            self.initialize()

        print(f"📊 チャンネル分析データ取得中: {start_date} - {end_date}")

        try:
            # 基本メトリクス
            response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost,likes,dislikes,comments,shares',
                dimensions='day'
            ).execute()

            # Note: サムネイル CTR (impressionClickThroughRate) は
            # YouTube Analytics API v2 では取得不可。YouTube Studio でのみ確認可能。
            # 以前のコードは views/estimatedMinutesWatched を誤って impressions/ctr_percentage
            # としてマッピングしていたバグがあったため、ctr_data は空を返す。

            return {
                'period': f"{start_date} to {end_date}",
                'daily_metrics': self._process_daily_data(response),
                'ctr_data': {'impressions': 0, 'ctr_percentage': 0, 'note': 'CTR is not available via Analytics API'},
                'summary': self._calculate_summary_stats(response)
            }

        except Exception as e:
            print(f"❌ チャンネル分析取得エラー: {e}")
            return {'error': str(e)}

    def collect_basic_analytics(self, start_date: str, end_date: str) -> Dict:
        """
        基本アナリティクスデータ収集（シンプル版）

        Args:
            start_date (str): 開始日 (YYYY-MM-DD)
            end_date (str): 終了日 (YYYY-MM-DD)

        Returns:
            Dict: 収集された基本アナリティクスデータ
        """
        print(f"📊 基本アナリティクス収集: {start_date} 〜 {end_date}")

        try:
            # サービス初期化
            self.initialize()

            # 基本データ収集のみ
            print("📈 チャンネル統計データ収集中...")
            channel_analytics = self.get_channel_analytics(start_date, end_date)

            print("🎬 動画別パフォーマンス収集中...")
            strategic_analytics = self.get_strategic_video_analytics(start_date, end_date, mode="efficient")

            # 戦略的分析結果から動画データを統合
            video_analytics = strategic_analytics['top_videos'] + strategic_analytics['recent_videos']

            # 動画データをキー化
            video_data = {}
            for video in video_analytics:
                video_id = video.get('video_id')
                if video_id:
                    video_data[video_id] = video

            # 基本データ構築
            basic_data = {
                'collection_period': {
                    'start_date': start_date,
                    'end_date': end_date,
                    'collected_at': datetime.now().isoformat()
                },
                'channel_analytics': channel_analytics,
                'video_analytics': video_data,
                'strategic_analysis': strategic_analytics,
                'summary': {
                    'total_videos_analyzed': len(video_data),
                    'strategic_mode': strategic_analytics['mode'],
                    'analysis_breakdown': strategic_analytics['summary'],
                    'date_range_days': (datetime.strptime(end_date, '%Y-%m-%d') -
                                      datetime.strptime(start_date, '%Y-%m-%d')).days,
                    'collection_version': '2.0'
                }
            }

            print("✅ 基本アナリティクス収集完了")
            return basic_data

        except Exception as e:
            print(f"❌ データ収集エラー: {e}")
            print("🛑 エラーが発生したため処理を終了します")
            raise

    def _process_daily_data(self, response: Dict) -> list:
        """日別データ処理"""
        daily_data = []

        if 'rows' in response:
            for row in response['rows']:
                daily_data.append({
                    'date': row[0],
                    'views': row[1],
                    'watch_time': row[2],
                    'avg_duration': row[3],
                    'subscribers_gained': row[4],
                    'subscribers_lost': row[5],
                    'likes': row[6],
                    'dislikes': row[7],
                    'comments': row[8],
                    'shares': row[9]
                })

        return daily_data

    def _calculate_summary_stats(self, main_response: Dict) -> Dict:
        """サマリー統計計算"""
        summary = {
            'total_views': 0,
            'total_watch_time': 0,
            'net_subscribers': 0,
            'total_engagement': 0,
        }

        if 'rows' in main_response:
            for row in main_response['rows']:
                summary['total_views'] += row[1]
                summary['total_watch_time'] += row[2]
                summary['net_subscribers'] += (row[4] - row[5])
                summary['total_engagement'] += (row[6] + row[8] + row[9])

        return summary
