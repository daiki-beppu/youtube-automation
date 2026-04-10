"""
CTR・コレクション分析 Mixin
YouTubeAnalyticsCollector の CTR 特化分析メソッド群
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List

from googleapiclient.errors import HttpError

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401


logger = logging.getLogger(__name__)


class CTRAnalyticsMixin:
    """CTR分析・コレクション別パフォーマンス分析"""

    def get_ctr_analysis(self, start_date: str, end_date: str) -> Dict:
        """
        CTR詳細分析

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: CTR分析結果
        """
        if not self.analytics_service:
            self.initialize()

        logger.info("CTR詳細分析実行中...")

        try:
            # 基本メトリクス
            overall_response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,likes,comments,shares,subscribersGained'
            ).execute()

            # 動画別データ（トップ30）— impressions/CTR 取得を試行
            video_ctr_response = self._fetch_video_ctr_with_impressions(start_date, end_date)

            # エンゲージメントデータ
            traffic_response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,estimatedMinutesWatched',
                dimensions='day'
            ).execute()

            overall_data = self._process_overall_ctr(overall_response)
            video_data = self._process_video_ctr(video_ctr_response)
            daily_data = self._process_traffic_source_ctr(traffic_response)
            perf_analysis = self._analyze_ctr_performance(video_ctr_response)

            # impressions 集計（動画レベルの合算でチャンネルレベル CTR を推定）
            impressions_data = self._aggregate_impressions(video_data)

            return {
                'period': f"{start_date} to {end_date}",
                'impressions_available': video_ctr_response.get('_impressions_available', False),
                'impressions_summary': impressions_data,
                'overall_engagement': overall_data,
                'video_performance': video_data,
                'daily_traffic': daily_data,
                'performance_analysis': perf_analysis,
                # 後方互換キー
                'overall_ctr': overall_data,
                'video_ctr_ranking': video_data,
                'traffic_source_ctr': daily_data,
                'ctr_analysis': perf_analysis,
            }

        except HttpError as e:
            logger.error(f"YouTube API エラー（CTR分析）: {e}")
            return {'error': str(e)}
        except Exception as e:
            logger.error(f"CTR分析エラー: {e}")
            return {'error': str(e)}

    def _fetch_video_ctr_with_impressions(self, start_date: str, end_date: str) -> Dict:
        """動画別 CTR データ取得（impressions 付きを試行、失敗時はフォールバック）"""
        try:
            response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,impressions,impressionClickThroughRate,likes,comments,estimatedMinutesWatched',
                dimensions='video',
                sort='-views',
                maxResults=30
            ).execute()
            response['_impressions_available'] = True
            response['_metrics_order'] = (
                'views,impressions,impressionClickThroughRate,likes,comments,estimatedMinutesWatched'
            )
            logger.info("impressions/CTR 取得成功 — YouTube Analytics API v2 で利用可能")
            return response
        except HttpError as e:
            logger.warning(f"impressions/CTR 取得不可、フォールバック: {e}")
            response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,likes,comments,estimatedMinutesWatched',
                dimensions='video',
                sort='-views',
                maxResults=30
            ).execute()
            response['_impressions_available'] = False
            response['_metrics_order'] = 'views,likes,comments,estimatedMinutesWatched'
            return response

    def _aggregate_impressions(self, video_data: List[Dict]) -> Dict:
        """動画レベルの impressions/CTR を集計してチャンネルサマリーを生成"""
        total_impressions = sum(v.get('impressions', 0) for v in video_data)
        total_views = sum(v.get('views', 0) for v in video_data)

        if total_impressions > 0:
            aggregated_ctr = (total_views / total_impressions) * 100
        else:
            aggregated_ctr = 0

        return {
            'total_impressions': total_impressions,
            'total_views_from_impressions': total_views,
            'aggregated_ctr_percentage': round(aggregated_ctr, 2),
        }

    def get_collection_performance(self, start_date: str, end_date: str) -> Dict:
        """
        コレクション別パフォーマンス分析

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: コレクション分析結果
        """
        logger.info("コレクション別パフォーマンス分析中...")

        # 動画データ取得
        videos_data = self.get_video_analytics(start_date, end_date)

        if not videos_data:
            return {'error': 'データが取得できませんでした'}

        # コレクション分類
        collections = {
            'Adventure': [],
            'Battle': [],
            'Boss Battle': [],
            'Village/Town': [],
            'Dungeon': [],
            'Castle': [],
            'Field': [],
            'Ocean': [],
            'Other': []
        }

        for video in videos_data:
            collection_type = self._classify_collection_type(video['title'])
            collections[collection_type].append(video)

        # コレクション別統計計算
        collection_stats = {}
        for collection_name, videos in collections.items():
            if videos:
                collection_stats[collection_name] = self._calculate_collection_stats(videos)

        return {
            'period': f"{start_date} to {end_date}",
            'collection_performance': collection_stats,
            'top_performers': self._identify_top_performers(videos_data),
            'ctr_by_collection': self._analyze_ctr_by_collection(videos_data),
            'recommendations': self._generate_collection_recommendations(collection_stats)
        }

    def _classify_collection_type(self, title: str) -> str:
        """コレクションタイプ分類"""
        title_lower = title.lower()

        classification_map = {
            'adventure': 'Adventure',
            'boss': 'Boss Battle',
            'battle': 'Battle',
            'village': 'Village/Town',
            'town': 'Village/Town',
            'dungeon': 'Dungeon',
            'castle': 'Castle',
            'field': 'Field',
            'ocean': 'Ocean'
        }

        for keyword, collection_type in classification_map.items():
            if keyword in title_lower:
                return collection_type

        return 'Other'

    def _process_overall_ctr(self, response: Dict) -> Dict:
        """全体エンゲージメント処理
        Note: YouTube Analytics API v2 ではサムネイル CTR (impressionClickThroughRate) は
        取得不可。ここでは views/likes/comments/shares/subscribersGained を処理する。
        """
        if 'rows' in response and response['rows']:
            row = response['rows'][0]
            return {
                'total_views': row[0],
                'total_likes': row[1],
                'total_comments': row[2],
                'total_shares': row[3],
                'subscribers_gained': row[4],
            }
        return {}

    def _evaluate_ctr_performance(self, ctr: float) -> str:
        """CTRパフォーマンス評価"""
        if ctr >= 2.0:
            return 'Excellent (目標達成)'
        elif ctr >= 1.5:
            return 'Good (改善中)'
        elif ctr >= 1.0:
            return 'Average (要改善)'
        else:
            return 'Poor (緊急改善必要)'

    def _process_video_ctr(self, response: Dict) -> List[Dict]:
        """動画別パフォーマンス処理（impressions 有無で分岐）"""
        video_data = []
        impressions_available = response.get('_impressions_available', False)

        if 'rows' in response:
            video_ids = [row[0] for row in response['rows']]
            video_details = self._get_video_details(video_ids)

            for row in response['rows']:
                video_id = row[0]
                video_detail = video_details.get(video_id, {})

                if impressions_available:
                    # row: [video_id, views, impressions, ctr, likes, comments, watch_time]
                    video_data.append({
                        'video_id': video_id,
                        'title': video_detail.get('title', 'Unknown'),
                        'views': row[1],
                        'impressions': row[2],
                        'impression_ctr': row[3],
                        'likes': row[4],
                        'comments': row[5],
                        'watch_time_minutes': row[6],
                        'collection_type': self._classify_collection_type(video_detail.get('title', '')),
                    })
                else:
                    # row: [video_id, views, likes, comments, watch_time]
                    video_data.append({
                        'video_id': video_id,
                        'title': video_detail.get('title', 'Unknown'),
                        'views': row[1],
                        'impressions': 0,
                        'impression_ctr': 0,
                        'likes': row[2],
                        'comments': row[3],
                        'watch_time_minutes': row[4],
                        'collection_type': self._classify_collection_type(video_detail.get('title', '')),
                    })

        return video_data

    def _process_traffic_source_ctr(self, response: Dict) -> List[Dict]:
        """日別トラフィック処理
        メトリクス: views,estimatedMinutesWatched (dimensions=day)
        row: [date, views, watch_time_minutes]
        """
        daily_traffic = []

        if 'rows' in response:
            for row in response['rows']:
                daily_traffic.append({
                    'date': row[0],
                    'views': row[1],
                    'watch_time_minutes': row[2],
                })

        return daily_traffic

    def _analyze_ctr_performance(self, response: Dict) -> Dict:
        """動画パフォーマンス分析（impressions 対応）"""
        if not response.get('rows'):
            return {}

        impressions_available = response.get('_impressions_available', False)
        views = [row[1] for row in response['rows']]

        result = {
            'highest_views': max(views),
            'lowest_views': min(views),
            'average_views': sum(views) / len(views),
            'total_videos': len(views),
        }

        if impressions_available:
            impressions = [row[2] for row in response['rows'] if row[2] > 0]
            ctrs = [row[3] for row in response['rows'] if row[3] > 0]
            if impressions:
                result['total_impressions'] = sum(impressions)
                result['average_impressions'] = sum(impressions) / len(impressions)
            if ctrs:
                result['average_ctr'] = sum(ctrs) / len(ctrs)
                result['highest_ctr'] = max(ctrs)
                result['lowest_ctr'] = min(ctrs)

        return result

    def _calculate_collection_stats(self, videos: List[Dict]) -> Dict:
        """コレクション統計計算"""
        if not videos:
            return {}

        total_views = sum(v['views'] for v in videos)
        total_engagement = sum(v.get('likes', 0) + v.get('comments', 0) + v.get('shares', 0) for v in videos)
        total_impressions = sum(v.get('impressions', 0) for v in videos)

        stats = {
            'video_count': len(videos),
            'total_views': total_views,
            'average_views': total_views / len(videos),
            'total_watch_time': sum(v.get('watch_time_minutes', 0) for v in videos),
            'total_engagement': total_engagement,
            'average_engagement_rate': sum(v.get('engagement_rate', 0) for v in videos) / len(videos),
            'subscribers_gained': sum(v.get('subscribers_gained', 0) for v in videos),
        }

        if total_impressions > 0:
            stats['total_impressions'] = total_impressions
            stats['average_ctr'] = (total_views / total_impressions) * 100

        return stats

    def _identify_top_performers(self, videos: List[Dict]) -> Dict:
        """トップパフォーマー特定"""
        if not videos:
            return {}

        # 各メトリクスでのトップ3
        top_by_views = sorted(videos, key=lambda x: x['views'], reverse=True)[:3]
        top_by_engagement = sorted(videos, key=lambda x: x['engagement_rate'], reverse=True)[:3]

        return {
            'top_by_views': [
                {'title': v['title'], 'views': v['views'], 'url': v['url']}
                for v in top_by_views
            ],
            'top_by_engagement': [
                {'title': v['title'], 'rate': v['engagement_rate'], 'url': v['url']}
                for v in top_by_engagement
            ],
        }

    def _analyze_ctr_by_collection(self, videos: List[Dict]) -> Dict:
        """コレクション別CTR分析（推定）"""
        collection_performance = {}

        for video in videos:
            collection = video['collection_type']
            if collection not in collection_performance:
                collection_performance[collection] = []
            collection_performance[collection].append(video)

        return {collection: self._calculate_collection_stats(vids)
                for collection, vids in collection_performance.items()}

    def _generate_collection_recommendations(self, collection_stats: Dict) -> List[str]:
        """改善提案生成"""
        recommendations = []

        if not collection_stats:
            return ["データが不足しています"]

        # パフォーマンス分析と提案
        best_performer = max(collection_stats.items(),
                           key=lambda x: x[1].get('average_views', 0))

        recommendations.append(f"🏆 最高パフォーマンス: {best_performer[0]} コレクション")
        recommendations.append(f"💡 {best_performer[0]} の成功要因を他のコレクションに適用を検討")

        # CTR改善提案
        recommendations.append("🎯 CTR改善策:")
        recommendations.append("  - Boss Battle系のサムネイル技法を他テーマに応用")
        recommendations.append("  - Adventure系の感情訴求強化")
        recommendations.append("  - モバイル最適化の徹底")

        return recommendations
