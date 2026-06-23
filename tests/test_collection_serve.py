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
from pathlib import Path

import pytest

from youtube_automation.scripts.collection_serve import (
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
#       各 collection を `{id, name, has_prompts, pattern_count}` に写像する。
#       id=ディレクトリ名 / name=CollectionPaths.collection_name /
#       has_prompts=docs json の存在 / pattern_count=entries 数 or None。
# - `resolve_collection_prompts_path(root: Path, cid: str) -> Path | None`
#       cid が既知の collection dir 名のとき docs json パスを返す。
#       未知 id / トラバーサル文字列は None（fail-loud せずホワイトリスト弾き）。
# - `create_server(..., collections_root: Path | None=None)`
#       collections_root 指定時は dir mode（`/collections` 系を配信し
#       `/suno/prompts.json` は配信しない）。既定 None は単一ファイル mode。
# ---------------------------------------------------------------------------


def _make_collection(planning: Path, dir_name: str, entries=None) -> Path:
    """planning dir 配下に `<dir_name>/20-documentation/suno-prompts.json` を作る。

    `entries` が None のとき json を置かない（has_prompts=False のケース）。
    """
    coll = planning / dir_name
    docs = coll / "20-documentation"
    docs.mkdir(parents=True)
    if entries is not None:
        (docs / "suno-prompts.json").write_text(json.dumps(entries), encoding="utf-8")
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


def test_build_collections_index_reports_has_prompts_and_pattern_count(tmp_path):
    """Given prompts 有り(2件) と prompts 無しの collection
    When build_collections_index を呼ぶ
    Then has_prompts と pattern_count を正しく写像する（無しは pattern_count=None）。
    """
    _make_collection(
        tmp_path,
        "20260601-clm-with-prompts-collection",
        entries=[{"name": "A", "style": "s", "lyrics": ""}, {"name": "B", "style": "s", "lyrics": ""}],
    )
    _make_collection(tmp_path, "20260602-clm-no-prompts-collection", entries=None)

    index = {row["id"]: row for row in build_collections_index(tmp_path)}

    with_prompts = index["20260601-clm-with-prompts-collection"]
    assert with_prompts["has_prompts"] is True
    assert with_prompts["pattern_count"] == 2

    no_prompts = index["20260602-clm-no-prompts-collection"]
    assert no_prompts["has_prompts"] is False
    assert no_prompts["pattern_count"] is None


def test_build_collections_index_name_strips_date_and_channel_prefix(tmp_path):
    """Given `<date>-<channel>-<theme>-collection` 形式の dir
    When build_collections_index を呼ぶ
    Then id=dir 名そのまま / name=CollectionPaths.collection_name（日付＋チャンネル接頭辞除去）。
    """
    _make_collection(tmp_path, "20260601-clm-midnight-mood-collection", entries=[])

    row = build_collections_index(tmp_path)[0]

    assert row["id"] == "20260601-clm-midnight-mood-collection"
    assert row["name"] == "midnight-mood-collection"


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

    def _start(planning: Path, allow_origin=None):
        server = create_server(
            0,
            allow_origin,
            prompts_path=None,
            collection_dir=None,
            distrokid=None,
            collections_root=planning,
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
    Then `[{id, name, has_prompts, pattern_count}]` を返す。
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
    # #893 追加要件 B: build_collections_index は各 entry に mapped を含める。
    # dir mode の serve_dir fixture は playlist_capture を渡さない（prefix 無）ため全件 mapped=False。
    assert by_id["20260601-clm-aaa-collection"] == {
        "id": "20260601-clm-aaa-collection",
        "name": "aaa-collection",
        "has_prompts": True,
        "pattern_count": 1,
        "mapped": False,
        "playlist_name": None,
    }
    assert by_id["20260602-clm-bbb-collection"]["has_prompts"] is False
    assert by_id["20260602-clm-bbb-collection"]["pattern_count"] is None


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
