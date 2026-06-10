#!/usr/bin/env python3
"""yt-collection-serve: コレクション成果物をローカル HTTP で Chrome 拡張へ配信する.

issue #698: #692 の `yt-suno-serve` を一般化し、エンドポイントをサブパス分離する。

- `GET /suno/prompts.json` … suno-prompts.json 配列 JSON（#692 契約不変）
- `GET /distrokid/release.json` … profile + collection 動的データのマージ JSON
- `GET /distrokid/assets/<path>` … 曲・ジャケットファイルの binary 配信

`distrokid` が None または `enabled == False` のとき `/distrokid/*` は 404。
CORS はデフォルトで Chrome 拡張オリジン (`chrome-extension://...`) と helper サイト
web origin (`https://suno.com` / `https://distrokid.com` 系) を許可し、全ルートで
同一ポリシー。`--allow-origin` 指定時はその値との完全一致のみに lock する。
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
    COLLECTIONS_ROUTE,
    DOCUMENTATION_DIRNAME,
    SUNO_PROMPTS_JSON_FILENAME,
    SUNO_PROMPTS_ROUTE,
)
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.config import Distrokid, load_config
from youtube_automation.utils.exceptions import ConfigError

DEFAULT_PORT = 7873
_EXTENSION_ORIGIN_SCHEME = "chrome-extension://"
# overlay 化（#892/#895）で content script の fetch が page origin になったため、
# helper 拡張がホストされる web origin をデフォルト許可する（#896）。完全一致のみ。
_DEFAULT_ALLOWED_WEB_ORIGINS = frozenset(
    {
        "https://suno.com",
        "https://www.suno.com",
        "https://distrokid.com",
        "https://www.distrokid.com",
    }
)
# `collections/planning/` 配下で 1 コレクションを示すディレクトリ接尾辞。
_COLLECTION_DIR_SUFFIX = "-collection"


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


def find_collection_dirs(root: Path) -> list[Path]:
    """`root` 直下の `*-collection` ディレクトリのみを名前昇順で返す（#816 dir mode）.

    `collections/planning/` 配下には `01-master` 等の非コレクションや雑多なファイルが
    混在しうるため、接尾辞 `-collection` を持つディレクトリだけをホワイトリスト採用する。
    `root` が存在しない / ディレクトリでない場合は空リスト。
    """
    if not root.is_dir():
        return []
    dirs = (p for p in root.iterdir() if p.is_dir() and p.name.endswith(_COLLECTION_DIR_SUFFIX))
    return sorted(dirs, key=lambda p: p.name)


def build_collections_index(root: Path) -> list[dict]:
    """各 collection を `{id, name, has_prompts, pattern_count}` に写像する（#816 dir mode）.

    - id   = ディレクトリ名（拡張から個別 fetch する際のホワイトリスト key）
    - name = `CollectionPaths.collection_name`（日付＋チャンネル接頭辞を除去した表示名）
    - has_prompts   = `<dir>/20-documentation/suno-prompts.json` の存在
    - pattern_count = json があれば entries 数、無ければ None
    """
    index: list[dict] = []
    for coll in find_collection_dirs(root):
        prompts_path = coll / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
        has_prompts = prompts_path.is_file()
        pattern_count = len(json.loads(prompts_path.read_text(encoding="utf-8"))) if has_prompts else None
        index.append(
            {
                "id": coll.name,
                "name": CollectionPaths(coll).collection_name,
                "has_prompts": has_prompts,
                "pattern_count": pattern_count,
            }
        )
    return index


def resolve_collection_prompts_path(root: Path, cid: str) -> Path | None:
    """`cid` が既知の collection dir 名のとき docs json パスを返す（#816 dir mode）.

    未知 id / パストラバーサル文字列は `find_collection_dirs` のホワイトリストに
    一致せず None を返す（fail-loud でなく 404 化できる形）。json の実在判定は
    呼び出し側に委ねる（has_prompts=False の collection も dir 自体は既知）。
    """
    known = {coll.name for coll in find_collection_dirs(root)}
    if cid not in known:
        return None
    return root / cid / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME


def is_origin_allowed(origin: str | None, allow_origin: str | None) -> bool:
    """CORS 判定.

    allow_origin=None なら `chrome-extension://` scheme と helper サイト web origin
    （suno.com / distrokid.com、完全一致）を許可する（#896）。
    allow_origin 指定時はその値との完全一致のみ許可する（lock 維持）。
    """
    if not origin:
        return False
    if allow_origin is not None:
        return origin == allow_origin
    if origin.startswith(_EXTENSION_ORIGIN_SCHEME):
        return True
    return origin in _DEFAULT_ALLOWED_WEB_ORIGINS


def create_server(
    port: int,
    allow_origin: str | None,
    *,
    prompts_path: Path | None,
    collection_dir: Path | None,
    distrokid: Distrokid | None,
    collections_root: Path | None = None,
    distrokid_source: str | None = None,
) -> ThreadingHTTPServer:
    """サブパス分離した GET / CORS preflight を返すサーバーを生成する.

    `collections_root` 指定時は **dir mode**（`/collections` 系を配信し
    単一ファイル mode の `/suno/prompts.json` は配信しない）。既定 None は
    単一ファイル mode（`/suno/prompts.json` + `/distrokid/*`）。

    distrokid が None または `enabled == False` のとき `/distrokid/*` は 404。
    """
    dir_mode = collections_root is not None
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
            if dir_mode:
                self._serve_dir_mode()
                return
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

        def _serve_dir_mode(self) -> None:
            if self.path == COLLECTIONS_ROUTE:
                body = json.dumps(build_collections_index(collections_root)).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            prefix = f"{COLLECTIONS_ROUTE}/"
            if self.path.startswith(prefix) and self.path.endswith(SUNO_PROMPTS_ROUTE):
                cid = self.path[len(prefix) : -len(SUNO_PROMPTS_ROUTE)]
                resolved = resolve_collection_prompts_path(collections_root, cid)
                if resolved is None or not resolved.is_file():
                    self.send_error(404, "Not Found")
                    return
                self._send_bytes(resolved.read_bytes(), "application/json; charset=utf-8")
                return
            self.send_error(404, "Not Found")

        def _serve_distrokid_release(self) -> None:
            if not distrokid_enabled:
                self.send_error(404, "Not Found")
                return
            payload = build_release_payload(collection_dir, distrokid, distrokid_source=distrokid_source)
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
        help=(
            "lock CORS to a single origin via exact match (default: allow any "
            "chrome-extension scheme plus the suno.com / distrokid.com helper origins)"
        ),
    )
    parser.add_argument(
        "--distrokid-source",
        default=None,
        help=(
            "submit a 30-distrokid disc dir as one album, e.g. "
            "'30-distrokid/disc1-coding-focus-vol1' (default: 02-Individual-music/)"
        ),
    )
    args = parser.parse_args()

    # path が `*-collection/` を並べたディレクトリなら dir mode（#816）。
    collection_dirs = find_collection_dirs(args.path)
    if collection_dirs:
        server = create_server(
            args.port,
            args.allow_origin,
            prompts_path=None,
            collection_dir=None,
            distrokid=None,
            collections_root=args.path,
        )
        port = server.server_address[1]
        print(
            f"Serving {len(collection_dirs)} collections from {args.path} at http://localhost:{port}{COLLECTIONS_ROUTE}"
        )
    else:
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
            distrokid_source=args.distrokid_source,
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
