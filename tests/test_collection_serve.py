"""yt-collection-serve (collection_serve) の挙動テスト.

issue #698: #692 の `yt-suno-serve` を `yt-collection-serve` に一般化し、
エンドポイントをサブパス分離する。`/suno/prompts.json` は #692 と同じ
配列 JSON を返す（契約不変・ルートのみ `/prompts.json` → `/suno/prompts.json`）。
CORS はデフォルトで `chrome-extension://` と suno.com / distrokid.com 系 web origin を
許可し（#896）、全ルートで同一ポリシー。

契約（draft が実装すべき public API）:
- `resolve_prompts_path(path: Path) -> Path`
    dir → `<dir>/20-documentation/suno-prompts.json` / file → そのまま / 不在 → ConfigError。
- `is_origin_allowed(origin: str | None, allow_origin: str | None) -> bool`
    allow_origin=None なら `chrome-extension://` scheme と
    suno.com / distrokid.com 系 web origin を許可。指定時は完全一致のみ許可。
- `create_server(port, allow_origin, *, prompts_path, collection_dir, distrokid) -> ThreadingHTTPServer`
    `GET /suno/prompts.json` で配列 JSON、`OPTIONS` で preflight を返すサーバーを生成する。
    distrokid は `Distrokid | None`（None / 無効時は `/distrokid/*` が 404）。
- `main()`
    argparse CLI（positional path / `--port`（既定 7873）/ `--allow-origin`）。
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import pytest

from youtube_automation.scripts.collection_serve import (
    _extract_and_rename_music,
    build_collections_index,
    create_server,
    find_collection_dirs,
    is_origin_allowed,
    main,
    resolve_collection_prompts_path,
    resolve_prompts_path,
)
from youtube_automation.utils.exceptions import ConfigError

_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
_SUNO_ORIGIN = "https://suno.com"

# 外部 HTTP 契約: 拡張が fetch する suno サブパス（リテラルで pin する）
_SUNO_PROMPTS_ROUTE = "/suno/prompts.json"

# 外部 HTTP 契約（#816 dir mode）: 拡張が fetch する collection サブパス。
# SSOT: extensions/shared/constants.ts COLLECTIONS_ROUTE / collectionPromptsRoute(id)。
_COLLECTIONS_ROUTE = "/collections"

# 外部 HTTP 契約（#1023）: 拡張が初回接続時に fetch する互換確認サブパス。
_VERSION_ROUTE = "/version"


def _collection_prompts_route(cid: str) -> str:
    """`GET /collections/<id>/suno/prompts.json` ルートを組み立てる（拡張側 collectionPromptsRoute と対）。"""
    return f"{_COLLECTIONS_ROUTE}/{cid}/suno/prompts.json"


def _assert_json_404_with_cors(error: urllib.error.HTTPError, origin: str) -> None:
    assert error.code == 404
    assert error.headers.get("Access-Control-Allow-Origin") == origin
    assert error.headers.get_content_type() == "application/json"
    assert json.loads(error.read().decode("utf-8")) == {"error": "Not Found"}


def _read_error_json(error: urllib.error.HTTPError) -> dict:
    return json.loads(error.read().decode("utf-8"))


def _send_raw_http_request(base: str, request: bytes) -> bytes:
    parsed = urllib.parse.urlparse(base)
    if parsed.hostname is None or parsed.port is None:
        raise AssertionError(f"Invalid test server URL: {base}")

    with socket.create_connection((parsed.hostname, parsed.port), timeout=5) as sock:
        sock.sendall(request)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := sock.recv(4096):
            chunks.append(chunk)

    return b"".join(chunks)


# ---------------------------------------------------------------------------
# resolve_prompts_path: パス解決（dir / file / 不在）— #692 契約不変
# ---------------------------------------------------------------------------


def test_resolve_prompts_path_dir_resolves_to_documentation_json(tmp_path):
    """Given コレクションディレクトリ
    When resolve_prompts_path を呼ぶ
    Then `<dir>/20-documentation/suno-prompts.json` を返す。
    """
    doc_dir = tmp_path / "20-documentation"
    doc_dir.mkdir()
    target = doc_dir / "suno-prompts.json"
    target.write_text("[]", encoding="utf-8")

    assert resolve_prompts_path(tmp_path) == target


def test_resolve_prompts_path_file_returns_itself(tmp_path):
    """Given suno-prompts.json ファイルパスを直接渡す
    When resolve_prompts_path を呼ぶ
    Then そのパス自身を返す。
    """
    json_path = tmp_path / "suno-prompts.json"
    json_path.write_text("[]", encoding="utf-8")

    assert resolve_prompts_path(json_path) == json_path


def test_resolve_prompts_path_dir_without_json_raises(tmp_path):
    """Given json を含まないディレクトリ
    When resolve_prompts_path を呼ぶ
    Then silent 続行せず ConfigError を投げる（fail-loud）。
    """
    with pytest.raises(ConfigError):
        resolve_prompts_path(tmp_path)


def test_resolve_prompts_path_missing_path_raises(tmp_path):
    """Given 存在しないパス
    When resolve_prompts_path を呼ぶ
    Then ConfigError を投げる。
    """
    with pytest.raises(ConfigError):
        resolve_prompts_path(tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# is_origin_allowed: CORS 判定
#   - allow_origin=None  : chrome-extension:// scheme + helper サイト origin を許可（#896）
#   - allow_origin 指定時 : その値との完全一致のみ許可（lock 維持・要件2）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "allow_origin", "expected"),
    [
        # allow_origin 未指定: chrome-extension:// scheme を許可（従来挙動維持）
        ("chrome-extension://abcdefghijklmnop", None, True),
        ("chrome-extension://anotherextensionid", None, True),
        # allow_origin 未指定: helper サイト origin をデフォルト許可（#896 / overlay 化対応）
        ("https://suno.com", None, True),
        ("https://www.suno.com", None, True),
        ("https://distrokid.com", None, True),
        ("https://www.distrokid.com", None, True),
        # allow_origin 未指定: 許可リスト外の web origin は拒否（要件4）
        ("http://localhost:3000", None, False),
        ("https://evil.com", None, False),
        # allow_origin 未指定: 完全一致集合なので偽装・scheme/末尾差異は通さない
        ("https://suno.com.evil.com", None, False),  # 前方一致なら通る偽装 → 拒否
        ("http://suno.com", None, False),  # http scheme は許可しない
        ("https://suno.com/", None, False),  # Origin ヘッダに末尾スラッシュは付かない
        # Origin ヘッダ無し
        (None, None, False),
        # allow_origin 指定（extension lock）: 完全一致のみ許可、デフォルト許可リストは効かない
        ("chrome-extension://exactid", "chrome-extension://exactid", True),
        ("chrome-extension://otherid", "chrome-extension://exactid", False),
        ("https://suno.com", "chrome-extension://exactid", False),
        # allow_origin 指定（web origin lock）: その origin との完全一致のみ許可
        ("https://suno.com", "https://suno.com", True),
        ("https://www.suno.com", "https://suno.com", False),
    ],
)
def test_is_origin_allowed(origin, allow_origin, expected):
    """Given (origin, allow_origin) の組
    When is_origin_allowed を呼ぶ
    Then デフォルト許可（extension scheme + helper サイト origin）/ 完全一致ロックの
         契約どおり真偽を返す。
    """
    assert is_origin_allowed(origin, allow_origin) is expected


# ---------------------------------------------------------------------------
# HTTP サーバー統合（create_server → 実リクエスト）
# ---------------------------------------------------------------------------


@pytest.fixture
def serve(tmp_path):
    """空きポートでサーバーを起動し base URL を返すファクトリ.

    port=0 を渡して OS に空きポートを割り当てさせる（固定ポート衝突回避）。
    distrokid 既定は None（suno-only 起動モード）。
    """
    started = []

    def _start(entries, allow_origin=None):
        json_path = tmp_path / "suno-prompts.json"
        json_path.write_text(json.dumps(entries), encoding="utf-8")
        server = create_server(
            0,
            allow_origin,
            prompts_path=json_path,
            collection_dir=tmp_path,
            distrokid=None,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        port = server.server_address[1]
        return f"http://localhost:{port}"

    yield _start

    for server, thread in started:
        server.shutdown()
        thread.join(timeout=5)


def test_get_suno_prompts_json_returns_array_body(serve):
    """Given prompts データを公開するサーバー
    When `GET /suno/prompts.json`
    Then 200 で元データと一致する配列 JSON を返す（#692 契約不変）。
    """
    entries = [{"name": "A — A", "style": "slow, jazz,\nscene", "lyrics": ""}]
    base = serve(entries)

    with urllib.request.urlopen(f"{base}{_SUNO_PROMPTS_ROUTE}") as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert body == entries


def test_get_version_returns_server_and_min_extension_semvers(serve):
    """Given 単一ファイル mode サーバー
    When `GET /version`
    Then tayk 本体 version と最低拡張 version を semver JSON で返す。
    """
    base = serve([{"name": "A", "style": "s", "lyrics": ""}])

    with urllib.request.urlopen(f"{base}{_VERSION_ROUTE}") as resp:
        assert resp.status == 200
        assert resp.headers.get_content_type() == "application/json"
        body = json.loads(resp.read().decode("utf-8"))

    assert set(body) == {"version", "min_extension_version"}
    assert re.match(r"^\d+\.\d+\.\d+$", body["version"])
    assert re.match(r"^\d+\.\d+\.\d+$", body["min_extension_version"])


def test_get_version_sets_cors_header_for_extension_origin(serve):
    """Given 拡張オリジンからの互換確認
    When `GET /version`
    Then 既存 GET ルートと同じ CORS ポリシーで Origin を echo する。
    """
    base = serve([{"name": "A", "style": "s", "lyrics": ""}])
    req = urllib.request.Request(
        f"{base}{_VERSION_ROUTE}",
        headers={"Origin": _EXTENSION_ORIGIN},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN


def test_old_root_prompts_json_returns_404(serve):
    """Given 旧ルート `/prompts.json`
    When GET する
    Then breaking rename により 404（サブパス分離済み）。
    """
    base = serve([])
    req = urllib.request.Request(f"{base}/prompts.json")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_get_suno_prompts_json_sets_cors_header_for_extension_origin(serve):
    """Given 拡張オリジンからの GET
    When Origin が chrome-extension://
    Then Access-Control-Allow-Origin がそのオリジンを返す。
    """
    base = serve([{"name": "A", "style": "s", "lyrics": ""}])
    req = urllib.request.Request(
        f"{base}{_SUNO_PROMPTS_ROUTE}",
        headers={"Origin": _EXTENSION_ORIGIN},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN


def test_get_suno_prompts_json_sets_cors_header_for_suno_origin(serve):
    """Given suno.com の content script オリジンからの GET（overlay 化後の発火元・#896）
    When Origin が https://suno.com
    Then デフォルト起動でも Access-Control-Allow-Origin がそのオリジンを echo する。
    """
    base = serve([{"name": "A", "style": "s", "lyrics": ""}])
    req = urllib.request.Request(
        f"{base}{_SUNO_PROMPTS_ROUTE}",
        headers={"Origin": "https://suno.com"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://suno.com"


def test_get_suno_prompts_json_omits_cors_header_for_unknown_origin(serve):
    """Given 許可リスト外の web オリジンからの GET
    When Origin が https://evil.com
    Then Access-Control-Allow-Origin ヘッダを付けない（許可リスト外は拒否）。
    """
    base = serve([{"name": "A", "style": "s", "lyrics": ""}])
    req = urllib.request.Request(
        f"{base}{_SUNO_PROMPTS_ROUTE}",
        headers={"Origin": "https://evil.com"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") is None


def test_options_preflight_allows_extension_origin(serve):
    """Given 拡張オリジンからの preflight
    When `OPTIONS /suno/prompts.json`
    Then 2xx + Access-Control-Allow-Origin を返す。
    """
    base = serve([])
    req = urllib.request.Request(
        f"{base}{_SUNO_PROMPTS_ROUTE}",
        method="OPTIONS",
        headers={"Origin": _EXTENSION_ORIGIN},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.status in (200, 204)
        assert resp.headers.get("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN


def test_options_preflight_echoes_suno_origin(serve):
    """Given suno.com からの preflight（受け入れ基準: curl OPTIONS で echo される・#896）
    When `OPTIONS /suno/prompts.json` で Origin が https://suno.com
    Then デフォルト起動でも 2xx + Access-Control-Allow-Origin: https://suno.com を返す。
    """
    base = serve([])
    req = urllib.request.Request(
        f"{base}{_SUNO_PROMPTS_ROUTE}",
        method="OPTIONS",
        headers={"Origin": "https://suno.com"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.status in (200, 204)
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://suno.com"


def test_allow_origin_exact_match_locks_to_single_extension(serve):
    """Given --allow-origin で 1 拡張に固定
    When 別の拡張オリジンから GET
    Then 完全一致しないため CORS ヘッダを付けない。
    """
    locked = "chrome-extension://lockedextensionid"
    base = serve([], allow_origin=locked)
    req = urllib.request.Request(
        f"{base}{_SUNO_PROMPTS_ROUTE}",
        headers={"Origin": "chrome-extension://someotherid"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") is None


def test_allow_origin_lock_does_not_admit_default_web_origin(serve):
    """Given --allow-origin で 1 拡張に固定（lock 維持・要件2）
    When suno.com（デフォルト許可リスト掲載 origin）から GET
    Then lock 時は完全一致のみなので CORS ヘッダを付けない（デフォルト許可は効かない）。
    """
    locked = "chrome-extension://lockedextensionid"
    base = serve([], allow_origin=locked)
    req = urllib.request.Request(
        f"{base}{_SUNO_PROMPTS_ROUTE}",
        headers={"Origin": "https://suno.com"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") is None


def test_unknown_path_returns_404(serve):
    """Given サーバー
    When 未知パスを GET
    Then 404 を返す（既定で全許可しない）。
    """
    base = serve([])
    req = urllib.request.Request(f"{base}/unknown")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_unknown_path_returns_json_error_with_cors_for_allowed_origin(serve):
    """Given 許可 Origin からの未知パス GET
    When handler が 404 を返す
    Then CORS 付き JSON エラーを返す。
    """
    base = serve([])
    req = urllib.request.Request(f"{base}/unknown", headers={"Origin": "https://suno.com"})

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    err = exc_info.value
    assert err.code == 404
    assert err.headers.get_content_type() == "application/json"
    assert err.headers.get("Access-Control-Allow-Origin") == "https://suno.com"
    assert _read_error_json(err) == {"error": "Not Found"}


def test_malformed_request_returns_400_json_without_headers(serve):
    """Given HTTP parser がヘッダー解析前に reject するリクエスト
    When BaseHTTPRequestHandler 内部から send_error が呼ばれる
    Then handler が落ちずに CORS なし JSON 400 を返す。
    """
    base = serve([])

    response = _send_raw_http_request(base, b"BADREQUEST\r\n")

    assert response == b'{"error": "Bad request syntax (\'BADREQUEST\')"}'
    assert b"Access-Control-Allow-Origin:" not in response


def test_head_error_returns_no_body(serve):
    """Given HEAD リクエスト（do_HEAD 未実装のため 501）
    When send_error override が呼ばれる
    Then ヘッダーのみ返し body は空（HTTP/1.1 HEAD 規約 + #1209 regression guard）。
    """
    base = serve([])

    req = urllib.request.Request(
        f"{base}/unknown",
        method="HEAD",
        headers={"Origin": "https://suno.com"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    err = exc_info.value
    assert err.code == 501
    assert err.headers.get_content_type() == "application/json"
    assert err.headers.get("Access-Control-Allow-Origin") == "https://suno.com"
    assert err.read() == b""


def test_send_error_unknown_status_returns_json_with_standard_fallback(tmp_path):
    """Given 標準 HTTP status 表にない code を返す handler
    When send_error override が呼ばれる
    Then BaseHTTPRequestHandler と同じ fallback message を JSON + CORS で返す。
    """
    json_path = tmp_path / "suno-prompts.json"
    json_path.write_text("[]", encoding="utf-8")
    server = create_server(0, None, prompts_path=json_path, collection_dir=tmp_path, distrokid=None)

    class UnknownStatusHandler(server.RequestHandlerClass):
        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler 規約)
            self.send_error(599)

    server.RequestHandlerClass = UnknownStatusHandler
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://localhost:{server.server_address[1]}"
    req = urllib.request.Request(f"{base}/unknown", headers={"Origin": "https://suno.com"})

    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)

        err = exc_info.value
        assert err.code == 599
        assert err.headers.get_content_type() == "application/json"
        assert err.headers.get("Access-Control-Allow-Origin") == "https://suno.com"
        assert _read_error_json(err) == {"error": "???"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_help_flag_shows_usage_and_exits_zero(monkeypatch, capsys):
    """--help は argparse の usage を表示して exit 0 する."""
    monkeypatch.setattr(sys, "argv", ["yt-collection-serve", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# dir mode（#816）: `collections/planning/` 配下の collection 列挙 + 個別配信
#
# 契約（draft が実装すべき public API）:
# - `find_collection_dirs(root: Path) -> list[Path]`
#       root 直下の `*-collection` ディレクトリのみを名前昇順で返す。
# - `build_collections_index(root: Path) -> list[dict]`
#       各 collection を `{id, name, status, pattern_count, downloaded_count}` に写像する。
#       id=ディレクトリ名 / name=CollectionPaths.collection_name /
#       status="needs_prompts"|"ready"|"downloaded" / pattern_count=entries 数 or None /
#       downloaded_count=02-Individual-music/ 内の音声ファイル数。
# - `resolve_collection_prompts_path(root: Path, cid: str) -> Path | None`
#       cid が既知の collection dir 名のとき docs json パスを返す。
#       未知 id / トラバーサル文字列は None（fail-loud せずホワイトリスト弾き）。
# - `create_server(..., collections_root: Path | None=None)`
#       collections_root 指定時は dir mode（`/collections` 系を配信し
#       `/suno/prompts.json` は配信しない）。既定 None は単一ファイル mode。
# ---------------------------------------------------------------------------


def _make_collection(planning: Path, dir_name: str, entries=None, *, theme: str | None = None) -> Path:
    """planning dir 配下に `<dir_name>/20-documentation/suno-prompts.json` を作る。

    `entries` が None のとき json を置かない（has_prompts=False のケース）。
    """
    coll = planning / dir_name
    docs = coll / "20-documentation"
    docs.mkdir(parents=True)
    if entries is not None:
        (docs / "suno-prompts.json").write_text(json.dumps(entries), encoding="utf-8")
    if theme is not None:
        (coll / "workflow-state.json").write_text(json.dumps({"theme": theme}), encoding="utf-8")
    return coll


# --- 純関数: 列挙・index 構築・id 解決 -------------------------------------


def test_find_collection_dirs_returns_only_collection_dirs_sorted(tmp_path):
    """Given `*-collection` dir・無関係 dir・ファイルが混在する planning dir
    When find_collection_dirs を呼ぶ
    Then `*-collection` ディレクトリのみを名前昇順で返す。
    """
    _make_collection(tmp_path, "20260602-clm-bbb-collection", entries=[])
    _make_collection(tmp_path, "20260601-clm-aaa-collection", entries=[])
    (tmp_path / "01-master").mkdir()  # collection 接尾辞でない dir は除外
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")  # ファイルは除外

    found = find_collection_dirs(tmp_path)

    assert [p.name for p in found] == [
        "20260601-clm-aaa-collection",
        "20260602-clm-bbb-collection",
    ]


def test_build_collections_index_reports_status_and_pattern_count(tmp_path):
    """Given prompts 有り(2件) と prompts 無しの collection
    When build_collections_index を呼ぶ
    Then status と pattern_count を正しく写像する（prompts 無しは status=needs_prompts, pattern_count=None）。
    """
    _make_collection(
        tmp_path,
        "20260601-clm-with-prompts-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}, {"name": "B", "style": "s", "lyrics": ""}],
    )
    _make_collection(tmp_path, "20260602-clm-no-prompts-collection", entries=None)

    index = {row["id"]: row for row in build_collections_index(tmp_path)}

    with_prompts = index["20260601-clm-with-prompts-collection"]
    assert with_prompts["status"] == "ready"
    assert with_prompts["pattern_count"] == 2
    assert with_prompts["downloaded_count"] == 0

    no_prompts = index["20260602-clm-no-prompts-collection"]
    assert no_prompts["status"] == "needs_prompts"
    assert no_prompts["pattern_count"] is None
    assert no_prompts["downloaded_count"] == 0


def test_build_collections_index_name_strips_date_and_channel_prefix(tmp_path):
    """Given `<date>-<channel>-<theme>-collection` 形式の dir
    When build_collections_index を呼ぶ
    Then id=dir 名そのまま / name=theme / channel, theme を返す。
    """
    _make_collection(tmp_path, "20260601-clm-midnight-mood-collection", entries=[])

    row = build_collections_index(tmp_path)[0]

    assert row["id"] == "20260601-clm-midnight-mood-collection"
    assert row["name"] == "midnight-mood"
    assert row["theme"] == "midnight-mood"
    assert row["channel"] == "clm"


def test_build_collections_index_does_not_emit_playlist_name(tmp_path):
    """Given multi-word prefix の collection
    When build_collections_index を呼ぶ
    Then playlist_name は返さない（#1216 BREAKING contract）。
    """
    _make_collection(
        tmp_path,
        "20260601-soulful-grooves-wah-groove-collection",
        entries=[],
        theme="wah-groove",
    )

    row = build_collections_index(tmp_path)[0]

    assert "playlist_name" not in row
    assert row["channel"] == "soulful-grooves"
    assert row["theme"] == "wah-groove"


def test_build_collections_index_status_downloaded_when_music_files_sufficient(tmp_path):
    """Given prompts 2 件 + 02-Individual-music/ に mp3 4 件
    When build_collections_index を呼ぶ
    Then status=downloaded, downloaded_count=4。
    """
    coll = _make_collection(
        tmp_path,
        "20260601-clm-done-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}, {"name": "B", "style": "s", "lyrics": ""}],
    )
    music_dir = coll / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / "track1.mp3").write_bytes(b"fake")
    (music_dir / "track2.mp3").write_bytes(b"fake")
    (music_dir / "track3.mp3").write_bytes(b"fake")
    (music_dir / "track4.mp3").write_bytes(b"fake")

    row = build_collections_index(tmp_path)[0]

    assert row["status"] == "downloaded"
    assert row["downloaded_count"] == 4
    assert row["expected_file_count"] == 4


def test_build_collections_index_status_ready_when_music_files_insufficient(tmp_path):
    """Given prompts 2 件 + 02-Individual-music/ に mp3 2 件
    When build_collections_index を呼ぶ
    Then status=ready, downloaded_count=2。
    """
    coll = _make_collection(
        tmp_path,
        "20260601-clm-partial-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}, {"name": "B", "style": "s", "lyrics": ""}],
    )
    music_dir = coll / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / "track1.mp3").write_bytes(b"fake")
    (music_dir / "track2.mp3").write_bytes(b"fake")

    row = build_collections_index(tmp_path)[0]

    assert row["status"] == "ready"
    assert row["downloaded_count"] == 2
    assert row["expected_file_count"] == 4


def test_build_collections_index_counts_multiple_audio_formats(tmp_path):
    """Given 02-Individual-music/ に mp3, m4a, wav ファイル
    When build_collections_index を呼ぶ
    Then 全音声形式をカウントする。
    """
    coll = _make_collection(
        tmp_path,
        "20260601-clm-multi-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}],
    )
    music_dir = coll / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / "track1.mp3").write_bytes(b"fake")
    (music_dir / "track2.m4a").write_bytes(b"fake")
    (music_dir / "track3.wav").write_bytes(b"fake")
    (music_dir / "notes.txt").write_bytes(b"not audio")  # 非音声は除外

    row = build_collections_index(tmp_path)[0]

    assert row["downloaded_count"] == 3


def test_build_collections_index_uses_workflow_expected_file_count_when_larger(tmp_path):
    """Given prompts 2 件 + workflow-state.json に expected_file_count=6
    When build_collections_index を呼ぶ
    Then expected_file_count=6 を完了判定に使う。
    """
    coll = _make_collection(
        tmp_path,
        "20260601-clm-explicit-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}, {"name": "B", "style": "s", "lyrics": ""}],
    )
    (coll / "workflow-state.json").write_text(
        json.dumps({"planning": {"music": {"expected_file_count": 6}}}),
        encoding="utf-8",
    )
    music_dir = coll / "02-Individual-music"
    music_dir.mkdir()
    for idx in range(4):
        (music_dir / f"track{idx + 1}.mp3").write_bytes(b"fake")

    row = build_collections_index(tmp_path)[0]

    assert row["status"] == "ready"
    assert row["downloaded_count"] == 4
    assert row["expected_file_count"] == 6


def test_resolve_collection_prompts_path_valid_id_returns_docs_json(tmp_path):
    """Given 既知の collection id
    When resolve_collection_prompts_path を呼ぶ
    Then `<dir>/20-documentation/suno-prompts.json` を返す。
    """
    coll = _make_collection(
        tmp_path, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}]
    )

    resolved = resolve_collection_prompts_path(tmp_path, "20260601-clm-aaa-collection")

    assert resolved == coll / "20-documentation" / "suno-prompts.json"


def test_resolve_collection_prompts_path_unknown_id_returns_none(tmp_path):
    """Given 存在しない collection id
    When resolve_collection_prompts_path を呼ぶ
    Then None を返す（ホワイトリスト外）。
    """
    _make_collection(tmp_path, "20260601-clm-aaa-collection", entries=[])

    assert resolve_collection_prompts_path(tmp_path, "does-not-exist") is None


@pytest.mark.parametrize(
    "malicious",
    ["../secrets", "../../etc/passwd", "20260601-clm-aaa-collection/../..", "..%2F.."],
)
def test_resolve_collection_prompts_path_traversal_returns_none(tmp_path, malicious):
    """Given パストラバーサルを狙う id 文字列
    When resolve_collection_prompts_path を呼ぶ
    Then ホワイトリスト不一致で None を返す（fail-loud でなく 404 化できる形）。
    """
    _make_collection(tmp_path, "20260601-clm-aaa-collection", entries=[])

    assert resolve_collection_prompts_path(tmp_path, malicious) is None


# --- HTTP 統合: dir mode サーバー ------------------------------------------


@pytest.fixture
def serve_dir(tmp_path):
    """planning dir を dir mode で配信し base URL を返すファクトリ.

    collections_root=planning を渡し、単一 mode 用の prompts_path/collection_dir は
    None（dir mode では一意に定まらないため）。distrokid も None。
    """
    started = []

    def _start(planning: Path, allow_origin=None, playlist_capture=None):
        server = create_server(
            0,
            allow_origin,
            prompts_path=None,
            collection_dir=None,
            distrokid=None,
            collections_root=planning,
            playlist_capture=playlist_capture,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        port = server.server_address[1]
        return f"http://localhost:{port}"

    yield _start

    for server, thread in started:
        server.shutdown()
        thread.join(timeout=5)


def test_get_collections_lists_planning_collections(serve_dir, tmp_path):
    """Given prompts 有り/無しの collection を持つ planning dir
    When `GET /collections`
    Then `[{id, name, status, pattern_count, downloaded_count}]` を返す（#1216）。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}],
    )
    _make_collection(planning, "20260602-clm-bbb-collection", entries=None)
    base = serve_dir(planning)

    with urllib.request.urlopen(f"{base}{_COLLECTIONS_ROUTE}") as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    by_id = {row["id"]: row for row in body}
    assert by_id["20260601-clm-aaa-collection"] == {
        "id": "20260601-clm-aaa-collection",
        "name": "aaa",
        "status": "ready",
        "pattern_count": 1,
        "downloaded_count": 0,
        "theme": "aaa",
        "channel": "clm",
        "expected_file_count": 2,
    }
    assert by_id["20260602-clm-bbb-collection"]["status"] == "needs_prompts"
    assert by_id["20260602-clm-bbb-collection"]["pattern_count"] is None


