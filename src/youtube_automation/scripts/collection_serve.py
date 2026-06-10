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
import os
import re
import tempfile
from datetime import datetime, timezone
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
    SUNO_PLAYLISTS_ROUTE,
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

# Suno playlist capture の出力先（`<root>/config/suno-playlists.json`）と env fallback 名（#893）。
_PLAYLISTS_OUTPUT_RELPATH = Path("config") / "suno-playlists.json"
_PLAYLIST_CAPTURE_ROOT_ENV = "PLAYLIST_CAPTURE_ROOT"
_PLAYLIST_CAPTURE_PREFIX_ENV = "PLAYLIST_CAPTURE_PREFIX"


def playlists_output_path(root: Path) -> Path:
    """capture 出力先 JSON の実体パス `<root>/config/suno-playlists.json` を返す（#893）。"""
    return root / _PLAYLISTS_OUTPUT_RELPATH


def _slugify(text: str) -> str:
    """テーマ文字列を小文字・連続空白畳み込みの slug にする（#893）。

    前後空白を除去し、連続空白を `-` 1 つに畳み込み、小文字化する。
    既にハイフン区切りの文字列（collection dir 由来）は空白が無いため不変。
    """
    return re.sub(r"\s+", "-", text.strip().lower())


def normalize_suno_title(title: str, prefix: str) -> str | None:
    """`<prefix> | <theme>` を `<prefix>-<theme-slug>` に正規化する（#893 要件3）。

    prefix はパイプ直前トークンと完全一致する必要がある（部分一致は弾く）。大小無視、
    パイプ前後の空白は任意、theme の連続空白は `-` に畳み込む。prefix 不一致・
    パイプ無しは None（channel-agnostic フィルタはこの純関数に閉じる）。
    """
    pattern = re.compile(rf"^{re.escape(prefix)}\s*\|\s*(.+)$", re.IGNORECASE)
    match = pattern.match(title.strip())
    if match is None:
        return None
    theme_slug = _slugify(match.group(1))
    if not theme_slug:
        return None
    return f"{prefix.lower()}-{theme_slug}"


def derive_collection_slug(collection_id: str, prefix: str) -> str | None:
    """collection dir 名から `<prefix>-<theme-slug>` を導出する（#893 要件 B）。

    `<date>-<channel>-<theme>-collection` 形式から日付・接尾辞を剥がし、theme を
    `normalize_suno_title` と同じ slug 形へ写像する（マージキー突合の不変条件）。
    """
    name = collection_id
    if name.endswith(_COLLECTION_DIR_SUFFIX):
        name = name[: -len(_COLLECTION_DIR_SUFFIX)]
    # `<date>-<channel>-<theme...>` の date と channel を剥がす（CollectionPaths.collection_name と同方針）。
    parts = name.split("-", 2)
    if len(parts) >= 3 and parts[0].isdigit():
        name = parts[2]
    theme_slug = _slugify(name)
    if not theme_slug:
        return None
    return f"{prefix.lower()}-{theme_slug}"


def _read_playlists_json(target: Path) -> dict:
    """既存 capture JSON を dict で読む。不在・破損・非 dict は空 dict 扱い（#893）。"""
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def read_mapped_slugs(root: Path) -> set[str]:
    """既存 `<root>/config/suno-playlists.json` の slug 集合を返す（#893 要件 B）。

    不在・破損は空集合（fail-loud せず「未マッピング」として扱う）。
    """
    return set(_read_playlists_json(playlists_output_path(root)).keys())


def write_suno_playlists(root: Path, payload: list[dict], *, prefix: str) -> int:
    """capture した playlist を `<root>/config/suno-playlists.json` へ atomic merge write する（#893 要件4）。

    prefix 不一致 item は skip、同 slug は captured_at 後勝ちで上書き、既存 JSON 破損は
    空 dict 扱いで再作成する。`tempfile.mkstemp` → `os.replace` で中間 temp を残さず
    書き込み、実際に書いた件数を返す。
    """
    target = playlists_output_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _read_playlists_json(target)

    captured_at = datetime.now(timezone.utc).isoformat()
    written = 0
    for item in payload:
        title = str(item.get("title", ""))
        slug = normalize_suno_title(title, prefix)
        url = str(item.get("url", ""))
        if slug is None or not url:
            continue
        entry = {"title": title, "url": url, "captured_at": captured_at}
        existing = data.get(slug)
        # captured_at 後勝ち。同一バッチ・新規書き込みは captured_at が等しい/新しいため上書きする。
        if not isinstance(existing, dict) or str(existing.get("captured_at", "")) <= captured_at:
            data[slug] = entry
            written += 1

    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".suno-playlists-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, target)
    except BaseException:
        # 書き込み失敗時に temp を残さない（atomic write の後始末）。
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return written


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


