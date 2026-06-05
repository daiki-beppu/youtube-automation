"""yt-collection-serve の distrokid サブパス（#698）の挙動テスト.

issue #698 で新規追加するエンドポイント:
- `GET /distrokid/release.json` … `config.distrokid.profile`（静的）と
  `collections/planning/<theme>/` の動的データ（アルバム名 / 曲ファイル /
  ジャケット / リリース日）をマージして返す。
- `GET /distrokid/assets/<path>` … 曲・ジャケットファイルを binary 配信。
- `distrokid.enabled == false` または未配置（`distrokid=None`）では
  `/distrokid/*` が 404。`/suno/prompts.json` は引き続き 200。
- CORS は `/suno/*` と同一ポリシー。

契約（draft が実装すべき public API）:
- `build_release_payload(collection_dir: Path, distrokid: Distrokid) -> dict`
- `resolve_asset_path(collection_dir: Path, relpath: str) -> Path | None`
    トラバーサル（`..` / 絶対パス）と不在は None。
- ルート定数 `DISTROKID_RELEASE_ROUTE` / `DISTROKID_ASSETS_PREFIX`
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from youtube_automation.scripts.collection_serve import create_server
from youtube_automation.scripts.distrokid_release import (
    DISTROKID_ASSETS_PREFIX,
    DISTROKID_RELEASE_ROUTE,
    build_release_payload,
    resolve_asset_path,
)
from youtube_automation.utils.config.distrokid import (
    AiDisclosure,
    Distrokid,
    DistrokidProfile,
    SongwriterName,
)

_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
_SUNO_PROMPTS_ROUTE = "/suno/prompts.json"

_MP3_BYTES = b"ID3\x03\x00\x00\x00fake-mp3-bytes"
_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


def _profile() -> DistrokidProfile:
    """#813 新 schema の profile（nested songwriter + ai_disclosure）."""
    return DistrokidProfile(
        language="ja",
        main_genre="Electronic",
        sub_genre="House",
        songwriter=SongwriterName(first="Jane", last="Doe"),
        ai_disclosure=AiDisclosure(),
    )


def _make_collection(tmp_path, *, with_thumbnail=True, publish_target_at=None):
    """標準コレクション構造を tmp に作る.

    番号 + チャンネルプレフィックス付きのディレクトリ名にして
    `CollectionPaths.collection_name` が "city-nights" を返すようにする。
    """
    collection = tmp_path / "20260322-cn-city-nights"
    music = collection / "02-Individual-music"
    assets = collection / "10-assets"
    music.mkdir(parents=True)
    assets.mkdir(parents=True)

    (music / "01-foo.mp3").write_bytes(_MP3_BYTES)
    (music / "02-bar.mp3").write_bytes(_MP3_BYTES)
    if with_thumbnail:
        (assets / "thumbnail.png").write_bytes(_PNG_BYTES)
    if publish_target_at is not None:
        (collection / "workflow-state.json").write_text(
            json.dumps({"planning": {"publish_target_at": publish_target_at}}),
            encoding="utf-8",
        )
    return collection


# ---------------------------------------------------------------------------
# build_release_payload: 純データ組み立て（profile 静的 + collection 動的）
# ---------------------------------------------------------------------------


def test_build_release_payload_merges_profile_and_dynamic_data(tmp_path):
    """Given enabled な distrokid + 標準コレクション
    When build_release_payload を呼ぶ
    Then profile はそのまま、release は album/tracks/cover/release_date を持つ。
    """
    collection = _make_collection(tmp_path, publish_target_at="2026-03-22T08:00:00+09:00")
    distrokid = Distrokid(enabled=True, profile=_profile())

    payload = build_release_payload(collection, distrokid)

    # build_release_payload は asdict(profile) で nested dataclass を再帰的に dict 化する。
    assert payload["profile"] == {
        "language": "ja",
        "main_genre": "Electronic",
        "sub_genre": "House",
        "songwriter": {"first": "Jane", "last": "Doe", "middle": None},
        "ai_disclosure": {
            "enabled": True,
            "lyrics": True,
            "music": True,
            "recording_scope": "full",
            "partial_audio_type": None,
            "artist_persona": True,
            "apply_to_all": True,
        },
    }
    release = payload["release"]
    assert release["album_title"] == "city-nights"
    assert release["release_date"] == "2026-03-22T08:00:00+09:00"


