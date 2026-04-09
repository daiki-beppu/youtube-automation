"""
AnalyticsSystem のユニットテスト

テスト対象: scripts/analytics_system.py
YouTube Analytics API 呼び出しとファイル I/O を unittest.mock でモック化して検証する。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from youtube_automation.utils.channel_config import ChannelConfig

# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singletons():
    ChannelConfig.reset()
    yield
    ChannelConfig.reset()


@pytest.fixture
def mock_config():
    """ChannelConfig.load() をモック化"""
    config = MagicMock()
    config.channel_name = 'Test Channel'
    config.channel_short = 'TC'
    return config


@pytest.fixture
def system(mock_config):
    """AnalyticsSystem インスタンスを返す（外部依存をモック）"""
    with patch('youtube_automation.scripts.analytics_system.ChannelConfig') as MockCC, \
         patch('youtube_automation.scripts.analytics_system.YouTubeAnalyticsCollector') as MockCollector:
        MockCC.load.return_value = mock_config
        MockCC.channel_dir.return_value = Path('/tmp/fake_channel')
        instance = MagicMock()
        MockCollector.return_value = instance

        from youtube_automation.scripts.analytics_system import AnalyticsSystem
        obj = AnalyticsSystem()
        obj._mock_collector_instance = instance
        obj._MockCC = MockCC
        yield obj


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_init_creates_collector(self, mock_config):
        """__init__ が YouTubeAnalyticsCollector を生成する"""
        with patch('youtube_automation.scripts.analytics_system.ChannelConfig') as MockCC, \
             patch('youtube_automation.scripts.analytics_system.YouTubeAnalyticsCollector') as MockCollector:
            MockCC.load.return_value = mock_config
            from youtube_automation.scripts.analytics_system import AnalyticsSystem
            obj = AnalyticsSystem()
            MockCollector.assert_called_once()
            assert obj.collector is not None

    def test_init_not_authenticated(self, system):
        """初期状態は未認証"""
        assert system.authenticated is False


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------

class TestAuthenticate:
    def test_authenticate_success(self, system):
        """認証成功時に True を返し authenticated を True にする"""
        mock_handler = MagicMock()
        mock_handler.test_connection.return_value = True

        mock_oauth_module = MagicMock()
        mock_oauth_module.YouTubeOAuthHandler.return_value = mock_handler

        with patch.dict('sys.modules', {
            'youtube_automation.auth': MagicMock(),
            'youtube_automation.auth.oauth_handler': mock_oauth_module,
        }):
            result = system.authenticate()
            assert result is True
            assert system.authenticated is True

    def test_authenticate_failure_connection_test(self, system):
        """接続テスト失敗時に False を返す"""
        mock_handler = MagicMock()
        mock_handler.test_connection.return_value = False

        oauth_module = MagicMock(YouTubeOAuthHandler=MagicMock(return_value=mock_handler))
        with patch.dict('sys.modules', {
            'youtube_automation.auth': MagicMock(),
            'youtube_automation.auth.oauth_handler': oauth_module,
        }):
            result = system.authenticate()
            assert result is False
            assert system.authenticated is False

    def test_authenticate_exception(self, system):
        """認証中に例外が発生した場合 False を返す"""
        with patch.dict('sys.modules', {
            'youtube_automation.auth': MagicMock(),
            'youtube_automation.auth.oauth_handler': MagicMock(
                YouTubeOAuthHandler=MagicMock(side_effect=Exception('Token expired'))
            ),
        }):
            result = system.authenticate()
            assert result is False


# ---------------------------------------------------------------------------
# collect_analytics_data
# ---------------------------------------------------------------------------

class TestCollectAnalyticsData:
    def test_not_authenticated(self, system):
        """未認証時に None を返す"""
        system.authenticated = False
        result = system.collect_analytics_data()
        assert result is None

    def test_success_with_save(self, system, tmp_path):
        """認証済みでデータ保存ありの場合"""
        system.authenticated = True
        expected_data = {'views': 1000, 'subscribers': 50}
        system.collector.collect_basic_analytics.return_value = expected_data

        with patch('youtube_automation.scripts.analytics_system.ChannelConfig') as MockCC:
            MockCC.channel_dir.return_value = tmp_path

            result = system.collect_analytics_data(days=7, save_data=True)

        assert result == expected_data
        # data ディレクトリにファイルが保存されたことを確認
        saved_files = list((tmp_path / 'data').glob('analytics_data_*.json'))
        assert len(saved_files) == 1

    def test_success_without_save(self, system):
        """認証済みでデータ保存なしの場合"""
        system.authenticated = True
        expected_data = {'views': 500}
        system.collector.collect_basic_analytics.return_value = expected_data

        result = system.collect_analytics_data(days=14, save_data=False)
        assert result == expected_data

    def test_collector_exception(self, system):
        """コレクター例外時に None を返す"""
        system.authenticated = True
        system.collector.collect_basic_analytics.side_effect = Exception('API quota exceeded')

        result = system.collect_analytics_data(days=30)
        assert result is None


# ---------------------------------------------------------------------------
# run_data_collection
# ---------------------------------------------------------------------------

class TestRunDataCollection:
    def test_full_success(self, system, mock_config):
        """認証 → データ収集 → 成功の完全パス"""
        with patch('youtube_automation.scripts.analytics_system.ChannelConfig') as MockCC:
            MockCC.load.return_value = mock_config

            expected_data = {'views': 2000}
            with patch.object(system, 'authenticate', return_value=True), \
                 patch.object(system, 'collect_analytics_data', return_value=expected_data):
                result = system.run_data_collection(days=30)

        assert result['success'] is True
        assert result['analytics_data'] == expected_data

    def test_auth_failure(self, system, mock_config):
        """認証失敗時のパス"""
        with patch('youtube_automation.scripts.analytics_system.ChannelConfig') as MockCC:
            MockCC.load.return_value = mock_config

            with patch.object(system, 'authenticate', return_value=False):
                result = system.run_data_collection(days=30)

        assert result['success'] is False
        assert result['error'] == 'Authentication failed'

    def test_data_collection_returns_none(self, system, mock_config):
        """データ収集が None を返した場合"""
        with patch('youtube_automation.scripts.analytics_system.ChannelConfig') as MockCC:
            MockCC.load.return_value = mock_config

            with patch.object(system, 'authenticate', return_value=True), \
                 patch.object(system, 'collect_analytics_data', return_value=None):
                result = system.run_data_collection(days=30)

        assert result['success'] is False
        assert 'error' in result

    def test_data_collection_exception(self, system, mock_config):
        """データ収集中に例外が発生した場合"""
        with patch('youtube_automation.scripts.analytics_system.ChannelConfig') as MockCC:
            MockCC.load.return_value = mock_config

            with patch.object(system, 'authenticate', return_value=True), \
                 patch.object(system, 'collect_analytics_data', side_effect=Exception('Network error')):
                result = system.run_data_collection(days=30)

        assert result['success'] is False
        assert 'error' in result