def build_collections_index(
    root: Path,
    *,
    mapped_slugs: set[str] | None = None,
    prefix: str | None = None,
) -> list[dict]:
    """各 collection を `{id, name, has_prompts, pattern_count, mapped}` に写像する（#816 dir mode / #893）.

    - id   = ディレクトリ名（拡張から個別 fetch する際のホワイトリスト key）
    - name = `CollectionPaths.collection_name`（日付＋チャンネル接頭辞を除去した表示名）
    - has_prompts   = `<dir>/20-documentation/suno-prompts.json` の存在
    - pattern_count = json があれば entries 数、無ければ None
    - mapped = `derive_collection_slug(id, prefix)` が `mapped_slugs` に含まれるか（#893 要件 B）。
      prefix 未指定（後方互換・旧運用）は常に False（素通し全件表示）。
    """
    slugs = mapped_slugs or set()
    index: list[dict] = []
    for coll in find_collection_dirs(root):
        prompts_path = coll / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
        has_prompts = prompts_path.is_file()
        pattern_count = len(json.loads(prompts_path.read_text(encoding="utf-8"))) if has_prompts else None
        slug = derive_collection_slug(coll.name, prefix) if prefix else None
        mapped = slug is not None and slug in slugs
        index.append(
            {
                "id": coll.name,
                "name": CollectionPaths(coll).collection_name,
                "has_prompts": has_prompts,
                "pattern_count": pattern_count,
                "mapped": mapped,
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
    playlist_capture: tuple[Path, str] | None = None,
) -> ThreadingHTTPServer:
    """サブパス分離した GET / POST / CORS preflight を返すサーバーを生成する.

    `collections_root` 指定時は **dir mode**（`/collections` 系を配信し
    単一ファイル mode の `/suno/prompts.json` は配信しない）。既定 None は
    単一ファイル mode（`/suno/prompts.json` + `/distrokid/*`）。

    `playlist_capture=(root, prefix)` 指定時のみ POST `/suno/playlists` を有効化し、
    dir mode の `/collections` には `mapped` 判定を付与する（#893）。None なら POST は 404。

    distrokid が None または `enabled == False` のとき `/distrokid/*` は 404。
    """
    dir_mode = collections_root is not None
    distrokid_enabled = distrokid is not None and distrokid.enabled
    capture_root, capture_prefix = playlist_capture if playlist_capture is not None else (None, None)

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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            # capture 無効（--playlist-capture-root 未設定）なら endpoint 自体が無い（#893 要件5）。
            if capture_root is None:
                self.send_error(404, "Not Found")
                return
            # GET と異なり POST は Origin 必須。未設定・不許可は 403。
            origin = self._allowed_origin()
            if origin is None:
                self.send_error(403, "Forbidden")
                return
            if self.path != SUNO_PLAYLISTS_ROUTE:
                self.send_error(404, "Not Found")
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # 不正 JSON は fail-loud（silent に空書き込みしない、#893 要件5）。
                self.send_error(400, "Bad Request")
                return
            if not isinstance(payload, list):
                # body は配列契約のまま受ける（envelope 流用を弾く）。
                self.send_error(400, "Bad Request")
                return
            written = write_suno_playlists(capture_root, payload, prefix=capture_prefix)
            body = json.dumps({"written": written, "path": str(playlists_output_path(capture_root))}).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8")

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
                # capture 有効時のみ mapped 判定を付与する（#893 要件 B）。prefix 無は全件 mapped=False。
                mapped_slugs = read_mapped_slugs(capture_root) if capture_root is not None else None
                index = build_collections_index(collections_root, mapped_slugs=mapped_slugs, prefix=capture_prefix)
                body = json.dumps(index).encode("utf-8")
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


def _resolve_playlist_capture(root_arg: str | None, prefix_arg: str | None) -> tuple[Path, str] | None:
    """CLI 引数 + env fallback から playlist capture 設定を解決する（#893 要件1/2）.

    root / prefix のうち片方だけ指定は `ConfigError` で fail-loud（silent 無効化しない）。
    両方未設定なら None（POST 無効）、両方設定なら `(Path(root).expanduser(), prefix)`。
    """
    root = root_arg if root_arg is not None else os.environ.get(_PLAYLIST_CAPTURE_ROOT_ENV)
    prefix = prefix_arg if prefix_arg is not None else os.environ.get(_PLAYLIST_CAPTURE_PREFIX_ENV)
    if root is None and prefix is None:
        return None
    if root is None or prefix is None:
        raise ConfigError(
            "--playlist-capture-root と --playlist-capture-prefix は両方指定してください "
            f"(env: {_PLAYLIST_CAPTURE_ROOT_ENV} / {_PLAYLIST_CAPTURE_PREFIX_ENV})。"
        )
    return Path(root).expanduser(), prefix


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
    parser.add_argument(
        "--playlist-capture-root",
        default=None,
        help=(
            "downstream channel repo root to write config/suno-playlists.json into; "
            f"enables POST {SUNO_PLAYLISTS_ROUTE} (env fallback: {_PLAYLIST_CAPTURE_ROOT_ENV})"
        ),
    )
    parser.add_argument(
        "--playlist-capture-prefix",
        default=None,
        help=(f"Suno title / slug prefix to capture, e.g. 'df365' (env fallback: {_PLAYLIST_CAPTURE_PREFIX_ENV})"),
    )
    args = parser.parse_args()

    playlist_capture = _resolve_playlist_capture(args.playlist_capture_root, args.playlist_capture_prefix)

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
            playlist_capture=playlist_capture,
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
            playlist_capture=playlist_capture,
        )
        port = server.server_address[1]
        print(f"Serving {collection_dir} at http://localhost:{port}{SUNO_PROMPTS_ROUTE}")
        if distrokid.enabled:
            print(f"  distrokid endpoints enabled: {DISTROKID_RELEASE_ROUTE}, {DISTROKID_ASSETS_PREFIX}<path>")
    if playlist_capture is not None:
        capture_root, capture_prefix = playlist_capture
        print(
            f"  playlist capture enabled: POST {SUNO_PLAYLISTS_ROUTE} "
            f"-> {playlists_output_path(capture_root)} (prefix='{capture_prefix}')"
        )
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