def test_build_release_payload_tracks_are_sorted_with_asset_paths(tmp_path):
    """Given 02-Individual-music/*.mp3
    When build_release_payload を呼ぶ
    Then tracks がソート済みで title/filename/asset_path を持つ。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())

    tracks = build_release_payload(collection, distrokid)["release"]["tracks"]

    assert [t["filename"] for t in tracks] == ["01-foo.mp3", "02-bar.mp3"]
    assert tracks[0]["title"] == "01-foo"
    assert tracks[0]["asset_path"] == f"{DISTROKID_ASSETS_PREFIX}02-Individual-music/01-foo.mp3"


def test_build_release_payload_cover_uses_thumbnail(tmp_path):
    """Given 10-assets/thumbnail.png
    When build_release_payload を呼ぶ
    Then cover が filename/asset_path を持つ。
    """
    collection = _make_collection(tmp_path, with_thumbnail=True)
    distrokid = Distrokid(enabled=True, profile=_profile())

    cover = build_release_payload(collection, distrokid)["release"]["cover"]

    assert cover["filename"] == "thumbnail.png"
    assert cover["asset_path"] == f"{DISTROKID_ASSETS_PREFIX}10-assets/thumbnail.png"


def test_build_release_payload_no_thumbnail_yields_null_cover(tmp_path):
    """Given サムネイル無し
    When build_release_payload を呼ぶ
    Then cover は None。
    """
    collection = _make_collection(tmp_path, with_thumbnail=False)
    distrokid = Distrokid(enabled=True, profile=_profile())

    assert build_release_payload(collection, distrokid)["release"]["cover"] is None


def test_build_release_payload_no_workflow_state_yields_null_release_date(tmp_path):
    """Given workflow-state.json 無し
    When build_release_payload を呼ぶ
    Then release_date は None（発明せず null）。
    """
    collection = _make_collection(tmp_path, publish_target_at=None)
    distrokid = Distrokid(enabled=True, profile=_profile())

    assert build_release_payload(collection, distrokid)["release"]["release_date"] is None


# ---------------------------------------------------------------------------
# resolve_asset_path: トラバーサルガード
# ---------------------------------------------------------------------------


def test_resolve_asset_path_returns_existing_file(tmp_path):
    """Given コレクション配下の実在ファイル
    When resolve_asset_path を呼ぶ
    Then その実体パスを返す。
    """
    collection = _make_collection(tmp_path)

    resolved = resolve_asset_path(collection, "02-Individual-music/01-foo.mp3")

    assert resolved is not None
    assert resolved.read_bytes() == _MP3_BYTES


def test_resolve_asset_path_rejects_parent_traversal(tmp_path):
    """Given `../` を含む相対パス
    When resolve_asset_path を呼ぶ
    Then コレクション外への脱出は None（トラバーサルガード）。
    """
    collection = _make_collection(tmp_path)
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")

    assert resolve_asset_path(collection, "../secret.txt") is None


def test_resolve_asset_path_rejects_absolute_path(tmp_path):
    """Given 絶対パス
    When resolve_asset_path を呼ぶ
    Then コレクション配下でないため None。
    """
    collection = _make_collection(tmp_path)

    assert resolve_asset_path(collection, "/etc/passwd") is None


def test_resolve_asset_path_missing_file_returns_none(tmp_path):
    """Given コレクション配下だが不在のパス
    When resolve_asset_path を呼ぶ
    Then None。
    """
    collection = _make_collection(tmp_path)

    assert resolve_asset_path(collection, "02-Individual-music/does-not-exist.mp3") is None


# ---------------------------------------------------------------------------
# HTTP 統合
# ---------------------------------------------------------------------------


@pytest.fixture
def serve(tmp_path):
    """空きポートでサーバーを起動し base URL を返すファクトリ.

    distrokid / collection_dir を明示注入できる（境界での解決をテストが代替）。
    """
    started = []

    def _start(*, collection_dir, distrokid, allow_origin=None, prompts=None):
        prompts_path = tmp_path / "suno-prompts.json"
        prompts_path.write_text(json.dumps(prompts or []), encoding="utf-8")
        server = create_server(
            0,
            allow_origin,
            prompts_path=prompts_path,
            collection_dir=collection_dir,
            distrokid=distrokid,
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


def test_get_distrokid_release_json_returns_merged_payload(serve, tmp_path):
    """Given enabled な distrokid
    When `GET /distrokid/release.json`
    Then 200 で build_release_payload と一致する JSON を返す。
    """
    collection = _make_collection(tmp_path, publish_target_at="2026-03-22T08:00:00+09:00")
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)

    with urllib.request.urlopen(f"{base}{DISTROKID_RELEASE_ROUTE}") as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert body == build_release_payload(collection, distrokid)


def test_get_distrokid_asset_serves_binary_with_mime(serve, tmp_path):
    """Given enabled な distrokid
    When `GET /distrokid/assets/02-Individual-music/01-foo.mp3`
    Then 200 + audio/mpeg で実バイト列を返す。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)

    url = f"{base}{DISTROKID_ASSETS_PREFIX}02-Individual-music/01-foo.mp3"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "audio/mpeg"
        assert resp.read() == _MP3_BYTES


