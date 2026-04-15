"""
VideoAnalyticsMixin のユニットテスト

テスト対象: utils/video_analytics.py
metrics パラメータと row マッピングの整合性を検証する。
"""

from unittest.mock import MagicMock

import pytest

from youtube_automation.utils.channel_config import ChannelConfig
from youtube_automation.utils.video_analytics import VideoAnalyticsMixin


@pytest.fixture(autouse=True)
def reset_singletons():
    ChannelConfig.reset()
    yield
    ChannelConfig.reset()


class StubCollector(VideoAnalyticsMixin):
    """テスト用スタブ"""

    def __init__(self):
        self.analytics_service = MagicMock()
        self.youtube_service = MagicMock()
        self.channel_id = 'UC_TEST'

    def initialize(self):
        pass


@pytest.fixture
def collector():
    return StubCollector()


class TestGetVideoAnalytics:
    def test_row_mapping_with_full_metrics(self, collector):
        """metrics 8個 + video_id でインデックス [0]-[8] が正しくマッピングされる"""
        mock_response = {
            'rows': [
                # video_id, views, watchTime, avgDuration, likes, dislikes, comments, shares, subsGained
                ['VID_001', 1000, 500, 300, 50, 2, 10, 5, 3],
            ]
        }
        collector.analytics_service.reports().query().execute.return_value = mock_response

        # _get_video_details をモック
        collector.youtube_service.videos().list().execute.return_value = {
            'items': [{
                'id': 'VID_001',
                'snippet': {
                    'title': 'Test Video',
                    'publishedAt': '2026-01-01T00:00:00Z',
                    'description': 'test',
                    'tags': [],
                },
                'contentDetails': {
                    'duration': 'PT1H',
                    'definition': 'hd',
                    'dimension': '2d',
                    'caption': 'false',
                },
                'topicDetails': {
                    'topicCategories': ['https://en.wikipedia.org/wiki/Music'],
                },
            }]
        }

        result = collector.get_video_analytics('2026-01-01', '2026-04-01')

        assert len(result) == 1
        video = result[0]
        assert video['video_id'] == 'VID_001'
        assert video['views'] == 1000
        assert video['watch_time_minutes'] == 500
        assert video['average_view_duration'] == 300
        assert video['likes'] == 50
        assert video['dislikes'] == 2
        assert video['comments'] == 10
        assert video['shares'] == 5
        assert video['subscribers_gained'] == 3

    def test_engagement_rate_calculation(self, collector):
        """エンゲージメント率: (likes + comments + shares) / views * 100"""
        mock_response = {
            'rows': [
                ['VID_001', 1000, 500, 300, 50, 2, 10, 5, 3],
            ]
        }
        collector.analytics_service.reports().query().execute.return_value = mock_response
        collector.youtube_service.videos().list().execute.return_value = {
            'items': [{
                'id': 'VID_001',
                'snippet': {'title': 'Test', 'publishedAt': '2026-01-01T00:00:00Z'},
                'contentDetails': {},
                'topicDetails': {},
            }]
        }

        result = collector.get_video_analytics('2026-01-01', '2026-04-01')
        # (50 + 10 + 5) / 1000 * 100 = 6.5
        assert result[0]['engagement_rate'] == pytest.approx(6.5)


class TestGetVideoAnalyticsById:
    def test_returns_all_metrics(self, collector):
        """get_video_analytics_by_id が拡張メトリクスを返す"""
        mock_response = {
            'rows': [[100, 50, 300, 10, 1, 3, 2, 1]]
        }
        collector.analytics_service.reports().query().execute.return_value = mock_response

        result = collector.get_video_analytics_by_id('VID_001', '2026-01-01', '2026-04-01')

        assert result['views'] == 100
        assert result['likes'] == 10
        assert result['comments'] == 3
        assert result['shares'] == 2
        assert result['subscribers_gained'] == 1

    def test_empty_response_returns_zeros(self, collector):
        """データなしの場合、全メトリクスが 0"""
        collector.analytics_service.reports().query().execute.return_value = {'rows': []}

        result = collector.get_video_analytics_by_id('VID_EMPTY', '2026-01-01', '2026-04-01')

        assert result['views'] == 0
        assert result['likes'] == 0
        assert result['subscribers_gained'] == 0


class TestGetVideoDetails:
    def test_includes_content_details(self, collector):
        """_get_video_details が contentDetails/topicDetails を含む"""
        collector.youtube_service.videos().list().execute.return_value = {
            'items': [{
                'id': 'VID_001',
                'snippet': {
                    'title': 'Test Video',
                    'publishedAt': '2026-01-01T00:00:00Z',
                    'description': 'desc',
                    'tags': ['music'],
                },
                'contentDetails': {
                    'duration': 'PT1H23M45S',
                    'definition': 'hd',
                    'dimension': '2d',
                    'caption': 'true',
                },
                'topicDetails': {
                    'topicCategories': ['https://en.wikipedia.org/wiki/Music'],
                },
            }]
        }

        result = collector._get_video_details(['VID_001'])

        assert result['VID_001']['duration'] == 'PT1H23M45S'
        assert result['VID_001']['definition'] == 'hd'
        assert result['VID_001']['caption'] == 'true'
        assert len(result['VID_001']['topic_categories']) == 1