def test_get_collections_does_not_include_playlist_name_when_capture_enabled(serve_dir, tmp_path):
    """Given capture prefix 付き dir mode サーバー
    When `GET /collections`
    Then playlist_name は返さない（拡張側で collection id/name から導出する）。
    """
    planning = tmp_path / "planning"
    channel_root = tmp_path / "channel"
    channel_root.mkdir()
    _make_collection(
        planning,
        "20260601-soulful-grooves-wah-groove-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}],
        theme="wah-groove",
    )
    base = serve_dir(planning, playlist_capture=(channel_root, "soulful-grooves"))

    with urllib.request.urlopen(f"{base}{_COLLECTIONS_ROUTE}") as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert "playlist_name" not in body[0]
    assert body[0]["channel"] == "soulful-grooves"
    assert body[0]["theme"] == "wah-groove"


def test_dir_mode_get_version_is_available_before_collection_routing(serve_dir, tmp_path):
    """Given dir mode サーバー
    When `GET /version`
    Then `/collections` ルーティングとは独立して互換確認 JSON を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning)

    with urllib.request.urlopen(f"{base}{_VERSION_ROUTE}") as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert set(body) == {"version", "min_extension_version"}


def test_get_collection_prompts_returns_entries(serve_dir, tmp_path):
    """Given 該当 collection に prompts json
    When `GET /collections/<id>/suno/prompts.json`
    Then 200 で元データと一致する配列 JSON を返す。
    """
    planning = tmp_path / "planning"
    entries = [{"name": "A — A", "style": "slow, jazz", "lyrics": ""}]
    _make_collection(planning, "20260601-clm-aaa-collection", entries=entries)
    base = serve_dir(planning)

    url = f"{base}{_collection_prompts_route('20260601-clm-aaa-collection')}"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert body == entries


def test_get_collection_prompts_unknown_id_returns_404(serve_dir, tmp_path):
    """Given 存在しない collection id
    When `GET /collections/<id>/suno/prompts.json`
    Then CORS 付き JSON 404 を返す（ホワイトリスト弾き）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning)

    req = urllib.request.Request(
        f"{base}{_collection_prompts_route('nope-collection')}",
        headers={"Origin": _SUNO_ORIGIN},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    _assert_json_404_with_cors(exc_info.value, _SUNO_ORIGIN)


def test_get_collection_prompts_unknown_id_returns_cors_json_404(serve_dir, tmp_path):
    """Given 許可 Origin + 存在しない collection id
    When `GET /collections/<id>/suno/prompts.json`
    Then CORS 付き JSON 404 を返す（#1209: send_error CORS 統一）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning)

    req = urllib.request.Request(
        f"{base}{_collection_prompts_route('nope-collection')}",
        headers={"Origin": "https://suno.com"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    err = exc_info.value
    assert err.code == 404
    assert err.headers.get_content_type() == "application/json"
    assert err.headers.get("Access-Control-Allow-Origin") == "https://suno.com"
    assert _read_error_json(err) == {"error": "Not Found"}


def test_get_collection_prompts_without_prompts_returns_404(serve_dir, tmp_path):
    """Given prompts json を持たない collection（has_prompts=False）
    When `GET /collections/<id>/suno/prompts.json`
    Then CORS 付き JSON 404 を返す（受け入れ条件: has_prompts true のみ実行可能）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-empty-collection", entries=None)
    base = serve_dir(planning)

    req = urllib.request.Request(
        f"{base}{_collection_prompts_route('20260601-clm-empty-collection')}",
        headers={"Origin": _EXTENSION_ORIGIN},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    _assert_json_404_with_cors(exc_info.value, _EXTENSION_ORIGIN)


@pytest.mark.parametrize("origin", [_SUNO_ORIGIN, _EXTENSION_ORIGIN])
def test_dir_mode_does_not_serve_single_suno_prompts_route(serve_dir, tmp_path, origin):
    """Given dir mode サーバー
    When `GET /suno/prompts.json`（単一 mode のルート）
    Then CORS 付き JSON 404 を返す（単一 mode のルートは dir mode で生きない）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning)

    req = urllib.request.Request(
        f"{base}{_SUNO_PROMPTS_ROUTE}",
        headers={"Origin": origin},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    _assert_json_404_with_cors(exc_info.value, origin)


def test_dir_mode_collections_sets_cors_header_for_extension_origin(serve_dir, tmp_path):
    """Given 拡張オリジンからの `GET /collections`
    When Origin が chrome-extension://
    Then Access-Control-Allow-Origin がそのオリジンを返す（単一 mode と同一 CORS ポリシー）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning)

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}",
        headers={"Origin": _EXTENSION_ORIGIN},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN


