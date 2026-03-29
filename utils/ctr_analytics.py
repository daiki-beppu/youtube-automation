"""
CTR・コレクション分析 Mixin
YouTubeAnalyticsCollector の CTR 特化分析メソッド群
"""

from typing import Dict, List


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

        print("🎯 CTR詳細分析実行中...")

        try:
            # 基本メトリクス（impressions不使用）
            overall_response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,likes,comments,shares,subscribersGained'
            ).execute()

            # 動画別データ（トップ30）
            video_ctr_response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,likes,comments,estimatedMinutesWatched',
                dimensions='video',
                sort='-views',
                maxResults=30
            ).execute()

            # エンゲージメントデータ
            traffic_response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,estimatedMinutesWatched',
                dimensions='day'
            ).execute()

            return {
                'period': f"{start_date} to {end_date}",
                'overall_engagement': self._process_overall_ctr(overall_response),
                'video_performance': self._process_video_ctr(video_ctr_response),
                'daily_traffic': self._process_traffic_source_ctr(traffic_response),
                'performance_analysis': self._analyze_ctr_performance(video_ctr_response),
                # 後方互換キー
                'overall_ctr': self._process_overall_ctr(overall_response),
                'video_ctr_ranking': self._process_video_ctr(video_ctr_response),
                'traffic_source_ctr': self._process_traffic_source_ctr(traffic_response),
                'ctr_analysis': self._analyze_ctr_performance(video_ctr_response),
            }

        except Exception as e:
            print(f"❌ CTR分析エラー: {e}")
            return {'error': str(e)}

    def get_collection_performance(self, start_date: str, end_date: str) -> Dict:
        """
        コレクション別パフォーマンス分析

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: コレクション分析結果
        """
        print("🎵 コレクション別パフォーマンス分析中...")

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
        """動画別パフォーマンス処理
        メトリクス: views,likes,comments,estimatedMinutesWatched (dimensions=video)
        row: [video_id, views, likes, comments, watch_time_minutes]
        """
        video_data = []

        if 'rows' in response:
            video_ids = [row[0] for row in response['rows']]
            video_details = self._get_video_details(video_ids)

            for row in response['rows']:
                video_id = row[0]
                video_detail = video_details.get(video_id, {})

                video_data.append({
                    'video_id': video_id,
                    'title': video_detail.get('title', 'Unknown'),
                    'views': row[1],
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
        """動画パフォーマンス分析
        Note: CTR は YouTube Analytics API v2 では取得不可。
        代わりに views ベースのパフォーマンス分析を行う。
        """
        if not response.get('rows'):
            return {}

        views = [row[1] for row in response['rows']]

        return {
            'highest_views': max(views),
            'lowest_views': min(views),
            'average_views': sum(views) / len(views),
            'total_videos': len(views),
        }

    def _calculate_collection_stats(self, videos: List[Dict]) -> Dict:
        """コレクション統計計算"""
        if not videos:
            return {}

        total_views = sum(v['views'] for v in videos)
        total_engagement = sum(v['likes'] + v['comments'] + v['shares'] for v in videos)

        return {
            'video_count': len(videos),
            'total_views': total_views,
            'average_views': total_views / len(videos),
            'total_watch_time': sum(v['watch_time_minutes'] for v in videos),
            'total_engagement': total_engagement,
            'average_engagement_rate': sum(v['engagement_rate'] for v in videos) / len(videos),
            'subscribers_gained': sum(v['subscribers_gained'] for v in videos)
        }

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
