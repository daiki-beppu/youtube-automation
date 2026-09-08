"""Static asset delivery shared by loopback SPA servers."""

import mimetypes
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from importlib.resources.abc import Traversable
from pathlib import PurePosixPath
from urllib.parse import unquote


def serve_spa_asset(
    handler: BaseHTTPRequestHandler,
    asset_root: Traversable,
    path: str,
    *,
    on_invalid_path: Callable[[], None],
    on_missing_build: Callable[[], None],
    send_headers: Callable[[], None],
) -> None:
    """Serve a packaged file or SPA shell using the application's response policies."""
    relative_path = unquote(path).lstrip("/") or "index.html"
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        on_invalid_path()
        return
    resource = asset_root
    for part in pure_path.parts:
        resource = resource.joinpath(part)
    if not resource.is_file():
        resource = asset_root.joinpath("index.html")
    if not resource.is_file():
        on_missing_build()
        return
    body = resource.read_bytes()
    content_type, _ = mimetypes.guess_type(str(resource))
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type or "application/octet-stream")
    handler.send_header("Content-Length", str(len(body)))
    send_headers()
    handler.end_headers()
    handler.wfile.write(body)