@pytest.mark.parametrize("origin", [_SUNO_ORIGIN, _EXTENSION_ORIGIN])
def test_single_mode_collections_route_returns_404(serve, origin):
    """Given 単一ファイル mode サーバー（collections_root 未指定）
    When `GET /collections`
    Then CORS 付き JSON 404 を返す。popup はこの 404 を fallback トリガーに使う（dir mode 専用ルート）。
    """
    base = serve([{"name": "A", "style": "s", "lyrics": ""}])

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}",
        headers={"Origin": origin},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    _assert_json_404_with_cors(exc_info.value, origin)


# ---------------------------------------------------------------------------
# POST /collections/<id>/downloaded (#1216): ダウンロード完了通知
# ---------------------------------------------------------------------------


def _post(url: str, body, *, headers=None):
    """JSON body を POST する。"""
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers or {})
    return urllib.request.urlopen(req)


def _fetch_token(base: str) -> str:
    """GET /auth/token からサーバートークンを取得する。"""
    req = urllib.request.Request(f"{base}/auth/token", headers={"Origin": _EXTENSION_ORIGIN})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))["token"]


def test_post_downloaded_updates_workflow_state(serve_dir, tmp_path):
    """Given dir mode サーバー + 既知 collection
    When POST /collections/<id>/downloaded を送る
    Then workflow-state.json が更新され 200 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}],
    )
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 0, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with _post(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        payload,
        headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
    ) as resp:
        assert resp.status == 200
        result = json.loads(resp.read().decode("utf-8"))

    assert result["ok"] is True
    assert result["collection_id"] == "20260601-clm-aaa-collection"

    # workflow-state.json が正しく更新されたか確認
    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    ws = json.loads(ws_path.read_text(encoding="utf-8"))
    assert ws["planning"]["music"]["suno_playlist_url"] == "https://suno.com/playlist/abc"
    assert "assets" not in ws or "music_downloaded" not in ws.get("assets", {})


def test_post_downloaded_unknown_collection_returns_404(serve_dir, tmp_path):
    """Given 存在しない collection id
    When POST /collections/<id>/downloaded を送る
    Then 404 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 1, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/nope-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 404


