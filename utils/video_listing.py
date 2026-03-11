"""
動画一覧取得 Mixin
YouTubeAnalyticsCollector のチャンネル動画リスト取得メソッド群
"""

from datetime import datetime, timedelta
from typing import Dict, List


class VideoListingMixin:
    """動画一覧取得の Mixin"""

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
