#!/usr/bin/env python3
"""yt-collection-serve: コレクション成果物をローカル HTTP で Chrome 拡張へ配信する.

issue #698: #692 の `yt-suno-serve` を一般化し、エンドポイントをサブパス分離する。

- `GET /suno/prompts.json` … suno-prompts.json 配列 JSON（#692 契約不変）
- `GET /distrokid/release.json` … profile + collection 動的データのマージ JSON
- `GET /distrokid/assets/<path>` … 曲・ジャケットファイルの binary 配信

`distrokid` が None または `enabled == False` のとき `/distrokid/*` は 404。
CORS は Chrome 拡張オリジン (`chrome-extension://...`) のみ許可し、全ルートで同一ポリシー。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from youtube_automation.scripts.distrokid_release import (
    DISTROKID_ASSETS_PREFIX,
    DISTROKID_RELEASE_ROUTE,
    build_release_payload,
    resolve_asset_path,
)
from youtube_automation.scripts.suno_artifacts import (
    DOCUMENTATION_DIRNAME,
    SUNO_PROMPTS_JSON_FILENAME,
    SUNO_PROMPTS_ROUTE,
)
from youtube_automation.utils.config import Distrokid, load_config
from youtube_automation.utils.exceptions import ConfigError

DEFAULT_PORT = 7873
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


def create_server(
    port: int,
    allow_origin: str | None,
    *,
    prompts_path: Path,
    collection_dir: Path,
    distrokid: Distrokid | None,
) -> ThreadingHTTPServer:
    """サブパス分離した GET / CORS preflight を返すサーバーを生成する.

    distrokid が None または `enabled == False` のとき `/distrokid/*` は 404。
    """
    distrokid_enabled = distrokid is not None and distrokid.enabled

    class _Handler(BaseHTTPRequestHandler):
        def _allowed_origin(self) -> str | None:
            origin = self.headers.get("Origin")
            return origin if is_origin_allowed(origin, allow_origin) else None

        def _send_cors(self, origin: str | None) -> None:
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send_bytes(self, body: bytes, content_type: str) -> None:
            origin = self._allowed_origin()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self._send_cors(origin)
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler 規約)
            origin = self._allowed_origin()
            self.send_response(204)
            self._send_cors(origin)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path == SUNO_PROMPTS_ROUTE:
                self._send_bytes(prompts_path.read_bytes(), "application/json; charset=utf-8")
                return
            if self.path == DISTROKID_RELEASE_ROUTE:
                self._serve_distrokid_release()
                return
            if self.path.startswith(DISTROKID_ASSETS_PREFIX):
                self._serve_distrokid_asset()
                return
            self.send_error(404, "Not Found")

        def _serve_distrokid_release(self) -> None:
            if not distrokid_enabled:
                self.send_error(404, "Not Found")
                return
            payload = build_release_payload(collection_dir, distrokid)
            body = json.dumps(payload).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8")

        def _serve_distrokid_asset(self) -> None:
            if not distrokid_enabled:
                self.send_error(404, "Not Found")
                return
            relpath = self.path[len(DISTROKID_ASSETS_PREFIX) :]
            resolved = resolve_asset_path(collection_dir, relpath)
            if resolved is None:
                self.send_error(404, "Not Found")
                return
            content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
            self._send_bytes(resolved.read_bytes(), content_type)

        def log_message(self, *args) -> None:  # サーバーログを抑制
            pass

    return ThreadingHTTPServer(("localhost", port), _Handler)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Serve collection artifacts over localhost HTTP for the suno-helper / "
            "distrokid-helper Chrome extensions (subpaths: /suno/*, /distrokid/*)."
        ),
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

    prompts_path = resolve_prompts_path(args.path)
    # collection dir: dir 引数はそのまま、json ファイル引数なら <collection>/20-documentation/x.json から 2 階層上。
    collection_dir = args.path if args.path.is_dir() else args.path.parent.parent
    distrokid = load_config().distrokid

    server = create_server(
        args.port,
        args.allow_origin,
        prompts_path=prompts_path,
        collection_dir=collection_dir,
        distrokid=distrokid,
    )
    port = server.server_address[1]
    print(f"Serving {collection_dir} at http://localhost:{port}{SUNO_PROMPTS_ROUTE}")
    if distrokid.enabled:
        print(f"  distrokid endpoints enabled: {DISTROKID_RELEASE_ROUTE}, {DISTROKID_ASSETS_PREFIX}<path>")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
