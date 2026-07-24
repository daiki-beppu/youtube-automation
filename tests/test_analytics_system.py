"""
AnalyticsSystem のユニットテスト

テスト対象: scripts/analytics_system.py
YouTube Analytics API 呼び出しとファイル I/O を unittest.mock でモック化して検証する。
"""

import json
import sys
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from googleapiclient.errors import HttpError

# `patch("youtube_automation.scripts.analytics_system.X")` がモジュール属性として
# 解決できるよう、トップレベルで submodule を import しておく。
import youtube_automation.scripts.analytics_system  # noqa: F401
from youtube_automation.infrastructure.errors import AuthError, YouTubeAPIError
from youtube_automation.utils.analytics_collector import YouTubeAnalyticsCollector

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


@pytest.fixture
def stub_analytics_boundaries(monkeypatch, tmp_path):
    """CLI 実経路を残したまま OAuth / YouTube API 境界だけを固定する。"""
    from youtube_automation.scripts import analytics_system
    from youtube_automation.utils.analytics_collector import YouTubeAnalyticsCollector

    def authenticate(system):
        system.authenticated = True
        return True

    monkeypatch.setattr(analytics_system, "channel_dir", lambda: tmp_path)
    monkeypatch.setattr(analytics_system.AnalyticsSystem, "authenticate", authenticate)
    monkeypatch.setattr(YouTubeAnalyticsCollector, "initialize", lambda self: None)
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_channel_analytics",
        lambda self, start, end: {"period": f"{start} to {end}", "daily_metrics": []},
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_strategic_video_analytics",
        lambda self, start, end, mode="efficient": {
            "mode": mode,
            "top_videos": [],
            "recent_videos": [],
            "summary": {},
        },
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_revenue_analytics",
        lambda self, start, end: {
            "status": "available",
            "daily_metrics": [],
            "by_video": {},
            "summary": {"estimated_revenue": 0, "views": 0, "rpm": 0.0},
        },
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_ctr_analysis",
        lambda self, start, end: {"videos": []},
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_traffic_source_analytics",
        lambda self, start, end: {"sources": {}},
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_traffic_source_detail",
        lambda self, start, end, source_type: [{"detail": "lofi music", "views": 30, "watch_time_minutes": 90}],
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_playlist_analytics",
        lambda self, start, end: {
            "playlists": {
                "PL_COMPLETE": {
                    "views": 300,
                    "average_view_duration": 120,
                    "view_share_percent": 100.0,
                }
            },
            "total_views": 300,
        },
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_device_analytics",
        lambda self, start, end: {"devices": {"TV": {"views": 25}}},
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_subscribed_status_analytics",
        lambda self, start, end: {
            "statuses": {
                "SUBSCRIBED": {"views": 10, "view_share_percent": 25.0},
                "UNSUBSCRIBED": {"views": 30, "view_share_percent": 75.0},
            },
            "total_views": 40,
        },
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_country_analytics",
        lambda self, start, end: {"countries": {"JP": {"views": 20}}},
    )
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_retention_summary",
        lambda self, start, end, top_n: [{"video_id": "VID_1", "average_retention": 0.62}],
    )
    monkeypatch.setattr(YouTubeAnalyticsCollector, "get_all_channel_videos", lambda self: [])
    monkeypatch.setattr(
        YouTubeAnalyticsCollector,
        "get_video_daily_analytics",
        lambda self, start, end, video_ids: [],
    )
    return tmp_path


