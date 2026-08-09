from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from youtube_automation.commands.analytics.dashboard import create_server, main


def _write_channel(root: Path) -> Path:
    channel = root / "channel"
    (channel / "config" / "channel").mkdir(parents=True)
    (channel / "data").mkdir()
    (channel / "config" / "channel" / "meta.json").write_text(
        json.dumps({"channel": {"name": "Night Drive"}}), encoding="utf-8"
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
    (channel / "data" / "dashboard_publications.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fetched_at": "2026-07-20T13:00:00+00:00",
                "timezone": "Asia/Tokyo",
                "days": {"2026-07-20": 2},
                "error": {
                    "code": "publication_refresh_failed",
                    "message": "quota exceeded",
                    "attempted_at": "2026-07-20T14:00:00+00:00",
                },
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


def test_server_exposes_overview_and_channel_detail(dashboard_server: str):
    status, overview = _json(f"{dashboard_server}/api/channels")
    channel = overview["channels"][0]

    assert status == 200
    assert channel["name"] == "Night Drive"
    assert channel["video_count"] == 1
    detail_status, detail = _json(f"{dashboard_server}/api/channels/{channel['id']}")
    assert detail_status == 200
    assert detail["videos"][0]["title"] == "Midnight"


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
