"""yt-suno-serve (suno_serve) の挙動テスト.

issue #692: コレクションディレクトリ or suno-prompts.json パスを引数に取り、
`http://localhost:<PORT>/prompts.json` で JSON を提供するローカル HTTP サーバー。
CORS は Chrome 拡張オリジン (`chrome-extension://...`) のみ許可する。

契約（draft が実装すべき public API）:
- `resolve_prompts_path(path: Path) -> Path`
    dir → `<dir>/20-documentation/suno-prompts.json` / file → そのまま / 不在 → ConfigError。
- `is_origin_allowed(origin: str | None, allow_origin: str | None) -> bool`
    allow_origin=None なら `chrome-extension://` scheme を許可。
    allow_origin 指定時は完全一致のみ許可。
- `create_server(json_path: Path, port: int, allow_origin: str | None) -> ThreadingHTTPServer`
    `GET /prompts.json` で配列 JSON、`OPTIONS` で preflight を返すサーバーを生成する。
- `main()`
    argparse CLI（positional path / `--port`（既定 7873）/ `--allow-origin`）。
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request

import pytest

from youtube_automation.scripts.suno_serve import (
    create_server,
    is_origin_allowed,
    main,
    resolve_prompts_path,
)
from youtube_automation.utils.exceptions import ConfigError

_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


# ---------------------------------------------------------------------------
# resolve_prompts_path: パス解決（dir / file / 不在）
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
# is_origin_allowed: CORS 判定（scheme 検証 + --allow-origin 完全一致）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "allow_origin", "expected"),
    [
        # allow_origin 未指定: chrome-extension:// scheme を許可
        ("chrome-extension://abcdefghijklmnop", None, True),
        ("chrome-extension://anotherextensionid", None, True),
        # allow_origin 未指定: web オリジンは不許可
        ("http://localhost:3000", None, False),
        ("https://suno.com", None, False),
        # Origin ヘッダ無し
        (None, None, False),
        # allow_origin 指定: 完全一致のみ許可
        ("chrome-extension://exactid", "chrome-extension://exactid", True),
        ("chrome-extension://otherid", "chrome-extension://exactid", False),
        ("https://suno.com", "chrome-extension://exactid", False),
    ],
)
def test_is_origin_allowed(origin, allow_origin, expected):
    """Given (origin, allow_origin) の組
    When is_origin_allowed を呼ぶ
    Then 拡張オリジン scheme 検証 / 完全一致ロックの契約どおり真偽を返す。
    """
    assert is_origin_allowed(origin, allow_origin) is expected


# ---------------------------------------------------------------------------
# HTTP サーバー統合（create_server → 実リクエスト）
# ---------------------------------------------------------------------------


@pytest.fixture
def serve(tmp_path):
    """空きポートでサーバーを起動し base URL を返すファクトリ.

    port=0 を渡して OS に空きポートを割り当てさせる（固定ポート衝突回避）。
    """
    started = []

    def _start(entries, allow_origin=None):
        json_path = tmp_path / "suno-prompts.json"
        json_path.write_text(json.dumps(entries), encoding="utf-8")
        server = create_server(json_path, 0, allow_origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        port = server.server_address[1]
        return f"http://localhost:{port}"

    yield _start

    for server, thread in started:
        server.shutdown()
        thread.join(timeout=5)


def test_get_prompts_json_returns_array_body(serve):
    """Given prompts データを公開するサーバー
    When `GET /prompts.json`
    Then 200 で元データと一致する配列 JSON を返す。
    """
    entries = [{"name": "A — A", "style": "slow, jazz,\nscene", "lyrics": ""}]
    base = serve(entries)

    with urllib.request.urlopen(f"{base}/prompts.json") as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert body == entries


def test_get_prompts_json_sets_cors_header_for_extension_origin(serve):
    """Given 拡張オリジンからの GET
    When Origin が chrome-extension://
    Then Access-Control-Allow-Origin がそのオリジンを返す。
    """
    base = serve([{"name": "A", "style": "s", "lyrics": ""}])
    req = urllib.request.Request(
        f"{base}/prompts.json",
        headers={"Origin": _EXTENSION_ORIGIN},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN


def test_get_prompts_json_omits_cors_header_for_web_origin(serve):
    """Given web オリジンからの GET
    When Origin が https://...
    Then Access-Control-Allow-Origin ヘッダを付けない（拡張のみ許可）。
    """
    base = serve([{"name": "A", "style": "s", "lyrics": ""}])
    req = urllib.request.Request(
        f"{base}/prompts.json",
        headers={"Origin": "https://suno.com"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") is None


def test_options_preflight_allows_extension_origin(serve):
    """Given 拡張オリジンからの preflight
    When `OPTIONS /prompts.json`
    Then 2xx + Access-Control-Allow-Origin を返す。
    """
    base = serve([])
    req = urllib.request.Request(
        f"{base}/prompts.json",
        method="OPTIONS",
        headers={"Origin": _EXTENSION_ORIGIN},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.status in (200, 204)
        assert resp.headers.get("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN


def test_allow_origin_exact_match_locks_to_single_extension(serve):
    """Given --allow-origin で 1 拡張に固定
    When 別の拡張オリジンから GET
    Then 完全一致しないため CORS ヘッダを付けない。
    """
    locked = "chrome-extension://lockedextensionid"
    base = serve([], allow_origin=locked)
    req = urllib.request.Request(
        f"{base}/prompts.json",
        headers={"Origin": "chrome-extension://someotherid"},
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_help_flag_shows_usage_and_exits_zero(monkeypatch, capsys):
    """--help は argparse の usage を表示して exit 0 する."""
    monkeypatch.setattr(sys, "argv", ["yt-suno-serve", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()
