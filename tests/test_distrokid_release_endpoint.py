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
import urllib.parse
import urllib.request

import pytest

from youtube_automation.configuration.distrokid import (
    AiDisclosure,
    Distrokid,
    DistrokidProfile,
    SongwriterName,
)
from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.scripts.collection_serve import create_server
from youtube_automation.scripts.distrokid_release import (
    DISTROKID_ASSETS_PREFIX,
    DISTROKID_RELEASE_ROUTE,
    build_release_payload,
    resolve_asset_path,
)

_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
_SUNO_PROMPTS_ROUTE = "/suno/prompts.json"

_MP3_BYTES = b"ID3\x03\x00\x00\x00fake-mp3-bytes"
_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


def _profile() -> DistrokidProfile:
    """#813 新 schema の profile（nested songwriter + ai_disclosure）."""
    return DistrokidProfile(
        artist="ABYSS MI",
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
        "artist": "ABYSS MI",
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
        "credits": {
            "performer_role": "Synthesizer",
            "producer_role": "Producer",
        },
    }
    release = payload["release"]
    assert release["album_title"] == "city-nights"
    # serve は publish_target_at を YYYY-MM-DD へ正規化して返す（#932）。
    assert release["release_date"] == "2026-03-22"


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


def test_build_release_payload_main_only_yields_null_cover(tmp_path):
    """#1310: textless main.png だけでは DistroKid cover に fallback しない。"""
    collection = _make_collection(tmp_path, with_thumbnail=False)
    (collection / "10-assets" / "main.png").write_bytes(_PNG_BYTES)
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


def test_resolve_asset_path_rejects_nul_path(tmp_path):
    """Given NUL 文字を含むパス
    When resolve_asset_path を呼ぶ
    Then 不正 path として None。
    """
    collection = _make_collection(tmp_path)

    assert resolve_asset_path(collection, "02-Individual-music/bad\x00.mp3") is None


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

    def _start(*, collection_dir, distrokid, allow_origin=None, prompts=None, distrokid_source=None):
        prompts_path = tmp_path / "suno-prompts.json"
        prompts_path.write_text(json.dumps(prompts or []), encoding="utf-8")
        server = create_server(
            0,
            allow_origin,
            prompts_path=prompts_path,
            collection_dir=collection_dir,
            distrokid=distrokid,
            distrokid_source=distrokid_source,
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


def test_get_distrokid_release_json_broken_spec_returns_500(serve, tmp_path):
    """Given 破損 spec.json を持つ 30-distrokid disc source
    When `GET /distrokid/release.json`
    Then 接続切断ではなく 500 + JSON エラーボディを返す（#944）。
    """
    collection = _make_collection(tmp_path)
    disc_dir = collection / "30-distrokid" / "disc1-city-nights-vol1"
    disc_dir.mkdir(parents=True)
    (disc_dir / "01-foo.mp3").write_bytes(_MP3_BYTES)
    (collection / "30-distrokid" / "spec.json").write_text("{ broken", encoding="utf-8")
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(
        collection_dir=collection,
        distrokid=distrokid,
        distrokid_source="30-distrokid/disc1-city-nights-vol1",
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base}{DISTROKID_RELEASE_ROUTE}")

    err = exc_info.value
    assert err.code == 500
    body = json.loads(err.read().decode("utf-8"))
    assert "spec.json" in body["error"]


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


def test_get_distrokid_asset_decodes_percent_encoded_relpath(serve, tmp_path):
    """Given 日本語ファイル名を percent-encode した asset URL
    When `GET /distrokid/assets/<rel>` を呼ぶ
    Then decode 後の実ファイルを返す。
    """
    collection = _make_collection(tmp_path)
    filename = "01-不屈のビート.mp3"
    (collection / "02-Individual-music" / filename).write_bytes(_MP3_BYTES)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)
    relpath = urllib.parse.quote(f"02-Individual-music/{filename}", safe="/")

    url = f"{base}{DISTROKID_ASSETS_PREFIX}{relpath}"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "audio/mpeg"
        assert resp.read() == _MP3_BYTES