@pytest.mark.parametrize("malicious_id", ["../secrets", "../../etc/passwd", "..%2F.."])
def test_post_downloaded_traversal_returns_404(serve_dir, tmp_path, malicious_id):
    """Given パストラバーサルを狙う collection id
    When POST /collections/<id>/downloaded を送る
    Then 404 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 1, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/{malicious_id}/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 404


def test_post_downloaded_without_origin_returns_403(serve_dir, tmp_path):
    """Given Origin ヘッダ無しの POST
    When POST /collections/<id>/downloaded を送る
    Then 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning)
    payload = {"file_count": 1, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
        )

    assert exc_info.value.code == 403


def test_post_downloaded_invalid_json_returns_400(serve_dir, tmp_path):
    """Given JSON として解釈できない body
    When POST /collections/<id>/downloaded を送る
    Then 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            b"{not json",
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400


def test_post_downloaded_missing_fields_returns_400(serve_dir, tmp_path):
    """Given 必須フィールド欠落の body
    When POST /collections/<id>/downloaded を送る
    Then 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 1}  # format が欠落

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400


def test_post_downloaded_positive_file_count_without_download_path_returns_400(serve_dir, tmp_path):
    """Given file_count>0 だが download_path なしの downloaded body
    When POST /collections/<id>/downloaded を送る
    Then ZIP 展開成功に基づかない完了扱いを避けるため 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 1, "format": "mp3"}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400


def test_post_downloaded_zero_file_count_does_not_set_music_downloaded(serve_dir, tmp_path):
    """Given file_count=0
    When POST /collections/<id>/downloaded を送る
    Then suno_playlist_url は設定されるが assets.music_downloaded は設定されない。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 0, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with _post(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        payload,
        headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
    ) as resp:
        assert resp.status == 200

    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    ws = json.loads(ws_path.read_text(encoding="utf-8"))
    assert ws["planning"]["music"]["suno_playlist_url"] == "https://suno.com/playlist/abc"
    assert "assets" not in ws or "music_downloaded" not in ws.get("assets", {})