def _collector_with_playlist_response(response):
    """playlist Mixin だけを実行し、他の収集 API はテスト境界で置き換える。"""
    collector = YouTubeAnalyticsCollector()
    collector.analytics_service = MagicMock()
    collector.channel_id = "UC_TEST"
    collector.initialize = MagicMock()
    collector.get_channel_analytics = MagicMock(return_value={"summary": {}})
    collector.get_strategic_video_analytics = MagicMock(
        return_value={"top_videos": [], "recent_videos": [], "mode": "efficient", "summary": {}}
    )
    collector.get_revenue_analytics = MagicMock(
        return_value={"status": "available", "daily_metrics": [], "by_video": {}, "summary": {}}
    )
    collector.get_subscribed_status_analytics = MagicMock(return_value={"statuses": {}, "total_views": 0})
    collector._build_publish_at_map = MagicMock(return_value={})
    collector.get_ctr_analysis = MagicMock(return_value={})
    collector.get_traffic_source_analytics = MagicMock(return_value={})
    collector.get_traffic_source_detail = MagicMock(return_value=[])
    collector.get_device_analytics = MagicMock(return_value={})
    collector.get_all_channel_videos = MagicMock(return_value=[])
    collector.get_video_daily_analytics = MagicMock(return_value=[])
    collector.analytics_service.reports().query().execute.return_value = response
    collector.analytics_service.reports().query.reset_mock()
    return collector


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
    """authenticate() は instance-owned OAuth handler を利用する。"""

    def test_authenticate_success(self, system):
        """認証成功時に True を返し authenticated を True にする"""
        mock_handler = MagicMock()
        mock_handler.test_connection.return_value = True

        with patch("youtube_automation.scripts.analytics_system.YouTubeOAuthHandler") as MockHandler:
            MockHandler.create_readonly.return_value = mock_handler
            result = system.authenticate()
            assert result is True
            assert system.authenticated is True
            MockHandler.create_readonly.assert_called_once_with()
            mock_handler.authenticate.assert_called_once_with(force_reauth=False)

    def test_authenticate_failure_connection_test(self, system):
        """接続テスト失敗時に False を返す"""
        mock_handler = MagicMock()
        mock_handler.test_connection.return_value = False

        with patch("youtube_automation.scripts.analytics_system.YouTubeOAuthHandler") as MockHandler:
            MockHandler.create_readonly.return_value = mock_handler
            result = system.authenticate()
            assert result is False
            assert system.authenticated is False
            MockHandler.create_readonly.assert_called_once_with()

    def test_authenticate_exception(self, system):
        """認証中にドメイン例外（AuthError）が発生した場合 False を返す"""
        with patch("youtube_automation.scripts.analytics_system.YouTubeOAuthHandler") as MockHandler:
            MockHandler.create_readonly.side_effect = AuthError("Token expired")
            result = system.authenticate()
            assert result is False

    def test_authenticate_unexpected_exception_propagates(self, system):
        """narrow catch 範囲外の例外は伝播する（fail-fast）"""
        with patch("youtube_automation.scripts.analytics_system.YouTubeOAuthHandler") as MockHandler:
            MockHandler.create_readonly.side_effect = RuntimeError("unexpected")
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
        expected_data = {
            "views": 1000,
            "subscribers": 50,
            "audience": {
                "by_subscribed_status": {
                    "statuses": {"UNSUBSCRIBED": {"views": 750, "view_share_percent": 75.0}},
                    "total_views": 1000,
                }
            },
            "playlist_analytics": {
                "playlists": {"PL_COMPLETE": {"views": 300, "average_view_duration": 120}},
                "total_views": 300,
            },
        }
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

        import json

        with open(saved_files[0], encoding="utf-8") as f:
            saved_payload = json.load(f)
        assert saved_payload["playlist_analytics"] == expected_data["playlist_analytics"]

        # 動画×日次データが impressions フィールド無しで保存されていること
        daily_files = list((tmp_path / "data" / "analytics" / "daily_per_video").glob("*.json"))
        assert len(daily_files) == 1
        with open(daily_files[0], encoding="utf-8") as f:
            daily_payload = json.load(f)
        assert daily_payload["rows"][0] == {
            "video_id": "vid_A",
            "date": "2026-04-01",
            "views": 100,
        }
        assert "impressions" not in daily_payload["rows"][0]
        assert "impression_ctr" not in daily_payload["rows"][0]

        with open(saved_files[0], encoding="utf-8") as f:
            analytics_payload = json.load(f)
        assert (
            analytics_payload["audience"]["by_subscribed_status"] == expected_data["audience"]["by_subscribed_status"]
        )

    def test_public_collection_path_saves_playlist_api_response(self, system, tmp_path):
        """AnalyticsSystem → collector → playlist API → JSON 保存を実行する。"""
        system.authenticated = True
        system.collector = _collector_with_playlist_response({"rows": [["PL_COMPLETE", 300, 120]]})

        with patch("youtube_automation.scripts.analytics_system.channel_dir", return_value=tmp_path):
            result = system.collect_analytics_data(days=7, save_data=True)

        assert result["playlist_analytics"] == {
            "playlists": {
                "PL_COMPLETE": {
                    "views": 300,
                    "average_view_duration": 120,
                    "view_share_percent": 100.0,
                }
            },
            "total_views": 300,
        }
        saved_file = next((tmp_path / "data").glob("analytics_data_*.json"))
        import json

        with open(saved_file, encoding="utf-8") as file:
            assert json.load(file)["playlist_analytics"] == result["playlist_analytics"]

    def test_success_without_save(self, system):
        """認証済みでデータ保存なしの場合"""
        system.authenticated = True
        expected_data = {"views": 500}
        system.collector.collect_basic_analytics.return_value = expected_data

        result = system.collect_analytics_data(days=14, save_data=False)
        assert result == expected_data

    def test_include_reporting_keeps_csv_summary_in_analytics_data(self, system):
        """--include-reporting 相当の経路は Reporting API 集計結果を保持する."""
        system.authenticated = True
        system.collector.collect_basic_analytics.return_value = {"views": 500}
        summary = {"aggregated_impressions": 1200, "aggregated_ctr_percentage": 4.2}
        system.collector.get_reporting_impressions_summary.return_value = summary

        result = system.collect_analytics_data(days=14, save_data=False, include_reporting=True)

        assert result["reporting_api"] == {"impressions_summary": summary}
        system.collector.get_reporting_impressions_summary.assert_called_once_with(days=14)

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
        system.collector.get_video_daily_analytics.side_effect = HttpError(MagicMock(status=403), b"quotaExceeded")

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
        system.collector.collect_basic_analytics.side_effect = HttpError(MagicMock(status=500), b"internalError")

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


