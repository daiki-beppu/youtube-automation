from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from youtube_automation.commands.analytics.dashboard import create_server, main
from youtube_automation.infrastructure.analytics.dashboard_publications import (
    build_dashboard_publications,
    save_dashboard_publications,
    with_dashboard_publication_error,
)


def _write_channel(root: Path) -> Path:
    channel = root / "channel"
    (channel / "config" / "channel").mkdir(parents=True)
    (channel / "data").mkdir()
    (channel / "config" / "channel" / "meta.json").write_text(
        json.dumps(
            {
                "channel": {
                    "name": "Night Drive",
                    "short": "ND",
                    "youtube_handle": "@nightdrive",
                    "url": "https://youtube.com/@nightdrive",
                    "tagline": "Drive at night",
                }
            }
        ),
        encoding="utf-8",
    )
    (channel / "config" / "channel" / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "synthwave", "style": "retro", "context": "driving"},
                "tags": {"base": ["synthwave"], "themes": {}},
                "descriptions": {"opening": "Night music", "perfect_for": ["Driving"], "hashtags": ["#Night"]},
                "title": {"template": "{theme}"},
            }
        ),
        encoding="utf-8",
    )
    (channel / "config" / "channel" / "youtube.json").write_text(
        json.dumps({"youtube": {"category_id": "10", "privacy_status": "public", "language": "ja"}}),
        encoding="utf-8",
    )
    (channel / "config" / "channel" / "workflow.json").write_text(
        json.dumps({"workflow": {"manual_baseline_minutes": {"wf-next": 1, "post-publish": 2}}}),
        encoding="utf-8",
    )
    (channel / "data" / "analytics_data_2026-07-20.json").write_text(
        json.dumps(
            {
                "collection_period": {"collected_at": "2026-07-20T12:00:00Z"},
                "channel_analytics": {"summary": {"total_views": 123}},
                "video_analytics": {"video-1": {"title": "Midnight", "views": 123}},
            }
        ),
        encoding="utf-8",
    )
    publications = build_dashboard_publications(
        ["2026-07-20T04:00:00Z", "2026-07-20T05:00:00Z"],
        timezone="Asia/Tokyo",
        fetched_at=datetime(2026, 7, 20, 13, tzinfo=UTC),
    )
    publications_with_error = with_dashboard_publication_error(
        publications,
        code="publication_refresh_failed",
        message="quota exceeded",
        attempted_at=datetime(2026, 7, 20, 14, tzinfo=UTC),
    )
    save_dashboard_publications(channel / "data" / "dashboard_publications.json", publications_with_error)
    active = channel / "collections" / "planning" / "active"
    active.mkdir(parents=True)
    (active / "workflow-state.json").write_text(
        json.dumps({"phase": "planning", "created_at": "2026-07-21"}), encoding="utf-8"
    )
    latest = channel / "collections" / "live" / "latest"
    latest.mkdir(parents=True)
    (latest / "workflow-state.json").write_text(
        json.dumps({"phase": "complete", "created_at": "2026-07-20"}), encoding="utf-8"
    )
    history_dir = channel / ".automation-run"
    history_dir.mkdir()
    (history_dir / "history.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "attempts": [
                    {
                        "collection": "collections/planning/active",
                        "action": "wf-next",
                        "status": "success",
                        "timing": {
                            "segments": [
                                {
                                    "kind": "ai",
                                    "started_at": "2026-07-21T00:00:00+00:00",
                                    "ended_at": "2026-07-21T00:00:10+00:00",
                                    "duration_seconds": 10,
                                },
                                {
                                    "kind": "human",
                                    "started_at": "2026-07-21T00:00:10+00:00",
                                    "ended_at": "2026-07-21T00:00:20+00:00",
                                    "duration_seconds": 5,
                                },
                            ]
                        },
                    },
                    {
                        "collection": "collections/live/latest",
                        "action": "post-publish",
                        "status": "success",
                        "timing": {
                            "segments": [
                                {
                                    "kind": "ai",
                                    "started_at": "2026-07-20T00:00:00+00:00",
                                    "ended_at": "2026-07-20T00:00:10+00:00",
                                    "duration_seconds": 20,
                                },
                                {
                                    "kind": "human",
                                    "started_at": "2026-07-20T00:00:10+00:00",
                                    "ended_at": "2026-07-20T00:00:20+00:00",
                                    "duration_seconds": 10,
                                },
                            ]
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return channel


@pytest.fixture
def dashboard_server(tmp_path: Path):
    channel = _write_channel(tmp_path)
    registry = tmp_path / "channels.json"
    registry.write_text(json.dumps([str(channel)]), encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<main>dashboard shell</main>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('dashboard')", encoding="utf-8")

    server = create_server(port=0, registry_path=registry, asset_root=assets)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _json(url: str) -> tuple[int, dict[str, object]]:
    with urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read())


def _response_bytes(url: str) -> bytes:
    with urlopen(url, timeout=5) as response:
        assert response.status == 200
        return response.read()


def _post_json(url: str, payload: object | None = None) -> tuple[int, dict[str, object]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    with urlopen(Request(url, data=data, method="POST"), timeout=5) as response:
        return response.status, json.loads(response.read())


def test_refresh_endpoint_recollects_and_rebuilds_read_model(tmp_path: Path) -> None:
    channel = _write_channel(tmp_path)

    def collect(path: Path, days: int) -> None:
        assert days == 30
        snapshot = path / "data" / "analytics_data_2026-07-20.json"
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        payload["channel_analytics"]["summary"]["total_views"] = 456
        snapshot.write_text(json.dumps(payload), encoding="utf-8")

    server = create_server(port=0, channel_paths=[channel], collect_channel=collect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, overview = _post_json(f"http://127.0.0.1:{server.server_port}/api/refresh")
        assert status == 200
        assert overview["channels"][0]["summary"]["views"] == 456
        _, current = _json(f"http://127.0.0.1:{server.server_port}/api/channels")
        assert current == overview
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_refresh_endpoint_skips_collection_when_server_is_offline(tmp_path: Path) -> None:
    channel = _write_channel(tmp_path)
    server = create_server(port=0, channel_paths=[channel], collect_channel=None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, overview = _post_json(f"http://127.0.0.1:{server.server_port}/api/refresh")
        assert status == 200
        assert overview["channels"][0]["summary"]["views"] == 123
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_refresh_endpoint_returns_conflict_while_refresh_is_running(tmp_path: Path) -> None:
    channel = _write_channel(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def collect(_path: Path, _days: int) -> None:
        started.set()
        assert release.wait(timeout=5)

    server = create_server(port=0, channel_paths=[channel], collect_channel=collect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    first = threading.Thread(
        target=lambda: _post_json(f"http://127.0.0.1:{server.server_port}/api/refresh"), daemon=True
    )
    first.start()
    try:
        assert started.wait(timeout=5)
        with pytest.raises(HTTPError) as exc_info:
            _post_json(f"http://127.0.0.1:{server.server_port}/api/refresh")
        assert exc_info.value.code == 409
        assert json.loads(exc_info.value.read())["error"]["code"] == "refresh_in_progress"
    finally:
        release.set()
        first.join(timeout=5)
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_server_returns_json_404_for_unknown_post_api(dashboard_server: str) -> None:
    with pytest.raises(HTTPError) as exc_info:
        _post_json(f"{dashboard_server}/api/unknown")
    assert exc_info.value.code == 404
    assert json.loads(exc_info.value.read())["error"]["code"] == "not_found"


@pytest.mark.parametrize("days", [7, 30, 90])
def test_refresh_endpoint_passes_allowed_days_to_collector(tmp_path: Path, days: int) -> None:
    channel = _write_channel(tmp_path)
    received: list[int] = []
    server = create_server(
        port=0,
        channel_paths=[channel],
        collect_channel=lambda _channel, selected_days: received.append(selected_days),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _ = _post_json(f"http://127.0.0.1:{server.server_port}/api/refresh", {"days": days})
        assert status == 200
        assert received == [days]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("days", [45, 0, "7", True, None])
def test_refresh_endpoint_rejects_invalid_days_without_collection(tmp_path: Path, days: object) -> None:
    channel = _write_channel(tmp_path)
    received: list[int] = []
    server = create_server(
        port=0,
        channel_paths=[channel],
        collect_channel=lambda _channel, selected_days: received.append(selected_days),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc_info:
            _post_json(f"http://127.0.0.1:{server.server_port}/api/refresh", {"days": days})
        assert exc_info.value.code == 400
        assert json.loads(exc_info.value.read())["error"]["code"] == "invalid_request"
        assert received == []
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_server_api_json_bytes_match_production_builder_golden(dashboard_server: str) -> None:
    overview = _response_bytes(f"{dashboard_server}/api/channels")
    channel_id = json.loads(overview)["channels"][0]["id"]
    detail = _response_bytes(f"{dashboard_server}/api/channels/{channel_id}")
    publications = _response_bytes(f"{dashboard_server}/api/publications")
    trends = _response_bytes(f"{dashboard_server}/api/trends")
    channel_id_bytes = channel_id.encode("utf-8")

    assert overview.replace(channel_id_bytes, b"<channel-id>") == (
        b'{"schema_version": 2, "channels": [{"id": "<channel-id>", "name": "Night Drive", '
        b'"status": "ready", "snapshot": "analytics_data_2026-07-20.json", '
        b'"collected_at": "2026-07-20T12:00:00Z", "period": {"start_date": null, "end_date": null}, '
        b'"scheduled_count": null, "summary": {"views": 123, "watch_time_minutes": 0, '
        b'"subscribers_net": 0, "engagements": 0, "average_view_percentage": 0}, "error": null, '
        b'"refresh_error": null, "video_count": 1}]}'
    )
    assert detail.replace(channel_id_bytes, b"<channel-id>") == (
        b'{"id": "<channel-id>", "name": "Night Drive", "status": "ready", '
        b'"snapshot": "analytics_data_2026-07-20.json", "collected_at": "2026-07-20T12:00:00Z", '
        b'"period": {"start_date": null, "end_date": null}, "scheduled_count": null, '
        b'"summary": {"views": 123, "watch_time_minutes": 0, "subscribers_net": 0, "engagements": 0, '
        b'"average_view_percentage": 0}, "videos": [{"video_id": "video-1", "title": "Midnight", '
        b'"views": 123, "impressions": 0, "ctr_percentage": 0, "likes": 0, "comments": 0, "shares": 0, '
        b'"subscribers_gained": 0, "average_view_duration_seconds": 0, "engagements": 0}], "error": null, '
        b'"refresh_error": null, "workflow_timing": {"status": "ready", "collections": '
        b'[{"collection_id": "active", "stage": "planning", "steps": [{"action": "wf-next", '
        b'"status": "success", "manual_baseline_seconds": 60.0, "ai_seconds": 10.0, '
        b'"human_seconds": 5.0, "work_seconds": 15.0, "ai_inclusive_saved_seconds": 45.0, '
        b'"human_freed_seconds": 55.0}], "totals": {"manual_baseline_seconds": 60.0, "ai_seconds": 10.0, '
        b'"human_seconds": 5.0, "work_seconds": 15.0, "ai_inclusive_saved_seconds": 45.0, '
        b'"human_freed_seconds": 55.0}}, {"collection_id": "latest", "stage": "live", "steps": '
        b'[{"action": "post-publish", "status": "success", "manual_baseline_seconds": 120.0, '
        b'"ai_seconds": 20.0, "human_seconds": 10.0, "work_seconds": 30.0, '
        b'"ai_inclusive_saved_seconds": 90.0, "human_freed_seconds": 110.0}], "totals": '
        b'{"manual_baseline_seconds": 120.0, "ai_seconds": 20.0, "human_seconds": 10.0, '
        b'"work_seconds": 30.0, "ai_inclusive_saved_seconds": 90.0, "human_freed_seconds": 110.0}}]}}'
    )
    assert publications.replace(channel_id_bytes, b"<channel-id>") == (
        b'{"days": {"2026-07-20": 2}, "channels": [{"id": "<channel-id>", "name": "Night Drive", '
        b'"status": "refresh_failed", "fetched_at": "2026-07-20T13:00:00+00:00", '
        b'"timezone": "Asia/Tokyo", "days": {"2026-07-20": 2}, "error": '
        b'{"code": "publication_refresh_failed", "message": "quota exceeded", '
        b'"attempted_at": "2026-07-20T14:00:00+00:00"}}]}'
    )
    assert json.loads(trends)["channels"][0]["name"] == "Night Drive"


def test_server_exposes_overview_and_channel_detail(dashboard_server: str):
    status, overview = _json(f"{dashboard_server}/api/channels")
    channel = overview["channels"][0]

    assert status == 200
    assert overview["schema_version"] == 2
    assert channel["name"] == "Night Drive"
    assert channel["video_count"] == 1
    assert "workflow_timing" not in channel
    detail_status, detail = _json(f"{dashboard_server}/api/channels/{channel['id']}")
    assert detail_status == 200
    assert detail["videos"][0]["title"] == "Midnight"
    assert detail["workflow_timing"]["status"] == "ready"
    active, latest = detail["workflow_timing"]["collections"]
    assert (active["collection_id"], active["stage"], active["totals"]["work_seconds"]) == (
        "active",
        "planning",
        15,
    )
    assert (latest["collection_id"], latest["stage"], latest["totals"]["work_seconds"]) == (
        "latest",
        "live",
        30,
    )


def test_server_exposes_pipeline_state_from_same_origin(dashboard_server: str) -> None:
    status, pipeline = _json(f"{dashboard_server}/api/pipeline")

    assert status == 200
    assert pipeline["channels"][0]["name"] == "Night Drive"
    assert [item["collection_id"] for item in pipeline["channels"][0]["collections"]] == ["active", "latest"]


def test_server_exposes_saved_publication_read_model(dashboard_server: str) -> None:
    status, payload = _json(f"{dashboard_server}/api/publications")

    assert status == 200
    assert payload["days"] == {"2026-07-20": 2}
    assert len(payload["channels"]) == 1
    channel = payload["channels"][0]
    assert channel["name"] == "Night Drive"
    assert channel["status"] == "refresh_failed"
    assert channel["fetched_at"] == "2026-07-20T13:00:00+00:00"
    assert channel["days"] == {"2026-07-20": 2}
    assert channel["error"] == {
        "code": "publication_refresh_failed",
        "message": "quota exceeded",
        "attempted_at": "2026-07-20T14:00:00+00:00",
    }


@pytest.mark.parametrize(
    ("timing_state", "expected_status", "expected_code"),
    [
        ("unavailable", "unavailable", None),
        ("error", "error", "workflow_timing_failed"),
    ],
)
def test_server_keeps_analytics_payload_when_workflow_timing_is_unavailable_or_error(
    tmp_path: Path,
    timing_state: str,
    expected_status: str,
    expected_code: str | None,
) -> None:
    channel = _write_channel(tmp_path)
    if timing_state == "unavailable":
        history_path = channel / ".automation-run" / "history.json"
        history_path.write_text(json.dumps({"schema_version": 1, "attempts": []}), encoding="utf-8")
    else:
        (channel / ".automation-run" / "history.json").write_text("not-json", encoding="utf-8")
    server = create_server(port=0, channel_paths=[channel])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        overview_status, overview = _json(f"{base_url}/api/channels")
        overview_channel = overview["channels"][0]
        detail_status, detail = _json(f"{base_url}/api/channels/{overview_channel['id']}")

        assert overview_status == detail_status == 200
        assert overview["schema_version"] == 2
        assert overview_channel["summary"]["views"] == 123
        assert "workflow_timing" not in overview_channel
        assert detail["summary"]["views"] == 123
        assert detail["videos"][0]["title"] == "Midnight"
        assert detail["workflow_timing"]["status"] == expected_status
        if expected_code is not None:
            assert detail["workflow_timing"]["error"]["code"] == expected_code
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_server_isolates_corrupt_history_from_healthy_channel(tmp_path: Path) -> None:
    corrupt = _write_channel(tmp_path / "corrupt-root")
    healthy = _write_channel(tmp_path / "healthy-root")
    (corrupt / ".automation-run" / "history.json").write_text("not-json", encoding="utf-8")

    server = create_server(port=0, channel_paths=[corrupt, healthy])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        overview_status, overview = _json(f"{base_url}/api/channels")
        corrupt_overview, healthy_overview = overview["channels"]
        corrupt_status, corrupt_detail = _json(f"{base_url}/api/channels/{corrupt_overview['id']}")
        healthy_status, healthy_detail = _json(f"{base_url}/api/channels/{healthy_overview['id']}")

        assert overview_status == corrupt_status == healthy_status == 200
        assert corrupt_overview["summary"]["views"] == 123
        assert corrupt_detail["videos"][0]["title"] == "Midnight"
        assert corrupt_detail["workflow_timing"]["status"] == "error"
        assert healthy_overview["summary"]["views"] == 123
        assert healthy_detail["videos"][0]["title"] == "Midnight"
        assert healthy_detail["workflow_timing"]["status"] == "ready"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_server_exposes_workflow_timing_failure_reason(tmp_path: Path) -> None:
    channel = _write_channel(tmp_path)
    state_path = channel / "collections" / "live" / "latest" / "workflow-state.json"
    state_path.write_text(json.dumps({"phase": "live", "created_at": "2026-07-20"}), encoding="utf-8")

    server = create_server(port=0, channel_paths=[channel])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        _, overview = _json(f"{base_url}/api/channels")
        _, detail = _json(f"{base_url}/api/channels/{overview['channels'][0]['id']}")

        assert detail["workflow_timing"] == {
            "status": "error",
            "collections": [],
            "error": {"code": "workflow_timing_failed", "message": "未対応 phase です: 'live'"},
        }
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_server_exposes_active_lease_without_collection_as_in_progress(tmp_path: Path) -> None:
    channel = _write_channel(tmp_path)
    for state_path in channel.glob("collections/*/*/workflow-state.json"):
        state_path.unlink()
    lease = channel / ".automation-run" / "lease"
    lease.mkdir()
    (lease / "lease.json").write_text(
        json.dumps({"token": "active", "acquired_at": 0, "expires_at": 4_102_444_800}),
        encoding="utf-8",
    )

    server = create_server(port=0, channel_paths=[channel])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        _, overview = _json(f"{base_url}/api/channels")
        status, detail = _json(f"{base_url}/api/channels/{overview['channels'][0]['id']}")

        assert status == 200
        assert detail["summary"]["views"] == 123
        assert detail["videos"][0]["title"] == "Midnight"
        assert detail["workflow_timing"] == {"status": "in_progress", "collections": []}
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("path", ["/api/unknown", "/api/channels/not-registered"])
def test_server_returns_json_404_for_unknown_api(dashboard_server: str, path: str):
    with pytest.raises(HTTPError) as exc_info:
        urlopen(f"{dashboard_server}{path}", timeout=5)

    assert exc_info.value.code == 404
    assert exc_info.value.headers.get_content_type() == "application/json"
    assert json.loads(exc_info.value.read())["error"]["code"] == "not_found"


def test_server_serves_assets_and_spa_fallback(dashboard_server: str):
    with urlopen(f"{dashboard_server}/app.js", timeout=5) as response:
        assert response.headers.get_content_type() == "text/javascript"
    with urlopen(f"{dashboard_server}/channels/example", timeout=5) as response:
        assert response.read() == b"<main>dashboard shell</main>"


def test_server_rejects_asset_path_traversal(dashboard_server: str):
    with pytest.raises(HTTPError) as exc_info:
        urlopen(f"{dashboard_server}/%2e%2e/app.js", timeout=5)

    assert exc_info.value.code == 404
    assert json.loads(exc_info.value.read())["error"]["message"] == "asset が見つかりません"


def test_server_returns_404_when_spa_index_is_missing(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    server = create_server(port=0, asset_root=assets, channel_paths=[])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"http://127.0.0.1:{server.server_port}/missing", timeout=5)

        assert exc_info.value.code == 404
        assert json.loads(exc_info.value.read())["error"]["message"] == "dashboard build asset が見つかりません"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_cli_opens_loopback_url_after_server_starts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    opened: list[str] = []
    events: list[str] = []
    channels = [tmp_path / "one", tmp_path / "two"]
    refresh_errors = {channels[1]: "authentication failed"}

    class FakeServer:
        server_port = 4321

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr("youtube_automation.commands.analytics.dashboard.load_channel_registry", lambda _path: channels)
    monkeypatch.setattr(
        "youtube_automation.commands.analytics.dashboard.refresh_dashboard_channels",
        lambda paths, **_kwargs: (
            events.append("refresh") or refresh_errors if paths == channels else pytest.fail("wrong paths")
        ),
    )

    def create_server(**kwargs):
        events.append("server")
        assert kwargs["channel_paths"] == channels
        assert kwargs["refresh_errors"] == refresh_errors
        return FakeServer()

    monkeypatch.setattr("youtube_automation.commands.analytics.dashboard.create_server", create_server)
    monkeypatch.setattr("youtube_automation.commands.analytics.dashboard.webbrowser.open", opened.append)

    assert main(["--port", "4321", "--open", "--registry", str(tmp_path / "channels.json")]) == 0
    assert events == ["refresh", "server"]
    assert opened == ["http://127.0.0.1:4321/"]


def test_cli_refresh_publications_forces_every_channel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    channels = [tmp_path / "one", tmp_path / "two"]
    collected: list[tuple[Path, bool]] = []

    class FakeServer:
        server_port = 4321

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr("youtube_automation.commands.analytics.dashboard.load_channel_registry", lambda _path: channels)

    def refresh_channels(paths: list[Path], *, collect_channel) -> dict[Path, str]:
        for path in paths:
            collect_channel(path)
        return {}

    def collect_analytics(
        channel: Path,
        _factory,
        *,
        force_publication_refresh: bool,
    ) -> None:
        collected.append((channel, force_publication_refresh))

    monkeypatch.setattr(
        "youtube_automation.commands.analytics.dashboard.refresh_dashboard_channels",
        refresh_channels,
    )
    monkeypatch.setattr(
        "youtube_automation.commands.analytics.dashboard.collect_channel_analytics",
        collect_analytics,
    )
    monkeypatch.setattr(
        "youtube_automation.commands.analytics.dashboard.create_server",
        lambda **_kwargs: FakeServer(),
    )

    assert main(["--refresh-publications", "--registry", str(tmp_path / "channels.json")]) == 0
    assert collected == [(channels[0], True), (channels[1], True)]


def test_cli_skip_refresh_starts_from_existing_snapshots_without_api_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    channels = [tmp_path / "one"]
    api_calls: list[str] = []

    class FakeServer:
        server_port = 4321

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr("youtube_automation.commands.analytics.dashboard.load_channel_registry", lambda _path: channels)

    def refresh_channels(paths: list[Path], *, collect_channel) -> dict[Path, str]:
        api_calls.append("channel refresh")
        collect_channel(paths[0])
        return {}

    monkeypatch.setattr(
        "youtube_automation.commands.analytics.dashboard.refresh_dashboard_channels",
        refresh_channels,
    )
    monkeypatch.setattr(
        "youtube_automation.commands.analytics.dashboard.collect_channel_analytics",
        lambda _channel, _factory, *, force_publication_refresh: api_calls.append(
            f"publication collector force={force_publication_refresh}"
        ),
    )
    monkeypatch.setattr(
        "youtube_automation.commands.analytics.dashboard.create_server",
        lambda **kwargs: (
            FakeServer()
            if kwargs["channel_paths"] == channels and kwargs["refresh_errors"] == {}
            else pytest.fail("wrong server input")
        ),
    )

    assert (
        main(
            [
                "--skip-refresh",
                "--refresh-publications",
                "--registry",
                str(tmp_path / "channels.json"),
            ]
        )
        == 0
    )
    assert api_calls == []


@pytest.mark.parametrize("port", [0, 65535])
def test_cli_accepts_port_boundaries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, port: int):
    received = []

    class FakeServer:
        server_port = 4321

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr("youtube_automation.commands.analytics.dashboard.load_channel_registry", lambda _path: [])
    monkeypatch.setattr(
        "youtube_automation.commands.analytics.dashboard.create_server",
        lambda **kwargs: received.append(kwargs["port"]) or FakeServer(),
    )

    assert main(["--skip-refresh", "--port", str(port), "--registry", str(tmp_path / "channels.json")]) == 0
    assert received == [port]


@pytest.mark.parametrize("port", [-1, 65536])
def test_cli_rejects_ports_outside_valid_range(tmp_path: Path, port: int):
    with pytest.raises(SystemExit) as exc_info:
        main(["--skip-refresh", "--port", str(port), "--registry", str(tmp_path / "channels.json")])

    assert exc_info.value.code == 2