def test_post_downloaded_zero_file_count_preserves_existing_music_downloaded(serve_dir, tmp_path):
    """Given 既に downloaded の workflow-state
    When playlist URL 記録用に file_count=0 で POST する
    Then assets.music_downloaded=true を維持する。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    ws_path.write_text(json.dumps({"assets": {"music_downloaded": True}}), encoding="utf-8")
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 0, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with _post(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        payload,
        headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
    ) as resp:
        assert resp.status == 200

    ws = json.loads(ws_path.read_text(encoding="utf-8"))
    assert ws["planning"]["music"]["suno_playlist_url"] == "https://suno.com/playlist/abc"
    assert ws["assets"]["music_downloaded"] is True


def test_post_downloaded_idempotent_two_calls(serve_dir, tmp_path):
    """Given 冪等 2-call パターン（1st: file_count=0、2nd: file_count=N）
    When 同じ collection に対して POST を 2 回送る
    Then 1st で playlist URL のみ記録、2nd で music_downloaded=true が追加され、
         既存キーが壊れない（冪等）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    url = f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded"
    auth_headers = {"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token}

    # 1st call: file_count=0 → playlist URL のみ記録
    payload_1 = {"file_count": 0, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}
    with _post(url, payload_1, headers=auth_headers) as resp:
        assert resp.status == 200

    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    ws = json.loads(ws_path.read_text(encoding="utf-8"))
    assert ws["planning"]["music"]["suno_playlist_url"] == "https://suno.com/playlist/abc"
    assert "assets" not in ws or "music_downloaded" not in ws.get("assets", {})

    zip_path = _make_zip(tmp_path / "download.zip", {"A.mp3": b"a", "A_1.mp3": b"b"})
    # 2nd call: ZIP 展開成功 → music_downloaded=true、playlist URL は維持
    payload_2 = {
        "file_count": 2,
        "expected_file_count": 2,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
        "download_path": str(zip_path),
    }
    with _post(url, payload_2, headers=auth_headers) as resp:
        assert resp.status == 200

    ws = json.loads(ws_path.read_text(encoding="utf-8"))
    assert ws["planning"]["music"]["suno_playlist_url"] == "https://suno.com/playlist/abc"
    assert ws["assets"]["music_downloaded"] is True


def test_post_downloaded_idempotent_repeated_calls_do_not_break(serve_dir, tmp_path):
    """Given 同じ payload で POST を 3 回繰り返す
    When 冪等な繰り返し呼び出し
    Then 毎回 200 を返し、workflow-state.json の内容は一貫して正しい。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    url = f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded"
    zip_path = _make_zip(tmp_path / "download.zip", {"A.mp3": b"a", "A_1.mp3": b"b"})
    payload = {
        "file_count": 2,
        "expected_file_count": 2,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/xyz",
        "download_path": str(zip_path),
    }

    for i in range(3):
        if i > 0:
            zip_path = _make_zip(tmp_path / f"download-{i}.zip", {"A.mp3": b"a", "A_1.mp3": b"b"})
            payload["download_path"] = str(zip_path)
        with _post(url, payload, headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token}) as resp:
            assert resp.status == 200

    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    ws = json.loads(ws_path.read_text(encoding="utf-8"))
    assert ws["planning"]["music"]["suno_playlist_url"] == "https://suno.com/playlist/xyz"
    assert ws["assets"]["music_downloaded"] is True


def test_post_downloaded_preserves_existing_workflow_state(serve_dir, tmp_path):
    """Given 既存の workflow-state.json に別のキーがある状態
    When POST /collections/<id>/downloaded を送る
    Then 既存キーが保持されつつ新しいキーが追加される（deep merge）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[{"name": "A", "style": "s", "lyrics": ""}])
    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    ws_path.write_text(
        json.dumps({"planning": {"thumbnail": {"approved": True}}, "meta": {"version": 1}}),
        encoding="utf-8",
    )
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    zip_path = _make_zip(tmp_path / "download.zip", {"A.mp3": b"a", "A_1.mp3": b"b"})
    payload = {
        "file_count": 2,
        "expected_file_count": 2,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/merge",
        "download_path": str(zip_path),
    }

    with _post(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        payload,
        headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
    ) as resp:
        assert resp.status == 200

    ws = json.loads(ws_path.read_text(encoding="utf-8"))
    # 既存キーが保持されている
    assert ws["planning"]["thumbnail"]["approved"] is True
    assert ws["meta"]["version"] == 1
    # 新しいキーが追加されている
    assert ws["planning"]["music"]["suno_playlist_url"] == "https://suno.com/playlist/merge"
    assert ws["assets"]["music_downloaded"] is True


# ---------------------------------------------------------------------------
# _extract_and_rename_music (#1256): ZIP 展開 + 曲順リネーム
# ---------------------------------------------------------------------------