class TestMainDepth:
    def test_full_depth_persists_retention_and_country(self, monkeypatch, stub_analytics_boundaries):
        """--depth full は full 専用データを最終 JSON まで貫通させる。"""
        from youtube_automation.scripts import analytics_system

        monkeypatch.setattr(sys, "argv", ["yt-analytics", "--depth", "full"])

        with pytest.raises(SystemExit) as exit_info:
            analytics_system.main()

        assert exit_info.value.code == 0
        saved_files = list((stub_analytics_boundaries / "data").glob("analytics_data_*.json"))
        assert len(saved_files) == 1
        payload = json.loads(saved_files[0].read_text(encoding="utf-8"))
        assert payload["collection_depth"] == "full"
        assert payload["audience"]["by_country"] == {"countries": {"JP": {"views": 20}}}
        assert payload["retention"] == [{"video_id": "VID_1", "average_retention": 0.62}]
        assert payload["playlist_analytics"]["playlists"]["PL_COMPLETE"]["views"] == 300

    def test_full_depth_country_api_error_fails_without_persisting(self, monkeypatch, stub_analytics_boundaries):
        """full の地域 API 失敗は CLI 成功や不完全 JSON に変換しない。"""
        from youtube_automation.scripts import analytics_system
        from youtube_automation.utils.analytics_collector import YouTubeAnalyticsCollector

        monkeypatch.setattr(sys, "argv", ["yt-analytics", "--depth", "full"])
        monkeypatch.setattr(
            YouTubeAnalyticsCollector,
            "get_country_analytics",
            lambda self, start, end: {"countries": {}, "error": "country API failed"},
        )

        with pytest.raises(SystemExit) as exit_info:
            analytics_system.main()

        assert exit_info.value.code == 1
        assert not list((stub_analytics_boundaries / "data").glob("analytics_data_*.json"))

    def test_full_depth_retention_api_error_fails_without_persisting(self, monkeypatch, stub_analytics_boundaries):
        """full の動画別 retention API 失敗は不完全 JSON を保存しない。"""
        from youtube_automation.scripts import analytics_system
        from youtube_automation.utils.analytics_collector import YouTubeAnalyticsCollector

        monkeypatch.setattr(sys, "argv", ["yt-analytics", "--depth", "full"])
        monkeypatch.setattr(
            YouTubeAnalyticsCollector,
            "get_retention_summary",
            lambda self, start, end, top_n: [{"video_id": "VID_1", "error": "retention API failed"}],
        )

        with pytest.raises(SystemExit) as exit_info:
            analytics_system.main()

        assert exit_info.value.code == 1
        assert not list((stub_analytics_boundaries / "data").glob("analytics_data_*.json"))

    def test_explicit_standard_depth_persists_standard_data(self, monkeypatch, stub_analytics_boundaries):
        """--depth standard は standard データを保存する。"""
        from youtube_automation.scripts import analytics_system

        monkeypatch.setattr(sys, "argv", ["yt-analytics", "--depth", "standard"])

        with pytest.raises(SystemExit) as exit_info:
            analytics_system.main()

        assert exit_info.value.code == 0
        saved_files = list((stub_analytics_boundaries / "data").glob("analytics_data_*.json"))
        assert len(saved_files) == 1
        payload = json.loads(saved_files[0].read_text(encoding="utf-8"))
        assert payload["collection_depth"] == "standard"
        assert "by_country" not in payload["audience"]
        assert "retention" not in payload
        assert payload["traffic_sources"]["search_terms"] == [
            {"detail": "lofi music", "views": 30, "watch_time_minutes": 90}
        ]
        assert payload["playlist_analytics"]["playlists"]["PL_COMPLETE"]["views"] == 300

    def test_unknown_depth_is_rejected_before_collection(self, monkeypatch, stub_analytics_boundaries):
        """choices 外の depth は argparse が exit 2 で拒否する。"""
        from youtube_automation.scripts import analytics_system

        monkeypatch.setattr(sys, "argv", ["yt-analytics", "--depth", "unknown"])

        with pytest.raises(SystemExit) as exit_info:
            analytics_system.main()

        assert exit_info.value.code == 2
        assert not (stub_analytics_boundaries / "data").exists()

    def test_omitted_depth_persists_standard_without_full_only_data(self, monkeypatch, stub_analytics_boundaries):
        """depth 省略時は従来どおり standard JSON を保存する。"""
        from youtube_automation.scripts import analytics_system

        monkeypatch.setattr(sys, "argv", ["yt-analytics"])

        with pytest.raises(SystemExit) as exit_info:
            analytics_system.main()

        assert exit_info.value.code == 0
        saved_files = list((stub_analytics_boundaries / "data").glob("analytics_data_*.json"))
        assert len(saved_files) == 1
        payload = json.loads(saved_files[0].read_text(encoding="utf-8"))
        assert payload["collection_depth"] == "standard"
        assert payload["audience"] == {
            "by_device": {"devices": {"TV": {"views": 25}}},
            "by_subscribed_status": {
                "statuses": {
                    "SUBSCRIBED": {"views": 10, "view_share_percent": 25.0},
                    "UNSUBSCRIBED": {"views": 30, "view_share_percent": 75.0},
                },
                "total_views": 40,
            },
        }
        assert "retention" not in payload


