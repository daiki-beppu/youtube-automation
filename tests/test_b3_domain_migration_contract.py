"""契約テスト: Issue #2306 (B3) の domain 移行。

対応表:

* B3-R2/R3/R8/R9: analytics の module 配置、Protocol と public selector
* B3-R10/R11/R12/R13: thumbnail の純粋な選択 policy と入口
* B3-R14--R23: media の provider-neutral 境界と B2 metadata edge
* B3-R24--R30: DistroKid naming/specification/preparation/release 契約
* B3-R31/R32: weekly vote の resource loader と保存 roundtrip
* B3-R37: active source の旧 owner import 除去

既存の各 domain ロジックの詳細は既存テスト群が担う。本ファイルでは、移動後に
失われやすい owner、依存注入、公開入口、境界接続を観測する。

未カバー理由: B3-R1/R17--R20/R33--R35/R38/R39 は owner receipt、B4/B5/B6
handoff、legacy resource の削除、CHANGELOG、architecture 文書という非テスト
成果物であり、本文固定テストは作らない。R4--R7/R13/R21/R25--R30/R36/R40 は
既存の各入口テストまたは実装後の targeted manifest が担うため、移行境界を重複
して固定しない。R22/R23 はそれぞれ captions/reference の実データを通るテスト、
R31/R32 は roundtrip テストでカバーする。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response
from PIL import Image

from youtube_automation.utils.exceptions import AuthError, ConfigError, YouTubeAPIError
from youtube_automation.utils.preflight_checks import check_thumbnail_skill_config

_ROOT = Path(__file__).resolve().parents[1]

_DOMAIN_MODULES = (
    "youtube_automation.domains.analytics.ports",
    "youtube_automation.domains.analytics.service",
    "youtube_automation.domains.analytics.collection.video_listing",
    "youtube_automation.domains.analytics.collection.strategic_analytics",
    "youtube_automation.domains.analytics.reporting.reporting_analytics",
    "youtube_automation.domains.analytics.analysis.launch_curve_analyzer",
    "youtube_automation.domains.analytics.series.channel_trend",
    "youtube_automation.domains.thumbnail.archive",
    "youtube_automation.domains.thumbnail.correlation",
    "youtube_automation.domains.thumbnail.features",
    "youtube_automation.domains.thumbnail.references",
    "youtube_automation.domains.thumbnail.selection",
    "youtube_automation.domains.media.audio",
    "youtube_automation.domains.media.captions",
    "youtube_automation.domains.media.image",
    "youtube_automation.domains.media.video",
    "youtube_automation.domains.distrokid.naming",
    "youtube_automation.domains.distrokid.metadata",
    "youtube_automation.domains.distrokid.specification",
    "youtube_automation.domains.distrokid.preparation",
    "youtube_automation.domains.distrokid.release",
    "youtube_automation.domains.collections.weekly_vote_log",
    "youtube_automation.domains.metadata.descriptions",
    "youtube_automation.domains.metadata.placeholders",
)


def test_b3_domain_modules_are_importable() -> None:
    """Given the approved owner map, each domain leaf is importable."""
    for module_name in _DOMAIN_MODULES:
        assert importlib.import_module(module_name).__name__ == module_name


def test_b3_removes_legacy_owner_imports_from_executable_code() -> None:
    """実行コードの import が削除済み owner を参照しないことを固定する。"""
    legacy_prefixes = (
        "youtube_automation.utils." + "analytics_",
        "youtube_automation.utils." + "thumbnail_",
        "youtube_automation.utils." + "distrokid_",
        "youtube_automation.utils." + "weekly_vote_log",
    )
    offenders: list[str] = []
    for root in (_ROOT / "src", _ROOT / "tests"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = [node.module]
                for module in modules:
                    if module.startswith(legacy_prefixes):
                        offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno}:{module}")
    assert offenders == []


def test_thumbnail_text_package_uses_fully_qualified_imports() -> None:
    """The migrated package follows the repository-wide import boundary."""
    package_root = _ROOT / "src/youtube_automation/domains/thumbnail/text"
    offenders: list[str] = []
    for path in package_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_analytics_collector_requires_injected_clients() -> None:
    """When initialized, analytics uses clients supplied at the boundary."""
    module = importlib.import_module("youtube_automation.domains.analytics.service")
    collector_type = module.YouTubeAnalyticsCollector

    with pytest.raises(TypeError):
        collector_type()

    youtube = MagicMock()
    youtube.resolve_channel.return_value = {"id": "channel-1", "title": "Test"}
    analytics = MagicMock()
    reporting = MagicMock()

    collector = collector_type(
        youtube_client=youtube,
        analytics_client=analytics,
        reporting_client=reporting,
        channel_root=_ROOT,
    )
    collector.initialize()

    assert collector.channel_id == "channel-1"
    assert collector.channel_root == _ROOT
    youtube.resolve_channel.assert_called_once_with()


def test_domains_do_not_resolve_channel_configuration() -> None:
    """Configuration and channel roots are resolved by consumers, not domains."""
    domain_files = (
        _ROOT / "src/youtube_automation/domains/thumbnail/archive.py",
        _ROOT / "src/youtube_automation/domains/analytics/mixins/channel_analytics.py",
    )
    forbidden = ("channel_dir", "load_skill_config")
    offenders = []
    for path in domain_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden:
                offenders.append(f"{path}:{node.lineno}:{node.id}")
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                offenders.append(f"{path}:{node.lineno}:{node.attr}")
    assert offenders == []


def test_analytics_collector_reports_missing_channel_as_api_error() -> None:
    """An empty Data API response keeps the established domain error contract."""
    module = importlib.import_module("youtube_automation.domains.analytics.service")
    youtube = MagicMock()
    youtube.resolve_channel.return_value = {}

    collector = module.YouTubeAnalyticsCollector(
        youtube_client=youtube,
        analytics_client=MagicMock(),
        reporting_client=MagicMock(),
        channel_root=_ROOT,
    )

    with pytest.raises(YouTubeAPIError, match="channel was not found"):
        collector.initialize()


def test_analytics_collector_observes_injected_query_port() -> None:
    """Collection invokes the purpose-named analytics port, not a request chain."""
    module = importlib.import_module("youtube_automation.domains.analytics.service")
    analytics = MagicMock()
    analytics.query.return_value = {"rows": [["2026-01-01", 10, 20, 30, 40, 0, 1, 0, 2, 3, 4, 5, 6, 7]]}
    collector = module.YouTubeAnalyticsCollector(
        youtube_client=MagicMock(),
        analytics_client=analytics,
        reporting_client=MagicMock(),
        channel_root=_ROOT,
    )
    collector.channel_id = "channel-1"

    collector.get_channel_analytics("2026-01-01", "2026-01-02")

    analytics.query.assert_called_once()


def test_analytics_domain_does_not_reinitialize_injected_clients() -> None:
    """Injected ports remain the sole client boundary for every analytics operation."""
    analytics_root = _ROOT / "src/youtube_automation/domains/analytics"
    forbidden_guards = ("if not self.analytics_service", "if not self.youtube_service")
    offenders = []
    for path in analytics_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for guard in forbidden_guards:
            if guard in source:
                offenders.append(f"{path.relative_to(_ROOT)}:{guard}")
    assert offenders == []


def test_analytics_domain_has_no_sdk_execution_or_retry_boundary() -> None:
    """Analytics domain delegates SDK construction, execution, and retry to an adapter."""
    analytics_root = _ROOT / "src/youtube_automation/domains/analytics"
    forbidden_imports = {
        "googleapiclient",
        "google.auth",
        "youtube_automation.utils.retry",
        "youtube_automation.utils.youtube_service",
    }
    offenders: list[str] = []
    for path in analytics_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
                offenders.extend(f"{path}:{node.lineno}:{name}" for name in imported & forbidden_imports)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in forbidden_imports:
                    offenders.append(f"{path}:{node.lineno}:{module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                offenders.append(f"{path}:{node.lineno}:.execute()")
    assert offenders == []


def test_analytics_adapter_executes_the_external_reporting_operation() -> None:
    """The adapter owns Google request construction and execution."""
    adapter = importlib.import_module("youtube_automation.infrastructure.analytics_adapter")
    client = MagicMock()
    client.reports.return_value.query.return_value.execute.return_value = {"rows": [[1]]}
    analytics = adapter.AnalyticsAdapter(client, retry_requests=True)

    assert analytics.query(start_date="2026-01-01", end_date="2026-01-02") == {"rows": [[1]]}
    client.reports.return_value.query.assert_called_once_with(start_date="2026-01-01", end_date="2026-01-02")


def test_analytics_adapter_retries_transient_and_translates_permanent_errors(monkeypatch) -> None:
    """Retry and SDK error translation stay at the adapter boundary."""
    adapter_module = importlib.import_module("youtube_automation.infrastructure.analytics_adapter")
    retry_module = importlib.import_module("youtube_automation.utils.retry")
    monkeypatch.setattr(retry_module, "_DEFAULT_SLEEP", lambda _seconds: None)
    monkeypatch.setattr(retry_module, "_DEFAULT_JITTER", lambda low, _high: low)

    client = MagicMock()
    request = client.reports.return_value.query.return_value
    request.execute.side_effect = [
        HttpError(Response({"status": "503"}), b"backendError"),
        {"rows": [[1]]},
    ]
    adapter = adapter_module.AnalyticsAdapter(client, retry_requests=True)
    assert adapter.query() == {"rows": [[1]]}
    assert request.execute.call_count == 2

    request.execute.side_effect = HttpError(Response({"status": "400"}), b"bad request")
    with pytest.raises(YouTubeAPIError) as error:
        adapter.query()
    assert error.value.status_code == 400


def test_analytics_adapter_single_attempt_preserves_non_retrying_boundary() -> None:
    """The channel-status boundary must not add quota-consuming retry attempts."""
    adapter_module = importlib.import_module("youtube_automation.infrastructure.analytics_adapter")
    client = MagicMock()
    request = client.reports.return_value.query.return_value
    request.execute.side_effect = [
        HttpError(Response({"status": "503"}), b"backendError"),
        {"rows": [[1]]},
    ]
    adapter = adapter_module.AnalyticsAdapter(client, retry_requests=False)

    with pytest.raises(YouTubeAPIError) as error:
        adapter.query()

    assert error.value.status_code == 503
    assert request.execute.call_count == 1


def test_youtube_data_adapter_builds_named_operation_requests() -> None:
    """Each named Data API operation preserves its explicit SDK query contract."""
    module = importlib.import_module("youtube_automation.infrastructure.analytics_adapter")
    service = MagicMock()
    for resource in (service.channels(), service.playlistItems(), service.playlists(), service.videos()):
        resource.list.return_value.execute.return_value = {"items": []}
    adapter = module.YouTubeDataAdapter(service, retry_requests=True)

    adapter.resolve_channel()
    service.channels.return_value.list.assert_called_once_with(part="id,snippet,statistics", mine=True)
    service.channels.return_value.list.reset_mock()
    adapter.list_uploads("channel-1")
    service.channels.return_value.list.assert_called_once_with(part="contentDetails", id="channel-1")
    service.channels.return_value.list.reset_mock()
    adapter.list_playlist_items("playlist-1", None)
    service.playlistItems.return_value.list.assert_called_once_with(
        part="snippet,contentDetails", playlistId="playlist-1", maxResults=50, pageToken=None
    )
    service.playlistItems.return_value.list.reset_mock()
    adapter.list_playlist_items("playlist-1", "page-2")
    service.playlistItems.return_value.list.assert_called_once_with(
        part="snippet,contentDetails", playlistId="playlist-1", maxResults=50, pageToken="page-2"
    )
    service.playlistItems.return_value.list.reset_mock()
    adapter.list_playlists("channel-1")
    service.playlists.return_value.list.assert_called_once_with(part="snippet", channelId="channel-1", maxResults=50)
    service.playlists.return_value.list.reset_mock()
    adapter.list_playlist_items_for_display("playlist-1", max_results=50)
    service.playlistItems.return_value.list.assert_called_once_with(
        part="snippet", playlistId="playlist-1", maxResults=50
    )
    service.playlistItems.return_value.list.reset_mock()
    adapter.list_playlist_items_for_display("uploads", max_results=10)
    service.playlistItems.return_value.list.assert_called_once_with(
        part="snippet", playlistId="uploads", maxResults=10
    )
    service.playlistItems.return_value.list.reset_mock()
    adapter.list_videos("video-1,video-2", part="status")
    service.videos.return_value.list.assert_called_once_with(part="status", id="video-1,video-2")


def test_channel_status_fallback_requests_ten_latest_uploads(monkeypatch) -> None:
    """The uploads fallback keeps its smaller display-query contract."""
    module = importlib.import_module("youtube_automation.scripts.get_channel_status")

    class Collector:
        def __init__(self, **_kwargs):
            self.channel_id = "channel-1"
            self.calls = []
            self.youtube_service = self
            self.analytics_service = self

        def initialize(self):
            return None

        def resolve_channel(self):
            return {"id": "channel-1", "snippet": {"title": "Test"}, "statistics": {}}

        def list_uploads(self, _channel_id):
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]}

        def list_playlists(self, _channel_id):
            return {"items": []}

        def list_playlist_items_for_display(self, playlist_id, *, max_results):
            self.calls.append((playlist_id, max_results))
            return {"items": []}

        def query(self, **_kwargs):
            return {"rows": []}

    collector = Collector()
    config = MagicMock()
    config.analytics.collection_filter_keywords = []
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "channel_dir", lambda: _ROOT)
    monkeypatch.setattr(module, "YouTubeAnalyticsCollector", lambda **kwargs: collector)

    module.get_channel_latest_status()

    assert collector.calls == [("uploads", 10)]


def test_analytics_public_selector_and_all_video_api_are_preserved() -> None:
    """K-01 selectors remain domain-facing operations after the move."""
    module = importlib.import_module("youtube_automation.domains.analytics.collection.strategic_analytics")
    collector = MagicMock()
    collector.get_all_channel_videos.return_value = []
    collector.get_all_video_analytics = module.StrategicAnalyticsMixin.get_all_video_analytics.__get__(collector)
    assert collector.get_all_video_analytics("2026-01-01", "2026-01-02") == []


def test_thumbnail_selection_keeps_config_validation_and_tie_breaking(tmp_path: Path) -> None:
    """Invalid mode is rejected and equal candidates use deterministic ordering."""
    module = importlib.import_module("youtube_automation.domains.thumbnail.selection")
    with pytest.raises(ConfigError):
        module.resolve_auto_selection_settings({"image_generation": {"auto_selection": {"mode": "unsupported"}}})

    settings = module.AutoSelectionSettings(
        enabled=True,
        min_width=160,
        min_height=90,
        aspect_tolerance=0.02,
        mode="selection_only",
    )
    image_paths = []
    for name in ("b.jpg", "a.jpg"):
        path = tmp_path / name
        Image.new("RGB", (160, 90), (20, 30, 80)).save(path)
        image_paths.append(path)
        centroid = module.extract_features_from_path(image_paths[0])
        scores = module.score_candidates(
            image_paths,
            centroid=centroid,
            settings=settings,
        )
    assert module.select_best(scores, mode="selection_only").path.name == "a.jpg"


def test_captions_domain_keeps_timestamp_parser_and_srt_contract() -> None:
    """Pure caption generation stays usable without a YouTube client."""
    module = importlib.import_module("youtube_automation.domains.media.captions")
    tracks = module.parse_track_timestamps("00:00 First\n03:00 After")
    result = module.generate_srt(["[Verse]\nHello", "World"], tracks, 180_000)
    assert "00:00:00,000 --> 00:03:00,000" in result
    assert "[Verse]" not in result
    assert "Hello" in result and "World" in result


def test_caption_upload_sdk_boundary_is_infrastructure() -> None:
    """Caption SDK operations stay outside the pure media domain and CLI."""
    domain = (_ROOT / "src/youtube_automation/domains/media/captions.py").read_text(encoding="utf-8")
    script = (_ROOT / "src/youtube_automation/scripts/captions_upload.py").read_text(encoding="utf-8")
    adapter = importlib.import_module("youtube_automation.infrastructure.captions_adapter")

    assert not hasattr(importlib.import_module("youtube_automation.domains.media.captions"), "upload_caption")
    assert "googleapiclient" not in domain
    assert "googleapiclient" not in script
    assert adapter.upload_caption is not None


def test_video_daily_benchmark_builds_injected_domain_collector(monkeypatch) -> None:
    """The benchmark uses the current analytics composition boundary."""
    benchmark = importlib.import_module("bench.bench_video_daily")
    monkeypatch.setattr(benchmark, "get_youtube_readonly", lambda: MagicMock())
    monkeypatch.setattr(benchmark, "get_analytics", lambda: MagicMock())
    monkeypatch.setattr(benchmark, "get_reporting", lambda: MagicMock())
    monkeypatch.setattr(benchmark, "get_credentials_readonly", lambda: MagicMock())
    monkeypatch.setattr(benchmark, "ReportingAPIClient", MagicMock())

    collector = benchmark._collector()

    collector_type = importlib.import_module("youtube_automation.domains.analytics.service").YouTubeAnalyticsCollector
    assert isinstance(collector, collector_type)


def test_video_daily_benchmark_skips_expected_auth_failure(monkeypatch) -> None:
    """認証・設定境界の失敗だけはベンチをスキップする。"""
    benchmark = importlib.import_module("bench.bench_video_daily")
    monkeypatch.setattr(benchmark, "_collector", lambda: (_ for _ in ()).throw(AuthError("token missing")))

    assert benchmark.run() == []


def test_video_daily_benchmark_propagates_unexpected_initialization_failure(monkeypatch) -> None:
    """collector の実装・API契約エラーは空結果へ変換しない。"""
    benchmark = importlib.import_module("bench.bench_video_daily")
    failure = RuntimeError("collector contract broken")
    monkeypatch.setattr(benchmark, "_collector", lambda: (_ for _ in ()).throw(failure))

    with pytest.raises(RuntimeError, match="collector contract broken"):
        benchmark.run()


def test_video_daily_benchmark_propagates_unexpected_measurement_failure(monkeypatch) -> None:
    """計測中の実装エラーもベンチの失敗として送出する。"""
    benchmark = importlib.import_module("bench.bench_video_daily")
    monkeypatch.setattr(benchmark, "_collector", lambda: object())
    failure = RuntimeError("measurement contract broken")
    monkeypatch.setattr(benchmark, "_bench_days", lambda _collector, _days: (_ for _ in ()).throw(failure))

    with pytest.raises(RuntimeError, match="measurement contract broken"):
        benchmark.run()


def test_thumbnail_reference_resolution_uses_metadata_placeholder_policy(tmp_path: Path) -> None:
    """Placeholder values are classified by the B2 metadata edge."""
    references = importlib.import_module("youtube_automation.domains.thumbnail.references")
    benchmark = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "COMP"
    benchmark.mkdir(parents=True)
    image = benchmark / "ref.jpg"
    image.write_bytes(b"image")

    resolved = references.resolve_configured_benchmark_references(
        tmp_path,
        ["{{benchmark_reference}}", str(image.relative_to(tmp_path))],
    )
    assert resolved.placeholders == ["{{benchmark_reference}}"]
    assert resolved.references == [image.resolve()]


def test_metadata_placeholder_policy_is_used_by_preflight_at_runtime(tmp_path: Path) -> None:
    """Preflight and thumbnail references classify the same placeholder input."""
    references = importlib.import_module("youtube_automation.domains.thumbnail.references")
    placeholder = "{{benchmark_reference}}"
    resolved = references.resolve_configured_benchmark_references(tmp_path, [placeholder])

    cfg = {
        "image_generation": {
            "gemini": {
                "generation_mode": "single_step",
                "single_step": {"max_attempts": 1, "rotate": True},
                "reference_images": {"default": [placeholder]},
                "composition_rules": {},
            }
        }
    }
    issues = check_thumbnail_skill_config(tmp_path, cfg)

    assert resolved.placeholders == [placeholder]
    assert any("reference_images.default が未設定/空/TBD" in issue for issue in issues)


def test_distrokid_naming_is_independent_of_release_command() -> None:
    """Preparation can use naming policy without importing the release CLI."""
    naming = importlib.import_module("youtube_automation.domains.distrokid.naming")
    preparation = importlib.import_module("youtube_automation.domains.distrokid.preparation")
    assert naming.kebab_to_title("disc1-coding-focus-vol1") == "Disc1 Coding Focus Vol1"
    assert preparation.build_draft_spec is not None


def test_weekly_vote_domain_roundtrips_schema_and_saved_entry(tmp_path: Path) -> None:
    """The reader and its packaged schema form one persistence boundary."""
    module = importlib.import_module("youtube_automation.domains.collections.weekly_vote_log")
    schema = module.load_weekly_vote_log_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    log = module.append_weekly_vote_entry(
        channel_dir=tmp_path,
        week_start="2026-05-04",
        axes=[module.AxisVote("rain_window", "Rain Window", 12)],
    )
    reloaded = module.load_weekly_vote_log(channel_dir=tmp_path)
    assert reloaded.entries == log.entries
    assert reloaded.entries[0].total_votes == 12


def test_distrokid_release_uses_the_domain_naming_policy(tmp_path: Path) -> None:
    """Release fallback titles use the same policy as preparation."""
    release = importlib.import_module("youtube_automation.domains.distrokid.release")
    source_dir = tmp_path / "30-distrokid" / "disc1-coding-focus-vol1"
    source_dir.mkdir(parents=True)
    (source_dir / "01-focus.mp3").write_bytes(b"mp3")
    (source_dir / "metadata.md").write_text(
        "# Album\n\n## Tracks\n\n| filename | title |\n| --- | --- |\n| 01-focus.mp3 | Focus |\n",
        encoding="utf-8",
    )

    payload = release._disc_source_payload(
        release.CollectionPaths(tmp_path),
        "30-distrokid/disc1-coding-focus-vol1",
        {},
    )

    assert payload["release"]["album_title"] == "Disc1 Coding Focus Vol1"


def test_plural_rain_layers_remains_an_active_configuration_contract() -> None:
    """B3 removes only the singular legacy alias; the active plural flow remains."""
    module = importlib.import_module("youtube_automation.scripts.apply_rain_layers")
    config = {"post_processing": {"rain_layers": {"enabled": False}}}
    resolved = module._resolve_post_processing_config(config)
    assert resolved["enabled"] is False