def _make_zip(path: Path, files: dict[str, bytes]) -> Path:
    """指定ファイル名→バイト内容の dict から ZIP を作る。"""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def test_extract_and_rename_happy_path(tmp_path):
    """ZIP 内の mp3 が suno-prompts.json の曲順でリネームされて 02-Individual-music/ に配置される。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[
            {"name": "螺旋の降下 — Spiral Descent", "style": "s", "lyrics": ""},
            {"name": "最初の回転 — First Revolution", "style": "s", "lyrics": ""},
        ],
    )
    zip_path = _make_zip(
        tmp_path / "download.zip",
        {
            "Spiral Descent.mp3": b"audio-a",
            "Spiral Descent_1.mp3": b"audio-b",
            "First Revolution.mp3": b"audio-a2",
            "First Revolution_1.mp3": b"audio-b2",
        },
    )

    _extract_and_rename_music(coll, str(zip_path))

    music_dir = coll / "02-Individual-music"
    names = sorted(f.name for f in music_dir.iterdir())
    assert names == [
        "01a-Spiral Descent.mp3",
        "01b-Spiral Descent.mp3",
        "02a-First Revolution.mp3",
        "02b-First Revolution.mp3",
    ]


def test_extract_without_prompts(tmp_path):
    """suno-prompts.json が無い場合、対応件数を確定できないため配置しない。"""
    coll = _make_collection(tmp_path, "20260601-clm-aaa-collection", entries=None)
    zip_path = _make_zip(
        tmp_path / "download.zip",
        {"Track A.mp3": b"a", "Track B.mp3": b"b"},
    )

    result = _extract_and_rename_music(coll, str(zip_path))

    music_dir = coll / "02-Individual-music"
    assert result == 0
    assert not music_dir.exists() or list(music_dir.iterdir()) == []


def test_extract_invalid_zip_path(tmp_path):
    """存在しない ZIP パス → fail-soft（例外なし、ファイル生成なし）。"""
    coll = _make_collection(tmp_path, "20260601-clm-aaa-collection", entries=[])

    _extract_and_rename_music(coll, str(tmp_path / "nonexistent.zip"))

    music_dir = coll / "02-Individual-music"
    assert not music_dir.exists()


def test_extract_non_zip_file(tmp_path):
    """ZIP でないファイル → fail-soft。"""
    coll = _make_collection(tmp_path, "20260601-clm-aaa-collection", entries=[])
    not_zip = tmp_path / "fake.zip"
    not_zip.write_text("this is not a zip")

    _extract_and_rename_music(coll, str(not_zip))

    music_dir = coll / "02-Individual-music"
    assert not music_dir.exists()


def test_extract_variant_detection(tmp_path):
    """_1 サフィックスが正しく take B として扱われる。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[{"name": "テスト — My Song", "style": "s", "lyrics": ""}],
    )
    zip_path = _make_zip(
        tmp_path / "download.zip",
        {"My Song.mp3": b"take-a", "My Song_1.mp3": b"take-b"},
    )

    _extract_and_rename_music(coll, str(zip_path))

    music_dir = coll / "02-Individual-music"
    assert (music_dir / "01a-My Song.mp3").read_bytes() == b"take-a"
    assert (music_dir / "01b-My Song.mp3").read_bytes() == b"take-b"


def test_extract_suno_track_prefixed_names(tmp_path):
    """Suno ZIP の `Track NN Title(_1).mp3` 形式も prompts の英語名でリネームされる。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[
            {"name": "Track 01 — Ignition Hour", "style": "s", "lyrics": ""},
            {"name": "Track 02 — First Light Signal", "style": "s", "lyrics": ""},
        ],
    )
    zip_path = _make_zip(
        tmp_path / "download.zip",
        {
            "Track 01 Ignition Hour.mp3": b"take-a",
            "Track 01 Ignition Hour_1.mp3": b"take-b",
            "Track 02 First Light Signal.mp3": b"take-a2",
            "Track 02 First Light Signal_1.mp3": b"take-b2",
        },
    )

    _extract_and_rename_music(coll, str(zip_path))

    music_dir = coll / "02-Individual-music"
    names = sorted(f.name for f in music_dir.iterdir())
    assert names == [
        "01a-Ignition Hour.mp3",
        "01b-Ignition Hour.mp3",
        "02a-First Light Signal.mp3",
        "02b-First Light Signal.mp3",
    ]


def test_extract_japanese_name_with_english_tail(tmp_path):
    """Suno ZIP の `日本語 English Title(_1).mp3` 形式も prompts の英語名でリネームされる。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[
            {"name": "炎の鍵盤 — Keys on Fire", "style": "s", "lyrics": ""},
            {"name": "不屈の巡航 — Unbroken Cruise", "style": "s", "lyrics": ""},
        ],
    )
    zip_path = _make_zip(
        tmp_path / "download.zip",
        {
            "炎の鍵盤 Keys on Fire.mp3": b"take-a",
            "炎の鍵盤 Keys on Fire_1.mp3": b"take-b",
            "不屈の巡航 Unbroken Cruise.mp3": b"take-a2",
        },
    )

    _extract_and_rename_music(coll, str(zip_path))

    music_dir = coll / "02-Individual-music"
    names = sorted(f.name for f in music_dir.iterdir())
    assert names == [
        "01a-Keys on Fire.mp3",
        "01b-Keys on Fire.mp3",
        "02a-Unbroken Cruise.mp3",
    ]


def test_extract_unmatched_files(tmp_path):
    """prompts にマッチしないファイルは配置せず、完了件数にも数えない。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[{"name": "テスト — Known", "style": "s", "lyrics": ""}],
    )
    zip_path = _make_zip(
        tmp_path / "download.zip",
        {"Known.mp3": b"matched", "Unknown.mp3": b"unmatched"},
    )

    result = _extract_and_rename_music(coll, str(zip_path))

    music_dir = coll / "02-Individual-music"
    names = sorted(f.name for f in music_dir.iterdir())
    assert result == 1
    assert names == ["01a-Known.mp3"]


def test_extract_skips_non_audio_files(tmp_path):
    """ZIP 内の非音声ファイル（画像等）はスキップされる。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[{"name": "テスト — Track", "style": "s", "lyrics": ""}],
    )
    zip_path = _make_zip(
        tmp_path / "download.zip",
        {"Track.mp3": b"audio", "cover.jpg": b"image"},
    )

    _extract_and_rename_music(coll, str(zip_path))

    music_dir = coll / "02-Individual-music"
    names = [f.name for f in music_dir.iterdir()]
    assert names == ["01a-Track.mp3"]


def test_extract_existing_audio_plus_empty_zip_returns_zero(tmp_path):
    """既存の音声ファイルがある状態で空 ZIP を展開すると moved_count=0 を返す (#1217 QA-1217-01)。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[{"name": "テスト — Existing", "style": "s", "lyrics": ""}],
    )
    music_dir = coll / "02-Individual-music"
    music_dir.mkdir(parents=True, exist_ok=True)
    (music_dir / "01a-Existing.mp3").write_bytes(b"pre-existing")
    # ZIP with no audio files
    zip_path = _make_zip(tmp_path / "empty-audio.zip", {"readme.txt": b"not audio"})

    result = _extract_and_rename_music(coll, str(zip_path))

    assert result == 0


def test_extract_title_based_matching(tmp_path):
    """entry.title でもマッチする (#1217 CODING-1217-03)。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[
            {"name": "夜明け — Dawn Chorus", "title": "Custom Dawn Title", "style": "s", "lyrics": ""},
        ],
    )
    zip_path = _make_zip(
        tmp_path / "title-match.zip",
        {"Custom Dawn Title.mp3": b"audio-by-title"},
    )

    result = _extract_and_rename_music(coll, str(zip_path))

    assert result == 1
    music_dir = coll / "02-Individual-music"
    names = [f.name for f in music_dir.iterdir()]
    assert names == ["01a-Custom Dawn Title.mp3"]


def test_extract_nested_zip_audio_files(tmp_path):
    """ZIP 内で音声がサブディレクトリ配下でも展開して配置する。"""
    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[{"name": "曲A — Song A", "style": "s", "lyrics": ""}],
    )
    zip_path = _make_zip(tmp_path / "nested.zip", {"playlist/Song A.mp3": b"audio"})

    result = _extract_and_rename_music(coll, str(zip_path))

    assert result == 1
    music_dir = coll / "02-Individual-music"
    assert [f.name for f in music_dir.iterdir()] == ["01a-Song A.mp3"]


def test_extract_rejects_zip_slip_audio_entry(tmp_path, monkeypatch):
    """ZIP entry 名に .. を含む音声ファイルは tmp_dir 外へ展開しない。"""
    import youtube_automation.scripts.collection_serve as cs

    coll = _make_collection(
        tmp_path,
        "20260601-clm-aaa-collection",
        entries=[{"name": "曲A — Song A", "style": "s", "lyrics": ""}],
    )
    extract_root = tmp_path / "extract"
    monkeypatch.setattr(cs.tempfile, "mkdtemp", lambda prefix: str(extract_root))
    zip_path = _make_zip(tmp_path / "zipslip.zip", {"../evil.mp3": b"bad"})

    result = _extract_and_rename_music(coll, str(zip_path))

    assert result == 0
    assert not (tmp_path / "evil.mp3").exists()