class TestReportingSubmodes:
    def test_dry_run_only_observes_reporting_state(self, monkeypatch, capsys):
        from youtube_automation.scripts import analytics_system

        client = MagicMock()
        client.dry_run_inspection.return_value = {
            "selected_report_type": "channel_reach_basic_a1",
            "existing_job": {"id": "job-1"},
            "recent_reports_count": 2,
        }
        monkeypatch.setattr(analytics_system, "_make_reporting_client", lambda: client)

        code = analytics_system._run_reporting_dry_run()

        assert code == 0
        client.dry_run_inspection.assert_called_once_with()
        client.select_report_type.assert_not_called()
        client.ensure_job.assert_not_called()
        assert "job-1" in capsys.readouterr().out

    def test_create_job_remains_idempotent_and_reports_backfill_contract(self, monkeypatch, capsys):
        from youtube_automation.scripts import analytics_system

        client = MagicMock()
        client.select_report_type.return_value = "channel_reach_basic_a1"
        client.ensure_job.return_value = "job-1"
        monkeypatch.setattr(analytics_system, "_make_reporting_client", lambda: client)

        code = analytics_system._run_reporting_create_job()

        assert code == 0
        client.ensure_job.assert_called_once_with("channel_reach_basic_a1")
        output = capsys.readouterr().out
        assert "過去 30 日分が backfill" in output
        assert "日次（D+2）" in output


