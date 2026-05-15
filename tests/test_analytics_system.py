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
from googleapiclient.errors import HttpError

# `patch("youtube_automation.scripts.analytics_system.X")` がモジュール属性として
# 解決できるよう、トップレベルで submodule を import しておく。
import youtube_automation.scripts.analytics_system  # noqa: F401
from youtube_automation.utils.exceptions import AuthError, YouTubeAPIError

# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    """load_config() をモック化"""
    config = MagicMock()
    config.meta.channel_name = "Test Channel"
    config.meta.channel_short = "TC"
    return config


@pytest.fixture
def system(mock_config):
    """AnalyticsSystem インスタンスを返す（外部依存をモック）"""
    with (
        patch("youtube_automation.scripts.analytics_system.load_config", return_value=mock_config),
        patch("youtube_automation.scripts.analytics_system.channel_dir", return_value=Path("/tmp/fake_channel")),
        patch("youtube_automation.scripts.analytics_system.YouTubeAnalyticsCollector") as MockCollector,
    ):
        instance = MagicMock()
        MockCollector.return_value = instance

        from youtube_automation.scripts.analytics_system import AnalyticsSystem

        obj = AnalyticsSystem()
        obj._mock_collector_instance = instance
        yield obj


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_creates_collector(self, mock_config):
        """__init__ が YouTubeAnalyticsCollector を生成する"""
        with (
            patch("youtube_automation.scripts.analytics_system.load_config", return_value=mock_config),
            patch("youtube_automation.scripts.analytics_system.YouTubeAnalyticsCollector") as MockCollector,
        ):
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

        with patch.dict(
            "sys.modules",
            {
                "youtube_automation.auth": MagicMock(),
                "youtube_automation.auth.oauth_handler": mock_oauth_module,
            },
        ):
            result = system.authenticate()
            assert result is True
            assert system.authenticated is True

    def test_authenticate_failure_connection_test(self, system):
        """接続テスト失敗時に False を返す"""
        mock_handler = MagicMock()
        mock_handler.test_connection.return_value = False

        oauth_module = MagicMock(YouTubeOAuthHandler=MagicMock(return_value=mock_handler))
        with patch.dict(
            "sys.modules",
            {
                "youtube_automation.auth": MagicMock(),
                "youtube_automation.auth.oauth_handler": oauth_module,
            },
        ):
            result = system.authenticate()
            assert result is False
            assert system.authenticated is False

    def test_authenticate_exception(self, system):
        """認証中にドメイン例外（AuthError）が発生した場合 False を返す"""
        with patch.dict(
            "sys.modules",
            {
                "youtube_automation.auth": MagicMock(),
                "youtube_automation.auth.oauth_handler": MagicMock(
                    YouTubeOAuthHandler=MagicMock(side_effect=AuthError("Token expired"))
                ),
            },
        ):
            result = system.authenticate()
            assert result is False

    def test_authenticate_unexpected_exception_propagates(self, system):
        """narrow catch 範囲外の例外は伝播する（fail-fast）"""
        with patch.dict(
            "sys.modules",
            {
                "youtube_automation.auth": MagicMock(),
                "youtube_automation.auth.oauth_handler": MagicMock(
                    YouTubeOAuthHandler=MagicMock(side_effect=RuntimeError("unexpected"))
                ),
            },
        ):
            with pytest.raises(RuntimeError, match="unexpected"):
                system.authenticate()


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
        expected_data = {"views": 1000, "subscribers": 50}
        system.collector.collect_basic_analytics.return_value = expected_data
        system.collector.get_all_channel_videos.return_value = [{"video_id": "vid_A"}]
        system.collector.get_video_daily_analytics.return_value = [
            {"video_id": "vid_A", "date": "2026-04-01", "views": 100}
        ]

        with patch("youtube_automation.scripts.analytics_system.channel_dir", return_value=tmp_path):
            result = system.collect_analytics_data(days=7, save_data=True)

        assert result == expected_data
        # data ディレクトリにファイルが保存されたことを確認
        saved_files = list((tmp_path / "data").glob("analytics_data_*.json"))
        assert len(saved_files) == 1

        # 動画×日次データが impressions フィールド無しで保存されていること
        daily_files = list((tmp_path / "data" / "analytics" / "daily_per_video").glob("*.json"))
        assert len(daily_files) == 1
        import json

        with open(daily_files[0], encoding="utf-8") as f:
            daily_payload = json.load(f)
        assert daily_payload["rows"][0] == {
            "video_id": "vid_A",
            "date": "2026-04-01",
            "views": 100,
        }
        assert "impressions" not in daily_payload["rows"][0]
        assert "impression_ctr" not in daily_payload["rows"][0]

    def test_success_without_save(self, system):
        """認証済みでデータ保存なしの場合"""
        system.authenticated = True
        expected_data = {"views": 500}
        system.collector.collect_basic_analytics.return_value = expected_data

        result = system.collect_analytics_data(days=14, save_data=False)
        assert result == expected_data

    def test_collector_domain_exception(self, system):
        """ドメイン例外（YouTubeAPIError）発生時に None を返す"""
        system.authenticated = True
        system.collector.collect_basic_analytics.side_effect = YouTubeAPIError("API quota exceeded")

        result = system.collect_analytics_data(days=30)
        assert result is None

    def test_collector_unexpected_exception_propagates(self, system):
        """narrow catch 範囲外の例外は伝播する（fail-fast）"""
        system.authenticated = True
        system.collector.collect_basic_analytics.side_effect = RuntimeError("unexpected")

        with pytest.raises(RuntimeError, match="unexpected"):
            system.collect_analytics_data(days=30)

    def test_video_daily_failure_continues(self, system, tmp_path):
        """動画×日次データ取得失敗時は warning ログ + 続行（analytics_data は返す）"""
        system.authenticated = True
        expected_data = {"views": 1000}
        system.collector.collect_basic_analytics.return_value = expected_data
        # 動画一覧取得は成功、日次取得で KeyError（データ整合性エラー）
        system.collector.get_all_channel_videos.return_value = [{"video_id": "vid_A"}]
        system.collector.get_video_daily_analytics.side_effect = KeyError("missing field")

        with patch("youtube_automation.scripts.analytics_system.channel_dir", return_value=tmp_path):
            result = system.collect_analytics_data(days=7, save_data=True)

        # 失敗しても analytics_data 本体は返る（fail-open）
        assert result == expected_data
        # 動画×日次ファイルは保存されていない
        daily_files = list((tmp_path / "data" / "analytics" / "daily_per_video").glob("*.json"))
        assert len(daily_files) == 0

    def test_video_daily_httperror_continues(self, system, tmp_path):
        """動画×日次データ取得で HttpError 発生時は warning + 続行（fail-open）。

        HttpError 専用分岐（`YouTubeAPIError.from_http_error` ラップ + warning + 続行）の検証。
        """
        system.authenticated = True
        expected_data = {"views": 1000}
        system.collector.collect_basic_analytics.return_value = expected_data
        system.collector.get_all_channel_videos.return_value = [{"video_id": "vid_A"}]
        # 内側ブロックで HttpError 発生 → 専用 catch で warning + 続行
        system.collector.get_video_daily_analytics.side_effect = HttpError(
            MagicMock(status=403), b"quotaExceeded"
        )

        with patch("youtube_automation.scripts.analytics_system.channel_dir", return_value=tmp_path):
            result = system.collect_analytics_data(days=7, save_data=True)

        # fail-open: analytics_data 本体は返る
        assert result == expected_data
        # 動画×日次ファイルは保存されていない
        daily_files = list((tmp_path / "data" / "analytics" / "daily_per_video").glob("*.json"))
        assert len(daily_files) == 0

    def test_collector_httperror_returns_none(self, system):
        """外周 HttpError 発生時は None を返す（fail-stop）。

        外周 HttpError 専用分岐（`YouTubeAPIError.from_http_error` ラップ + logger.exception + None 返却）の検証。
        """
        system.authenticated = True
        system.collector.collect_basic_analytics.side_effect = HttpError(
            MagicMock(status=500), b"internalError"
        )

        result = system.collect_analytics_data(days=30)
        # fail-stop: None が返る
        assert result is None