def test_post_downloaded_with_download_path_extracts_zip(serve_dir, tmp_path):
    """POST /downloaded に download_path を含めると ZIP 展開 + リネームが実行される。"""
    planning = tmp_path / "planning"
    coll = _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[
            {"name": "曲A — Song A", "style": "s", "lyrics": ""},
            {"name": "曲B — Song B", "style": "s", "lyrics": ""},
        ],
    )
    zip_path = _make_zip(
        tmp_path / "test.zip",
        {
            "Song A.mp3": b"a1",
            "Song A_1.mp3": b"a2",
            "Song B.mp3": b"b1",
            "Song B_1.mp3": b"b2",
        },
    )
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 4,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/test",
        "download_path": str(zip_path),
    }

    with _post(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        payload,
        headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
    ) as resp:
        assert resp.status == 200

    music_dir = coll / "02-Individual-music"
    names = sorted(f.name for f in music_dir.iterdir())
    assert names == ["01a-Song A.mp3", "01b-Song A.mp3", "02a-Song B.mp3", "02b-Song B.mp3"]


def test_post_downloaded_success_keeps_download_archive(serve_dir, tmp_path):
    """POST /downloaded が成功しても元 ZIP は削除しない。"""
    planning = tmp_path / "planning"
    _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[{"name": "曲A — Song A", "style": "s", "lyrics": ""}],
    )
    zip_path = _make_zip(
        tmp_path / "valid.zip",
        {"Song A.mp3": b"audio1", "Song A_1.mp3": b"audio2"},
    )
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)

    with _post(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        {
            "file_count": 2,
            "format": "mp3",
            "suno_playlist_url": "https://suno.com/playlist/abc",
            "download_path": str(zip_path),
        },
        headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
    ) as resp:
        assert resp.status == 200

    assert zip_path.exists()


# ---------------------------------------------------------------------------
# Payload validation (#1217): file_count / format / download_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_file_count", [True, False, "5", 3.14, -1])
def test_post_downloaded_invalid_file_count_returns_400(serve_dir, tmp_path, bad_file_count):
    """Given file_count が int 以外 / bool / 負数
    When POST /collections/<id>/downloaded を送る
    Then 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": bad_file_count, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400


@pytest.mark.parametrize("bad_expected_file_count", [True, False, "5", 3.14, -1])
def test_post_downloaded_invalid_expected_file_count_returns_400(serve_dir, tmp_path, bad_expected_file_count):
    """Given expected_file_count が int 以外 / bool / 負数
    When POST /collections/<id>/downloaded を送る
    Then 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 1,
        "expected_file_count": bad_expected_file_count,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
    }

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400


@pytest.mark.parametrize("bad_format", ["flac", "ogg", "aac", ""])
def test_post_downloaded_invalid_format_returns_400(serve_dir, tmp_path, bad_format):
    """Given format が mp3/m4a/wav 以外
    When POST /collections/<id>/downloaded を送る
    Then 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 1, "format": bad_format, "suno_playlist_url": "https://suno.com/playlist/abc"}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400


def test_post_downloaded_relative_download_path_returns_400(serve_dir, tmp_path):
    """Given download_path が相対パス
    When POST /collections/<id>/downloaded を送る
    Then 400 を返す（パストラバーサル防御 #1217）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 4,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
        "download_path": "../../../etc/passwd",
    }

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400


def test_post_downloaded_download_path_without_playlist_url_returns_400(serve_dir, tmp_path):
    """Given download_path 付きだが suno_playlist_url が無い payload
    When POST /collections/<id>/downloaded を送る
    Then workflow-state の lost update を避けるため 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    zip_path = _make_zip(tmp_path / "test.zip", {"Song A.mp3": b"a1"})
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            {"file_count": 1, "format": "mp3", "download_path": str(zip_path)},
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400


def test_extract_oversized_zip_entry_rejected(tmp_path, monkeypatch):
    """ZIP 内の単一ファイルがサイズ上限を超える場合、展開しない (#1217)。"""
    import youtube_automation.scripts.collection_serve as cs

    # テスト用に上限を 10 bytes に下げる（実際の 500MB は CI で生成不可）。
    monkeypatch.setattr(cs, "_ZIP_MAX_SINGLE_FILE", 10)
    coll = _make_collection(tmp_path, "20260601-clm-aaa-collection", entries=[])
    zip_path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("huge.mp3", b"x" * 100)  # 100 bytes > limit of 10

    result = _extract_and_rename_music(coll, str(zip_path))

    assert result == 0
    music_dir = coll / "02-Individual-music"
    assert not music_dir.exists() or len(list(music_dir.iterdir())) == 0


def test_extract_too_many_entries_rejected(tmp_path):
    """ZIP 内の entry 数が 1000 を超える場合、展開しない (#1217)。"""
    coll = _make_collection(tmp_path, "20260601-clm-aaa-collection", entries=[])
    zip_path = tmp_path / "many.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(1001):
            zf.writestr(f"track_{i:04d}.mp3", b"x")

    result = _extract_and_rename_music(coll, str(zip_path))

    assert result == 0


def test_post_downloaded_extraction_failure_does_not_set_music_downloaded(serve_dir, tmp_path):
    """Given download_path が存在しない ZIP を指す
    When POST /collections/<id>/downloaded を送る
    Then extraction 失敗時は 500 を返し workflow-state.json を更新しない (#1217)。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    # 存在しない ZIP パスを指定
    nonexistent = str(tmp_path / "does_not_exist.zip")
    payload = {
        "file_count": 5,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
        "download_path": nonexistent,
    }

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 500

    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    # workflow-state.json should not exist since the request failed before updating
    assert not ws_path.exists()


# ---------------------------------------------------------------------------
# Token auth (#1217): /auth/token + X-Serve-Token validation
# ---------------------------------------------------------------------------


def test_get_auth_token_returns_uuid(serve_dir, tmp_path):
    """Given extension origin に lock した dir mode サーバー
    When exact extension Origin から GET /auth/token を送る
    Then UUID 形式の token を含む JSON を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    req = urllib.request.Request(f"{base}/auth/token", headers={"Origin": _EXTENSION_ORIGIN})

    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert "token" in body
    # UUID v4 format: 8-4-4-4-12 hex digits
    assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", body["token"])


def test_get_auth_token_default_rejects_extension_origin_without_exact_lock(serve_dir, tmp_path):
    """Given allow_origin 未指定の通常起動
    When chrome-extension Origin から GET /auth/token を送る
    Then 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning)
    req = urllib.request.Request(f"{base}/auth/token", headers={"Origin": "chrome-extension://runtime-id"})

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 403


def test_get_auth_token_default_rejects_missing_origin(serve_dir, tmp_path):
    """Given allow_origin 未指定の通常起動
    When Origin なしで GET /auth/token を送る
    Then 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}/auth/token")

    assert exc_info.value.code == 403


def test_get_auth_token_web_origin_returns_403(serve_dir, tmp_path):
    """Given web origin (https://suno.com) からの GET /auth/token
    When Origin ヘッダ付きでリクエストする
    Then 403 を返す（token は background script のみに公開・#1217 SEC-001）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    req = urllib.request.Request(
        f"{base}/auth/token",
        headers={"Origin": "https://suno.com"},
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 403


def test_get_auth_token_no_origin_returns_403(serve_dir, tmp_path):
    """Given Origin ヘッダ無しの GET /auth/token
    When リクエストする
    Then 403 を返す（token は exact extension Origin にだけ公開する・#1217 SEC-001）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}/auth/token")

    assert exc_info.value.code == 403


def test_get_auth_token_other_extension_origin_returns_403(serve_dir, tmp_path):
    """Given extension origin lock と別 extension Origin
    When GET /auth/token を送る
    Then 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    req = urllib.request.Request(f"{base}/auth/token", headers={"Origin": "chrome-extension://otherextension"})

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 403


def test_post_downloaded_missing_token_returns_403(serve_dir, tmp_path):
    """Given Origin はあるが X-Serve-Token ヘッダが無い
    When POST /collections/<id>/downloaded を送る
    Then 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    payload = {"file_count": 1, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN},
        )

    assert exc_info.value.code == 403


def test_post_downloaded_wrong_token_returns_403(serve_dir, tmp_path):
    """Given 不正な X-Serve-Token ヘッダ
    When POST /collections/<id>/downloaded を送る
    Then 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    payload = {"file_count": 1, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": "wrong-token"},
        )

    assert exc_info.value.code == 403


def test_post_downloaded_valid_token_succeeds(serve_dir, tmp_path):
    """Given 正しい X-Serve-Token を GET /auth/token から取得
    When POST /collections/<id>/downloaded を送る
    Then 200 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 0, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}

    with _post(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        payload,
        headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
    ) as resp:
        assert resp.status == 200


