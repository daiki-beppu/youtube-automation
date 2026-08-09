"""収集済み Analytics を表示する loopback 限定 dashboard server。"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import webbrowser
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import unquote, urlsplit

from youtube_automation.commands.analytics.analytics_system import AnalyticsSystem
from youtube_automation.configuration.loader import load_config_from_path
from youtube_automation.core.errors import ConfigError, DashboardChannelNotFoundError
from youtube_automation.infrastructure.analytics.channel_registry import (
    DEFAULT_CHANNEL_REGISTRY,
    load_channel_registry,
)
from youtube_automation.infrastructure.analytics.dashboard_read_model import DashboardAPI, build_dashboard_read_model
from youtube_automation.infrastructure.analytics.dashboard_refresh import (
    collect_channel_analytics,
    refresh_dashboard_channels,
)
from youtube_automation.infrastructure.analytics.workflow_timing import build_workflow_timing

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _build_channel_workflow_timing(channel: Path) -> dict[str, object] | None:
    try:
        collection_states = (
            state_path
            for stage in ("planning", "live")
            for state_path in (channel / "collections" / stage).glob("*/workflow-state.json")
        )
        if next(collection_states, None) is None:
            timing = build_workflow_timing(channel, None)
            if timing.get("status") == "in_progress":
                return timing
            return {"status": "unavailable", "reason": "collection_missing", "collections": []}
        config = load_config_from_path(channel)
        return build_workflow_timing(channel, config.workflow.manual_baseline_minutes)
    except (ConfigError, OSError, ValueError):
        return None


class DashboardServer(ThreadingHTTPServer):
    """dashboard service と静的 asset を保持する HTTP server。"""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], api: DashboardAPI, asset_root: Traversable) -> None:
        super().__init__(address, DashboardRequestHandler)
        self.api = api
        self.asset_root = asset_root


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self, message: str) -> None:
        self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": message}})

    def _api(self, path: str) -> bool:
        if path == "/api/channels":
            self._json(HTTPStatus.OK, self.server.api.overview())
            return True
        if path == "/api/publications":
            self._json(HTTPStatus.OK, cast(dict[str, object], self.server.api.model["publications"]))
            return True
        prefix = "/api/channels/"
        if path.startswith(prefix):
            channel_id = unquote(path.removeprefix(prefix))
            try:
                payload = self.server.api.channel(channel_id)
            except DashboardChannelNotFoundError:
                self._not_found(f"dashboard channel が見つかりません: {channel_id}")
            else:
                self._json(HTTPStatus.OK, payload)
            return True
        if path.startswith("/api/"):
            self._not_found(f"API path が見つかりません: {path}")
            return True
        return False

    def _resource(self, relative_path: str) -> Traversable | None:
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            return None
        resource = self.server.asset_root
        for part in pure_path.parts:
            resource = resource.joinpath(part)
        return resource

    def _static(self, path: str) -> None:
        relative_path = unquote(path).lstrip("/") or "index.html"
        resource = self._resource(relative_path)
        if resource is None:
            self._not_found("asset が見つかりません")
            return
        if not resource.is_file():
            resource = self._resource("index.html")
        if resource is None or not resource.is_file():
            self._not_found("dashboard build asset が見つかりません")
            return
        body = resource.read_bytes()
        content_type, _ = mimetypes.guess_type(str(resource))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if not self._api(path):
            self._static(path)


def create_server(
    *,
    port: int = DEFAULT_PORT,
    registry_path: Path | None = None,
    asset_root: Traversable | None = None,
    channel_paths: list[Path] | None = None,
    refresh_errors: dict[Path, str] | None = None,
) -> DashboardServer:
    """registry を一度読み、loopback にだけ bind する server を作る。"""
    channels = channel_paths if channel_paths is not None else load_channel_registry(registry_path)
    workflow_timings = {channel: _build_channel_workflow_timing(channel) for channel in channels}
    api = DashboardAPI(
        build_dashboard_read_model(
            channels,
            refresh_errors=refresh_errors,
            workflow_timing_by_channel=workflow_timings,
        )
    )
    resolved_assets = asset_root or files("youtube_automation").joinpath("dashboard_dist")
    return DashboardServer((DEFAULT_HOST, port), api, resolved_assets)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="全チャンネルを更新して Analytics dashboard をローカル配信します")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"配信 port（default: {DEFAULT_PORT}）")
    parser.add_argument("--open", action="store_true", help="起動後に既定 browser で開きます")
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="API更新を行わず既存snapshotを表示します（offline test用）",
    )
    parser.add_argument(
        "--refresh-publications",
        action="store_true",
        help="fresh cache があっても公開履歴を再取得します",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_CHANNEL_REGISTRY,
        help="絶対 path の channel registry JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        _parser().error("--port は 0..65535 で指定してください")
    registry_path = cast(Path, args.registry)
    channels = load_channel_registry(registry_path)
    refresh_errors = (
        {}
        if args.skip_refresh
        else refresh_dashboard_channels(
            channels,
            collect_channel=lambda channel: collect_channel_analytics(
                channel,
                AnalyticsSystem,
                force_publication_refresh=args.refresh_publications,
            ),
        )
    )
    server = create_server(
        port=args.port,
        registry_path=registry_path,
        channel_paths=channels,
        refresh_errors=refresh_errors,
    )
    url = f"http://{DEFAULT_HOST}:{server.server_port}/"
    print(f"dashboard: {url}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
