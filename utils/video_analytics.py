"""
8BAH - 動画別分析 Mixin
YouTubeAnalyticsCollector の動画レベル分析メソッド群
"""

from datetime import datetime, timedelta
from typing import Dict, List


class VideoAnalyticsMixin:
    """動画別の統計データ取得・処理"""

    def get_video_analytics(self, start_date: str, end_date: str) -> List[Dict]:
        """
        動画別アナリティクス取得

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            List[Dict]: 動画別統計データ
        """
        if not self.analytics_service:
            self.initialize()

        print("🎬 動画別分析データ取得中: 全動画")

        try:
            # 動画別メトリクス取得
            response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,estimatedMinutesWatched,averageViewDuration',
                dimensions='video',
                sort='-views',
                maxResults=10
            ).execute()

            videos_data = []

            if 'rows' in response:
                # 動画詳細情報を取得
                video_ids = [row[0] for row in response['rows']]
                video_details = self._get_video_details(video_ids)

                for i, row in enumerate(response['rows']):
                    video_id = row[0]
                    video_detail = video_details.get(video_id, {})

                    videos_data.append({
                        'video_id': video_id,
                        'title': video_detail.get('title', 'Unknown'),
                        'published_at': video_detail.get('published_at'),
                        'collection_type': self._classify_video_type(video_detail.get('title', '')),
                        'views': row[1],
                        'watch_time_minutes': row[2],
                        'average_view_duration': row[3],
                        'likes': row[4],
                        'dislikes': row[5],
                        'comments': row[6],
                        'shares': row[7],
                        'subscribers_gained': row[8],
                        'engagement_rate': self._calculate_engagement_rate(row),
                        'url': f"https://www.youtube.com/watch?v={video_id}"
                    })

            return videos_data

        except Exception as e:
            print(f"❌ 動画別分析取得エラー: {e}")
            return []

    def get_all_channel_videos(self) -> List[Dict]:
        """
        チャンネルの全動画リストを取得（YouTube Data API v3使用）

        Returns:
            List[Dict]: 動画情報リスト
        """
        if not self.youtube_service:
            self.initialize()

        print("🎥 チャンネル全動画リスト取得中...")

        try:
            # チャンネルのアップロード済みプレイリストIDを取得
            channel_response = self.youtube_service.channels().list(
                part='contentDetails',
                id=self.channel_id
            ).execute()

            uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

            # 全動画を取得
            videos = []
            next_page_token = None

            while True:
                # プレイリストのアイテムを取得
                playlist_response = self.youtube_service.playlistItems().list(
                    part='snippet,contentDetails',
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=next_page_token
                ).execute()

                for item in playlist_response['items']:
                    video_info = {
                        'video_id': item['contentDetails']['videoId'],
                        'title': item['snippet']['title'],
                        'published_at': item['snippet']['publishedAt'],
                        'description': (
                            item['snippet']['description'][:100] + '...'
                            if len(item['snippet']['description']) > 100
                            else item['snippet']['description']
                        )
                    }
                    videos.append(video_info)

                next_page_token = playlist_response.get('nextPageToken')
                if not next_page_token:
                    break

                print(f"  📄 {len(videos)}本の動画を取得済み...")

            print(f"✅ 全動画取得完了: {len(videos)}本")
            return videos

        except Exception as e:
            print(f"❌ 動画リスト取得エラー: {e}")
            return []

    def get_video_analytics_by_id(self, video_id: str, start_date: str, end_date: str) -> Dict:
        """
        特定動画のAnalyticsデータを取得

        Args:
            video_id (str): 動画ID
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: 動画のアナリティクスデータ
        """
        if not self.analytics_service:
            self.initialize()

        try:
            # 動画別メトリクス取得
            response = self.analytics_service.reports().query(
                ids=f'channel=={self.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,estimatedMinutesWatched,averageViewDuration',
                filters=f'video=={video_id}'
            ).execute()

            if 'rows' in response and response['rows']:
                row = response['rows'][0]
                return {
                    'video_id': video_id,
                    'views': row[0] if len(row) > 0 else 0,
                    'estimated_minutes_watched': row[1] if len(row) > 1 else 0,
                    'average_view_duration': row[2] if len(row) > 2 else 0
                }
            else:
                return {
                    'video_id': video_id,
                    'views': 0,
                    'estimated_minutes_watched': 0,
                    'average_view_duration': 0
                }

        except Exception as e:
            print(f"  ❌ 動画ID {video_id} の分析取得エラー: {e}")
            return {
                'video_id': video_id,
                'views': 0,
                'estimated_minutes_watched': 0,
                'average_view_duration': 0,
                'error': str(e)
            }

    def get_all_video_analytics(self, start_date: str, end_date: str) -> List[Dict]:
        """
        全動画のアナリティクス取得（制限なし版）

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            List[Dict]: 全動画の統計データ
        """
        print("🎬 動画別分析データ取得中: 全動画（制限なし）")

        # Step 1: 全動画リストを取得
        all_videos = self.get_all_channel_videos()
        if not all_videos:
            print("❌ 動画リストの取得に失敗しました")
            return []

        print(f"📊 {len(all_videos)}本の動画のAnalyticsデータを取得開始...")

        # Step 2: 各動画のAnalyticsデータを取得
        videos_data = []
        for i, video in enumerate(all_videos, 1):
            print(f"  📹 [{i}/{len(all_videos)}] {video['title'][:50]}...")

            analytics_data = self.get_video_analytics_by_id(
                video['video_id'],
                start_date,
                end_date
            )

            # 動画情報とAnalyticsデータを結合
            combined_data = {
                **video,  # title, published_at, description
                **analytics_data  # views, estimated_minutes_watched, average_view_duration
            }
            videos_data.append(combined_data)

            # 進行状況表示（10件ごと）
            if i % 10 == 0:
                print(f"    ✅ {i}本完了...")

        # 再生回数で降順ソート
        videos_data.sort(key=lambda x: x.get('views', 0), reverse=True)

        print(f"✅ 全動画Analytics取得完了: {len(videos_data)}本")
        return videos_data

    def get_top_video_analytics(self, start_date: str, end_date: str, top_count: int = 50) -> List[Dict]:
        """
        上位N本の動画アナリティクス取得（効率版）

        Args:
            start_date (str): 開始日
            end_date (str): 終了日
            top_count (int): 取得する上位動画数（デフォルト50本）

        Returns:
            List[Dict]: 上位動画の統計データ
        """
        print(f"🎬 上位{top_count}本の動画分析データ取得中...")

        videos_data = []
        remaining_count = top_count

        while remaining_count > 0 and len(videos_data) < top_count:
            batch_size = min(10, remaining_count)

            try:
                response = self.analytics_service.reports().query(
                    ids=f'channel=={self.channel_id}',
                    startDate=start_date,
                    endDate=end_date,
                    metrics='views,estimatedMinutesWatched,averageViewDuration',
                    dimensions='video',
                    sort='-views',
                    maxResults=batch_size,
                    startIndex=len(videos_data) + 1
                ).execute()

                if 'rows' not in response:
                    break

                # 動画詳細を取得
                video_ids = [row[0] for row in response['rows']]
                video_details = self._get_video_details(video_ids)

                for row in response['rows']:
                    video_id = row[0]
                    video_detail = video_details.get(video_id, {})

                    video_data = {
                        'video_id': video_id,
                        'title': video_detail.get('title', 'Unknown'),
                        'published_at': video_detail.get('published_at'),
                        'description': (
                            video_detail.get('description', '')[:100] + '...'
                            if len(video_detail.get('description', '')) > 100
                            else video_detail.get('description', '')
                        ),
                        'views': row[1],
                        'estimated_minutes_watched': row[2],
                        'average_view_duration': row[3],
                        'url': f"https://www.youtube.com/watch?v={video_id}"
                    }
                    videos_data.append(video_data)

                remaining_count -= len(response['rows'])
                print(f"  📊 {len(videos_data)}本取得済み...")

                # レスポンスが期待より少ない場合は終了
                if len(response['rows']) < batch_size:
                    break

            except Exception as e:
                print(f"  ❌ バッチ取得エラー: {e}")
                break

        print(f"✅ 上位動画Analytics取得完了: {len(videos_data)}本")
        return videos_data

    def get_recent_videos(self, days: int = 30) -> List[Dict]:
        """
        直近N日間の投稿動画を取得

        Args:
            days (int): 過去の日数（デフォルト30日）

        Returns:
            List[Dict]: 直近投稿動画リスト
        """
        if not self.youtube_service:
            self.initialize()

        print(f"📅 直近{days}日間の投稿動画を取得中...")

        try:
            cutoff_date = datetime.now() - timedelta(days=days)

            # 全動画リストを取得
            all_videos = self.get_all_channel_videos()

            # 直近の動画をフィルタリング
            recent_videos = []
            for video in all_videos:
                # ISO形式の日付をパース
                published_date = datetime.fromisoformat(video['published_at'].replace('Z', '+00:00'))

                if published_date.replace(tzinfo=None) >= cutoff_date:
                    recent_videos.append(video)

            # 投稿日時で降順ソート（新しい順）
            recent_videos.sort(key=lambda x: x['published_at'], reverse=True)

            print(f"✅ 直近{days}日間の投稿動画取得完了: {len(recent_videos)}本")
            return recent_videos

        except Exception as e:
            print(f"❌ 直近動画取得エラー: {e}")
            return []

    def get_recent_video_analytics(self, start_date: str, end_date: str, days: int = 30) -> List[Dict]:
        """
        直近N日間投稿動画のアナリティクス取得

        Args:
            start_date (str): 分析開始日
            end_date (str): 分析終了日
            days (int): 投稿から何日以内の動画を対象とするか

        Returns:
            List[Dict]: 直近投稿動画の統計データ
        """
        print(f"🎬 直近{days}日間投稿動画の分析データ取得中...")

        # 直近投稿動画を取得
        recent_videos = self.get_recent_videos(days)
        if not recent_videos:
            print("❌ 直近投稿動画が見つかりません")
            return []

        print(f"📊 {len(recent_videos)}本の直近動画のAnalyticsデータを取得開始...")

        # 各動画のAnalyticsデータを取得
        videos_data = []
        for i, video in enumerate(recent_videos, 1):
            print(f"  📹 [{i}/{len(recent_videos)}] {video['title'][:50]}...")

            analytics_data = self.get_video_analytics_by_id(
                video['video_id'],
                start_date,
                end_date
            )

            # 動画情報とAnalyticsデータを結合
            combined_data = {
                **video,
                **analytics_data
            }
            videos_data.append(combined_data)

        # 再生回数で降順ソート
        videos_data.sort(key=lambda x: x.get('views', 0), reverse=True)

        print(f"✅ 直近動画Analytics取得完了: {len(videos_data)}本")
        return videos_data

    def get_combined_analytics(
        self, start_date: str, end_date: str, top_count: int = 50, recent_days: int = 30
    ) -> Dict:
        """
        上位動画と直近投稿動画の統合取得（重複排除・一回取得）

        Args:
            start_date (str): 分析開始日
            end_date (str): 分析終了日
            top_count (int): 上位動画数（デフォルト50本）
            recent_days (int): 直近日数（デフォルト30日）

        Returns:
            Dict: 統合分析データ
        """
        print(f"🎯 統合Analytics取得: 上位{top_count}本 + 直近{recent_days}日投稿")

        # Step 1: 全動画リストを一回で取得
        print("📋 全動画リスト取得中...")
        all_videos = self.get_all_channel_videos()
        if not all_videos:
            return {'top_videos': [], 'recent_videos': []}

        # Step 2: 直近投稿動画をフィルタリング
        print(f"📅 直近{recent_days}日間の投稿動画をフィルタリング中...")
        cutoff_date = datetime.now() - timedelta(days=recent_days)

        recent_video_ids = set()
        recent_videos_info = []

        for video in all_videos:
            published_date = datetime.fromisoformat(video['published_at'].replace('Z', '+00:00'))
            if published_date.replace(tzinfo=None) >= cutoff_date:
                recent_video_ids.add(video['video_id'])
                recent_videos_info.append(video)

        print(f"  📊 直近投稿動画: {len(recent_videos_info)}本")

        # Step 3: 上位動画を効率的に取得
        print(f"🏆 上位{top_count}本の動画Analytics取得中...")
        top_videos_data = []
        remaining_count = top_count

        while remaining_count > 0 and len(top_videos_data) < top_count:
            batch_size = min(10, remaining_count)

            try:
                response = self.analytics_service.reports().query(
                    ids=f'channel=={self.channel_id}',
                    startDate=start_date,
                    endDate=end_date,
                    metrics='views,estimatedMinutesWatched,averageViewDuration',
                    dimensions='video',
                    sort='-views',
                    maxResults=batch_size,
                    startIndex=len(top_videos_data) + 1
                ).execute()

                if 'rows' not in response:
                    break

                # 動画詳細を取得
                video_ids = [row[0] for row in response['rows']]
                video_details = self._get_video_details(video_ids)

                for row in response['rows']:
                    video_id = row[0]
                    video_detail = video_details.get(video_id, {})

                    video_data = {
                        'video_id': video_id,
                        'title': video_detail.get('title', 'Unknown'),
                        'published_at': video_detail.get('published_at'),
                        'description': (
                            video_detail.get('description', '')[:100] + '...'
                            if len(video_detail.get('description', '')) > 100
                            else video_detail.get('description', '')
                        ),
                        'views': row[1],
                        'estimated_minutes_watched': row[2],
                        'average_view_duration': row[3],
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'is_recent': video_id in recent_video_ids
                    }
                    top_videos_data.append(video_data)

                remaining_count -= len(response['rows'])

                if len(response['rows']) < batch_size:
                    break

            except Exception as e:
                print(f"  ❌ 上位動画取得エラー: {e}")
                break

        # Step 4: 直近動画のAnalytics取得（上位に含まれていないもののみ）
        print("📊 直近投稿動画のAnalytics取得中...")
        top_video_ids = {video['video_id'] for video in top_videos_data}

        recent_videos_data = []
        for video in recent_videos_info:
            if video['video_id'] not in top_video_ids:
                analytics_data = self.get_video_analytics_by_id(
                    video['video_id'], start_date, end_date
                )

                combined_data = {
                    **video,
                    **analytics_data,
                    'is_recent': True
                }
                recent_videos_data.append(combined_data)

        # 再生回数で降順ソート
        recent_videos_data.sort(key=lambda x: x.get('views', 0), reverse=True)

        # 結果
        result = {
            'top_videos': top_videos_data,
            'recent_videos': recent_videos_data,
            'statistics': {
                'top_videos_count': len(top_videos_data),
                'recent_videos_count': len(recent_videos_data),
                'recent_in_top': len([v for v in top_videos_data if v.get('is_recent')]),
                'unique_recent_videos': len(recent_videos_data),
                'total_analyzed': len(top_videos_data) + len(recent_videos_data)
            }
        }

        print("✅ 統合Analytics取得完了:")
        print(f"  🏆 上位動画: {len(top_videos_data)}本")
        print(f"  📅 直近動画（上位外）: {len(recent_videos_data)}本")
        print(f"  🔄 直近動画（上位内）: {result['statistics']['recent_in_top']}本")
        print(f"  📊 総計: {result['statistics']['total_analyzed']}本")

        return result

    def get_strategic_video_analytics(self, start_date: str, end_date: str, mode: str = "efficient") -> Dict:
        """
        戦略的動画分析データ取得（モード選択可能）

        Args:
            start_date (str): 分析開始日
            end_date (str): 分析終了日
            mode (str): 取得モード
                - "efficient": 上位50本 + 直近30日投稿（推奨）
                - "comprehensive": 全動画
                - "top_only": 上位50本のみ
                - "recent_only": 直近30日投稿のみ

        Returns:
            Dict: 分析データ
        """
        print(f"🎯 戦略的動画分析データ取得開始 (モード: {mode})")

        result = {
            'mode': mode,
            'period': f"{start_date} to {end_date}",
            'top_videos': [],
            'recent_videos': [],
            'all_videos': []
        }

        if mode == "efficient":
            print("📊 効率モード: 上位50本 + 直近30日投稿（統合取得）")
            combined_data = self.get_combined_analytics(start_date, end_date, 50, 30)
            result['top_videos'] = combined_data['top_videos']
            result['recent_videos'] = combined_data['recent_videos']

        elif mode == "comprehensive":
            print("🔍 包括モード: 全動画")
            result['all_videos'] = self.get_all_video_analytics(start_date, end_date)

        elif mode == "top_only":
            print("🏆 上位のみモード: 上位50本")
            result['top_videos'] = self.get_top_video_analytics(start_date, end_date, 50)

        elif mode == "recent_only":
            print("📅 直近のみモード: 直近30日投稿")
            result['recent_videos'] = self.get_recent_video_analytics(start_date, end_date, 30)

        else:
            print(f"❌ 不明なモード: {mode}")
            print("利用可能なモード: efficient, comprehensive, top_only, recent_only")
            return result

        # 統計情報を追加
        total_videos = len(result['top_videos']) + len(result['recent_videos']) + len(result['all_videos'])
        result['summary'] = {
            'total_videos_analyzed': total_videos,
            'top_videos_count': len(result['top_videos']),
            'recent_videos_count': len(result['recent_videos']),
            'all_videos_count': len(result['all_videos'])
        }

        print(f"✅ 戦略的分析データ取得完了: 総計{total_videos}本")
        return result

    def _get_video_details(self, video_ids: List[str]) -> Dict:
        """動画詳細情報取得"""
        if not video_ids:
            return {}

        try:
            # 50個ずつ分割して処理（API制限対応）
            all_details = {}

            for i in range(0, len(video_ids), 50):
                batch_ids = video_ids[i:i+50]

                response = self.youtube_service.videos().list(
                    part='snippet,statistics',
                    id=','.join(batch_ids)
                ).execute()

                for item in response.get('items', []):
                    video_id = item['id']
                    snippet = item['snippet']

                    all_details[video_id] = {
                        'title': snippet['title'],
                        'published_at': snippet['publishedAt'],
                        'description': snippet.get('description', ''),
                        'tags': snippet.get('tags', [])
                    }

            return all_details

        except Exception as e:
            print(f"⚠️  動画詳細取得エラー: {e}")
            return {}

    def _classify_video_type(self, title: str) -> str:
        """動画タイプ分類（Complete Collection vs Individual Track）"""
        title_lower = title.lower()

        if any(keyword in title_lower for keyword in ['tracks', 'collection', 'full', 'complete']):
            return 'Complete Collection'
        else:
            return 'Individual Track'

    def _calculate_engagement_rate(self, row: list) -> float:
        """エンゲージメント率計算"""
        try:
            views = row[1]
            likes = row[4]
            comments = row[6]
            shares = row[7]

            if views > 0:
                return ((likes + comments + shares) / views) * 100
            else:
                return 0.0
        except Exception:
            return 0.0