def test_post_downloaded_default_rejects_extension_origin_without_exact_lock(serve_dir, tmp_path):
    """Given allow_origin 未指定の通常起動
    When chrome-extension Origin で /auth/token を取得しようとする
    Then 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning)
    origin = "chrome-extension://runtime-id"
    req = urllib.request.Request(f"{base}/auth/token", headers={"Origin": origin})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 403


def test_post_downloaded_default_rejects_missing_origin_without_exact_lock(serve_dir, tmp_path):
    """Given allow_origin 未指定の通常起動
    When Origin なしで /auth/token を取得しようとする
    Then 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}/auth/token")

    assert exc_info.value.code == 403


# ---------------------------------------------------------------------------
# Body size / type validation (#1217)
# ---------------------------------------------------------------------------


def test_post_downloaded_oversized_body_returns_413(serve_dir, tmp_path):
    """Given Content-Length > 10KB
    When POST /collections/<id>/downloaded を送る
    Then 413 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    # Create a body larger than 10KB
    oversized = b"x" * 10241

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            oversized,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 413


@pytest.mark.parametrize("raw_body", [b"[]", b'"x"', b"null"])
def test_post_downloaded_non_object_json_returns_400(serve_dir, tmp_path, raw_body):
    """Given JSON として valid だが object でない body
    When POST /collections/<id>/downloaded を送る
    Then 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        data=raw_body,
        headers={
            "Origin": _EXTENSION_ORIGIN,
            "Content-Type": "application/json",
            "X-Serve-Token": token,
        },
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 400


# ---------------------------------------------------------------------------
# ZIP extraction edge cases (#1217)
# ---------------------------------------------------------------------------


def test_post_downloaded_empty_zip_returns_500(serve_dir, tmp_path):
    """Given download_path が音声ファイルを含まない ZIP を指す
    When POST /collections/<id>/downloaded を送る
    Then placed_count == 0 で 500 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    # ZIP with only non-audio files
    zip_path = _make_zip(tmp_path / "no-audio.zip", {"readme.txt": b"hello", "notes.doc": b"world"})
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 2,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
        "download_path": str(zip_path),
    }

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 500


def test_post_downloaded_partial_zip_returns_500_and_does_not_set_music_downloaded(serve_dir, tmp_path):
    """Given prompts 2 件に対して ZIP 内の音声が 1 件
    When POST /collections/<id>/downloaded を送る
    Then 500 を返し assets.music_downloaded を設定しない。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[
            {"name": "曲A — Song A", "style": "s", "lyrics": ""},
            {"name": "曲B — Song B", "style": "s", "lyrics": ""},
        ],
    )
    zip_path = _make_zip(tmp_path / "partial.zip", {"Song A.mp3": b"audio1"})
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 2,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
        "download_path": str(zip_path),
    }

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 500
    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    assert not ws_path.exists()
    music_dir = planning / "20260601-clm-aaa-collection" / "02-Individual-music"
    assert not music_dir.exists() or list(music_dir.iterdir()) == []


def test_post_downloaded_unmatched_zip_returns_500_and_does_not_set_music_downloaded(serve_dir, tmp_path):
    """Given ZIP 内の音声数は足りるが prompts に 1 件もマッチしない
    When POST /collections/<id>/downloaded を送る
    Then placed_count=0 として 500 を返し assets.music_downloaded を設定しない。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[{"name": "曲A — Song A", "style": "s", "lyrics": ""}],
    )
    zip_path = _make_zip(tmp_path / "unmatched.zip", {"Unknown.mp3": b"audio1", "Unknown_1.mp3": b"audio2"})
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 2,
        "expected_file_count": 2,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
        "download_path": str(zip_path),
    }

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 500
    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    assert not ws_path.exists()
    music_dir = planning / "20260601-clm-aaa-collection" / "02-Individual-music"
    assert not music_dir.exists() or list(music_dir.iterdir()) == []


def test_post_downloaded_malformed_prompts_returns_500_and_does_not_update_artifacts(serve_dir, tmp_path):
    """Given suno-prompts.json が壊れている
    When POST /collections/<id>/downloaded を送る
    Then 500 を返し workflow-state / music を更新しない。
    """
    planning = tmp_path / "planning"
    coll = _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[{"name": "曲A — Song A", "style": "s", "lyrics": ""}],
    )
    (coll / "20-documentation" / "suno-prompts.json").write_text("{bad json", encoding="utf-8")
    zip_path = _make_zip(tmp_path / "malformed-prompts.zip", {"Song A.mp3": b"audio1"})
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 1,
        "expected_file_count": 1,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
        "download_path": str(zip_path),
    }

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 500
    error = _read_error_json(exc_info.value)["error"]
    assert error == "invalid suno-prompts.json"
    assert str(coll) not in error
    assert not (coll / "workflow-state.json").exists()
    music_dir = coll / "02-Individual-music"
    assert not music_dir.exists() or list(music_dir.iterdir()) == []


def test_post_downloaded_partial_zip_keeps_download_archive(serve_dir, tmp_path):
    """ZIP が期待数未満なら元 ZIP を残し、再取得や調査ができるようにする。"""
    planning = tmp_path / "planning"
    _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[
            {"name": "曲A — Song A", "style": "s", "lyrics": ""},
            {"name": "曲B — Song B", "style": "s", "lyrics": ""},
        ],
    )
    zip_path = _make_zip(tmp_path / "partial.zip", {"Song A.mp3": b"audio1"})
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            {
                "file_count": 1,
                "format": "mp3",
                "suno_playlist_url": "https://suno.com/playlist/abc",
                "download_path": str(zip_path),
            },
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 500
    assert zip_path.exists()


def test_post_downloaded_partial_zip_with_underreported_expected_count_returns_500(serve_dir, tmp_path):
    """Given prompts 2 件に対して range ZIP の音声が 1 件
    When expected_file_count=1 で POST /collections/<id>/downloaded を送る
    Then prompt_count * 2 を期待数として使い 500 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[
            {"name": "曲A — Song A", "style": "s", "lyrics": ""},
            {"name": "曲B — Song B", "style": "s", "lyrics": ""},
        ],
    )
    zip_path = _make_zip(tmp_path / "partial-range.zip", {"Song A.mp3": b"audio1"})
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 1,
        "expected_file_count": 1,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/range",
        "download_path": str(zip_path),
    }

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 500
    ws_path = planning / "20260601-clm-aaa-collection" / "workflow-state.json"
    assert not ws_path.exists()
    music_dir = planning / "20260601-clm-aaa-collection" / "02-Individual-music"
    assert not music_dir.exists() or list(music_dir.iterdir()) == []


def test_post_downloaded_success_includes_placed_count(serve_dir, tmp_path):
    """Given 有効な ZIP を download_path に指定
    When POST /collections/<id>/downloaded を送る
    Then レスポンスに placed_count が含まれる。
    """
    planning = tmp_path / "planning"
    _make_collection(
        planning,
        "20260601-clm-aaa-collection",
        entries=[{"name": "曲A — Song A", "style": "s", "lyrics": ""}],
    )
    zip_path = _make_zip(
        tmp_path / "valid.zip",
        {"Song A.mp3": b"audio1", "Song A_1.mp3": b"audio2"},
    )
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {
        "file_count": 2,
        "format": "mp3",
        "suno_playlist_url": "https://suno.com/playlist/abc",
        "download_path": str(zip_path),
    }

    with _post(
        f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
        payload,
        headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
    ) as resp:
        assert resp.status == 200
        result = json.loads(resp.read().decode("utf-8"))

    assert result["ok"] is True
    assert result["placed_count"] == 2


# ---------------------------------------------------------------------------
# Payload type validation (#1217 TEST-1217-003): non-string download_path / suno_playlist_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("download_path", ["/tmp"]),
        ("download_path", {"a": 1}),
        ("suno_playlist_url", ["url"]),
        ("suno_playlist_url", {}),
    ],
)
def test_post_downloaded_payload_type_validation(serve_dir, tmp_path, field, bad_value):
    """Given download_path or suno_playlist_url が非文字列型
    When POST /collections/<id>/downloaded を送る
    Then 400 を返す（#1217 型バリデーション）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260601-clm-aaa-collection", entries=[])
    base = serve_dir(planning, allow_origin=_EXTENSION_ORIGIN)
    token = _fetch_token(base)
    payload = {"file_count": 1, "format": "mp3", "suno_playlist_url": "https://suno.com/playlist/abc"}
    payload[field] = bad_value

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_COLLECTIONS_ROUTE}/20260601-clm-aaa-collection/downloaded",
            payload,
            headers={"Origin": _EXTENSION_ORIGIN, "X-Serve-Token": token},
        )

    assert exc_info.value.code == 400