@pytest.mark.parametrize(
    ("encoded_relpath", "outside_filename"),
    [
        (urllib.parse.quote("../secret.mp3", safe=""), "secret.mp3"),
        (None, "absolute-secret.mp3"),
        (urllib.parse.quote("02-Individual-music/bad\x00.mp3", safe="/"), None),
    ],
)
def test_get_distrokid_asset_rejects_decoded_invalid_relpath(
    serve,
    tmp_path,
    encoded_relpath,
    outside_filename,
):
    """Given decode 後に traversal / absolute / NUL になる asset URL
    When `GET /distrokid/assets/<rel>` を呼ぶ
    Then 外部ファイルや不正 path は 404。
    """
    collection = _make_collection(tmp_path)
    if outside_filename is not None:
        outside = tmp_path / outside_filename
        outside.write_bytes(b"secret")
        if encoded_relpath is None:
            encoded_relpath = urllib.parse.quote(str(outside), safe="")
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)

    req = urllib.request.Request(f"{base}{DISTROKID_ASSETS_PREFIX}{encoded_relpath}")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


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


def test_distrokid_release_sets_cors_header_for_distrokid_origin(serve, tmp_path):
    """Given enabled な distrokid + distrokid.com の content script オリジン（#896）
    When `GET /distrokid/release.json`
    Then デフォルト起動でも Access-Control-Allow-Origin がそのオリジンを echo する。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)
    req = urllib.request.Request(
        f"{base}{DISTROKID_RELEASE_ROUTE}",
        headers={"Origin": "https://distrokid.com"},
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://distrokid.com"


def test_distrokid_release_omits_cors_header_for_unknown_origin(serve, tmp_path):
    """Given enabled な distrokid + 許可リスト外の web オリジン
    When `GET /distrokid/release.json`
    Then CORS ヘッダを付けない（許可リスト外は拒否・同一ポリシー）。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid)
    req = urllib.request.Request(
        f"{base}{DISTROKID_RELEASE_ROUTE}",
        headers={"Origin": "https://evil.com"},
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


# ---------------------------------------------------------------------------
# release_date 正規化（#932）
# ---------------------------------------------------------------------------


def test_release_date_date_only_string_passes_through(tmp_path):
    """Given publish_target_at が date のみ（"2026-07-01"）
    When build_release_payload を呼ぶ
    Then release_date がそのまま "2026-07-01"（正規化で変化しない）（#932）。
    """
    collection = _make_collection(tmp_path, publish_target_at="2026-07-01")
    distrokid = Distrokid(enabled=True, profile=_profile())

    release_date = build_release_payload(collection, distrokid)["release"]["release_date"]

    assert release_date == "2026-07-01"


def test_release_date_iso_datetime_normalized_to_date(tmp_path):
    """Given publish_target_at が ISO datetime（"2026-03-22T08:00:00+09:00"）
    When build_release_payload を呼ぶ
    Then release_date が YYYY-MM-DD に正規化される（#932）。
    """
    collection = _make_collection(tmp_path, publish_target_at="2026-03-22T08:00:00+09:00")
    distrokid = Distrokid(enabled=True, profile=_profile())

    release_date = build_release_payload(collection, distrokid)["release"]["release_date"]

    assert release_date == "2026-03-22"


def test_release_date_invalid_format_raises_config_error(tmp_path):
    """Given publish_target_at が parse 不能な文字列（"22/03/2026"）
    When build_release_payload を呼ぶ
    Then ConfigError（fail-loud。ISO 8601 形式でなければ設定ミスとして弾く）（#932）。
    """
    collection = _make_collection(tmp_path, publish_target_at="22/03/2026")
    distrokid = Distrokid(enabled=True, profile=_profile())

    with pytest.raises(ConfigError):
        build_release_payload(collection, distrokid)


def test_release_date_absent_yields_none(tmp_path):
    """Given publish_target_at 未設定（workflow-state.json 無し）
    When build_release_payload を呼ぶ
    Then release_date は None（注入 skip でフォームは空のまま）（#932）。
    """
    collection = _make_collection(tmp_path, publish_target_at=None)
    distrokid = Distrokid(enabled=True, profile=_profile())

    assert build_release_payload(collection, distrokid)["release"]["release_date"] is None