# ---------------------------------------------------------------------------
# run_data_collection
# ---------------------------------------------------------------------------


class TestRunDataCollection:
    def test_full_success(self, system, mock_config):
        """認証 → データ収集 → 成功の完全パス"""
        with patch("youtube_automation.scripts.analytics_system.load_config", return_value=mock_config):
            expected_data = {"views": 2000}
            with (
                patch.object(system, "authenticate", return_value=True),
                patch.object(system, "collect_analytics_data", return_value=expected_data),
            ):
                result = system.run_data_collection(days=30)

        assert result["success"] is True
        assert result["analytics_data"] == expected_data

    def test_auth_failure(self, system, mock_config):
        """認証失敗時のパス"""
        with patch("youtube_automation.scripts.analytics_system.load_config", return_value=mock_config):
            with patch.object(system, "authenticate", return_value=False):
                result = system.run_data_collection(days=30)

        assert result["success"] is False
        assert result["error"] == "Authentication failed"

    def test_data_collection_returns_none(self, system, mock_config):
        """データ収集が None を返した場合"""
        with patch("youtube_automation.scripts.analytics_system.load_config", return_value=mock_config):
            with (
                patch.object(system, "authenticate", return_value=True),
                patch.object(system, "collect_analytics_data", return_value=None),
            ):
                result = system.run_data_collection(days=30)

        assert result["success"] is False
        assert "error" in result

    def test_data_collection_exception_propagates(self, system, mock_config):
        """collect_analytics_data からの例外は run_data_collection で握りつぶさず伝播する"""
        with patch("youtube_automation.scripts.analytics_system.load_config", return_value=mock_config):
            with (
                patch.object(system, "authenticate", return_value=True),
                patch.object(system, "collect_analytics_data", side_effect=RuntimeError("Network error")),
            ):
                with pytest.raises(RuntimeError, match="Network error"):
                    system.run_data_collection(days=30)