class TestPlaylistCli:
    def test_cli_saves_playlist_api_response_and_exits_zero(self, system, mock_config, tmp_path):
        """公開 CLI が playlist API 応答を保存して成功終了する。"""
        system.authenticated = True
        system.collector = _collector_with_playlist_response({"rows": [["PL_COMPLETE", 300, 120]]})

        with (
            patch("youtube_automation.scripts.analytics_system.AnalyticsSystem", return_value=system),
            patch("youtube_automation.scripts.analytics_system.load_config", return_value=mock_config),
            patch("youtube_automation.scripts.analytics_system.channel_dir", return_value=tmp_path),
            patch.object(system, "authenticate", return_value=True),
            patch.object(sys, "argv", ["yt-analytics", "--days", "7"]),
        ):
            from youtube_automation.scripts.analytics_system import main

            with pytest.raises(SystemExit) as exit_info:
                main()

        assert exit_info.value.code == 0
        system.collector.analytics_service.reports().query.assert_called_once_with(
            ids="channel==UC_TEST",
            startDate=ANY,
            endDate=ANY,
            metrics="playlistViews,playlistAverageViewDuration",
            dimensions="playlist",
            sort="-playlistViews",
            maxResults=200,
        )
        saved_file = next((tmp_path / "data").glob("analytics_data_*.json"))
        import json

        with open(saved_file, encoding="utf-8") as file:
            assert json.load(file)["playlist_analytics"] == {
                "playlists": {
                    "PL_COMPLETE": {
                        "views": 300,
                        "average_view_duration": 120,
                        "view_share_percent": 100.0,
                    }
                },
                "total_views": 300,
            }

    def test_playlist_api_error_fails_collection_without_saving_or_exit_zero(self, system, mock_config, tmp_path):
        """playlist API 失敗は公開 CLI の失敗終了まで伝播し、JSON を保存しない。"""
        system.authenticated = True
        collector = _collector_with_playlist_response({})
        collector.analytics_service.reports().query().execute.side_effect = HttpError(
            MagicMock(status=403), b"quotaExceeded"
        )
        system.collector = collector

        with (
            patch("youtube_automation.scripts.analytics_system.AnalyticsSystem", return_value=system),
            patch("youtube_automation.scripts.analytics_system.load_config", return_value=mock_config),
            patch("youtube_automation.scripts.analytics_system.channel_dir", return_value=tmp_path),
            patch.object(system, "authenticate", return_value=True),
            patch.object(sys, "argv", ["yt-analytics", "--days", "7"]),
        ):
            from youtube_automation.scripts.analytics_system import main

            with pytest.raises(SystemExit) as exit_info:
                main()

        assert exit_info.value.code == 1
        assert list((tmp_path / "data").glob("analytics_data_*.json")) == []
