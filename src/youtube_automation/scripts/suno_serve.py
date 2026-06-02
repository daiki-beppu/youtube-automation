#!/usr/bin/env python3
"""yt-suno-serve: suno-prompts.json をローカル HTTP で Chrome 拡張へ配信する.

issue #692: コレクションディレクトリまたは suno-prompts.json パスを引数に取り、
`http://localhost:<PORT>/prompts.json` で JSON を返すフォアグラウンドサーバー。
CORS は Chrome 拡張オリジン (`chrome-extension://...`) のみ許可する。
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from youtube_automation.scripts.suno_artifacts import (
    DOCUMENTATION_DIRNAME,
    SUNO_PROMPTS_JSON_FILENAME,
)
from youtube_automation.utils.exceptions import ConfigError

DEFAULT_PORT = 7873
PROMPTS_ROUTE = "/prompts.json"
_EXTENSION_ORIGIN_SCHEME = "chrome-extension://"


def resolve_prompts_path(path: Path) -> Path:
    """引数パスを suno-prompts.json の実体パスへ解決する.

    - ファイルパス → そのまま返す
    - ディレクトリ → `<dir>/20-documentation/suno-prompts.json`（存在すれば）
    - 不在 / json が見つからない → ConfigError（fail-loud、silent 続行しない）
    """
    if path.is_file():
        return path
    if path.is_dir():
        candidate = path / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
        if candidate.is_file():
            return candidate
        raise ConfigError(f"{SUNO_PROMPTS_JSON_FILENAME} not found under {path}")
    raise ConfigError(f"path does not exist: {path}")


def is_origin_allowed(origin: str | None, allow_origin: str | None) -> bool:
    """CORS 判定.

    allow_origin=None なら `chrome-extension://` scheme を許可する。
    allow_origin 指定時はその値との完全一致のみ許可する。
    """
    if not origin:
        return False
    if allow_origin is not None:
        return origin == allow_origin
    return origin.startswith(_EXTENSION_ORIGIN_SCHEME)


def create_server(json_path: Path, port: int, allow_origin: str | None) -> ThreadingHTTPServer:
    """`GET /prompts.json` と CORS preflight を返すサーバーを生成する."""

    class _Handler(BaseHTTPRequestHandler):
        def _allowed_origin(self) -> str | None:
            origin = self.headers.get("Origin")
            return origin if is_origin_allowed(origin, allow_origin) else None

        def _send_cors(self, origin: str | None) -> None:
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def do_OPTIONS(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler 規約)
            origin = self._allowed_origin()
            self.send_response(204)
            self._send_cors(origin)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path != PROMPTS_ROUTE:
                self.send_error(404, "Not Found")
                return
            body = json_path.read_bytes()
            origin = self._allowed_origin()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors(origin)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # サーバーログを抑制
            pass

    return ThreadingHTTPServer(("localhost", port), _Handler)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve suno-prompts.json over localhost HTTP for the suno-helper Chrome extension.",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="collection dir or suno-prompts.json path",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--allow-origin",
        default=None,
        help="lock CORS to a single chrome-extension://<id> origin (default: allow any chrome-extension scheme)",
    )
    args = parser.parse_args()

    json_path = resolve_prompts_path(args.path)
    server = create_server(json_path, args.port, args.allow_origin)
    port = server.server_address[1]
    print(f"Serving {json_path} at http://localhost:{port}{PROMPTS_ROUTE}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