def test_get_distrokid_asset_missing_returns_404(serve, tmp_path):
    """Given enabled な distrokid
    When 不在の assets パスを GET
    Then 404（resolve_asset_path が None）。

    `..` を含む真のトラバーサルはクライアント（urllib）がパスを正規化して畳むため、
    HTTP 経由では再現しづらい。トラバーサルガード自体は resolve_asset_path の
    関数レベルテストで担保し、ここでは handler が None を 404 に写すことを検証する。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)

    url = f"{base}{DISTROKID_ASSETS_PREFIX}does-not-exist.mp3"
    req = urllib.request.Request(url)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_distrokid_release_sets_cors_header_for_extension_origin(serve, tmp_path):
    """Given enabled な distrokid + 拡張オリジン
    When `GET /distrokid/release.json`
    Then `/suno/*` と同一ポリシーで CORS ヘッダを付与する。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)
    req = urllib.request.Request(
        f"{base}{DISTROKID_RELEASE_ROUTE}",
        headers={"Origin": _EXTENSION_ORIGIN},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN


def test_distrokid_release_omits_cors_header_for_web_origin(serve, tmp_path):
    """Given enabled な distrokid + web オリジン
    When `GET /distrokid/release.json`
    Then CORS ヘッダを付けない（拡張のみ許可・同一ポリシー）。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)
    req = urllib.request.Request(
        f"{base}{DISTROKID_RELEASE_ROUTE}",
        headers={"Origin": "https://distrokid.com"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") is None


# ---------------------------------------------------------------------------
# 404: disabled / 未配置（要件6 + 受け入れ基準）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "distrokid",
    [
        None,
        Distrokid(enabled=False),
    ],
    ids=["distrokid_none", "distrokid_disabled"],
)
def test_distrokid_release_404_when_disabled_or_absent(serve, tmp_path, distrokid):
    """Given distrokid=None または enabled=False
    When `GET /distrokid/release.json`
    Then 404。
    """
    collection = _make_collection(tmp_path)
    base = serve(collection_dir=collection, distrokid=distrokid)
    req = urllib.request.Request(f"{base}{DISTROKID_RELEASE_ROUTE}")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


@pytest.mark.parametrize(
    "distrokid",
    [
        None,
        Distrokid(enabled=False),
    ],
    ids=["distrokid_none", "distrokid_disabled"],
)
def test_distrokid_assets_404_when_disabled_or_absent(serve, tmp_path, distrokid):
    """Given distrokid=None または enabled=False
    When `GET /distrokid/assets/<existing-file>`
    Then 実体が存在しても 404（機能ごと無効）。
    """
    collection = _make_collection(tmp_path)
    base = serve(collection_dir=collection, distrokid=distrokid)
    url = f"{base}{DISTROKID_ASSETS_PREFIX}02-Individual-music/01-foo.mp3"
    req = urllib.request.Request(url)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_suno_prompts_still_served_when_distrokid_disabled(serve, tmp_path):
    """Given distrokid=None（distrokid.json 未配置のチャンネル相当）
    When 同サーバーの `GET /suno/prompts.json`
    Then 200（distrokid 無効でも suno は素通り・受け入れ基準）。
    """
    collection = _make_collection(tmp_path)
    entries = [{"name": "A", "style": "s", "lyrics": ""}]
    base = serve(collection_dir=collection, distrokid=None, prompts=entries)

    with urllib.request.urlopen(f"{base}{_SUNO_PROMPTS_ROUTE}") as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8")) == entries
