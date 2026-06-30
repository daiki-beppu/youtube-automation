"""yt-collection-serve の distrokid dir mode エンドポイント群（#934）のテスト.

issue #934 で新規追加するエンドポイント（dir mode 時のみ有効）:
- `GET /distrokid/collections` … collections_root 配下の disc 一覧 JSON 配列
- `GET /collections/<id>/distrokid/<disc>/release.json` … collection-scoped release payload
- `GET /collections/<id>/distrokid/assets/<rel>` … collection-scoped アセット配信
- `POST /distrokid/releases` … disc リリース記録

契約（draft が実装すべき public API）:
- `build_distrokid_collections_index(root, *, released_discs=None) -> list[dict]`
- `find_distrokid_discs(collection_dir) -> list[str]`
- `read_released_discs(root) -> set[str]`
- `write_distrokid_release(root, collection_id, disc, album_title) -> None`
"""

from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from youtube_automation.scripts.collection_serve import (
    _DISTROKID_COLLECTIONS_ROUTE,
    _DISTROKID_RELEASES_ROUTE,
    build_distrokid_collections_index,
    create_server,
    distrokid_releases_output_path,
    find_distrokid_discs,
    read_released_discs,
    write_distrokid_release,
)
from youtube_automation.utils.config.distrokid import (
    AiDisclosure,
    Distrokid,
    DistrokidProfile,
    SongwriterName,
)
from youtube_automation.utils.distrokid_spec import write_collection_spec

_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
_COLLECTIONS_ROUTE = "/collections"

_MP3_BYTES = b"ID3\x03\x00\x00\x00fake-mp3-bytes"
_JPG_BYTES = b"\xff\xd8\xff\xe0fake-jpg-bytes"


def _profile() -> DistrokidProfile:
    """テスト用 DistrokidProfile（#813 新 schema）."""
    return DistrokidProfile(
        language="ja",
        main_genre="Electronic",
        sub_genre="House",
        songwriter=SongwriterName(first="Jane", last="Doe"),
        ai_disclosure=AiDisclosure(),
    )


def _make_disc(
    collection_dir: Path,
    disc: str,
    *,
    mp3_count: int = 3,
    with_metadata: bool = True,
    album_title: str = "Test Album",
    with_cover: bool = True,
) -> Path:
    """コレクション配下に `30-distrokid/<disc>/` 構造を作る."""
    distrokid_dir = collection_dir / "30-distrokid"
    disc_dir = distrokid_dir / disc
    disc_dir.mkdir(parents=True)

    for i in range(mp3_count):
        (disc_dir / f"track-{i + 1:02d}.mp3").write_bytes(_MP3_BYTES)

    if with_metadata:
        # parse_album_metadata は `## アルバム情報` セクション内の `| アルバムタイトル | <value> |` を読む。
        metadata_content = (
            "## アルバム情報\n\n"
            "| 項目 | 値 |\n"
            "|---|---|\n"
            f"| アルバムタイトル | {album_title} |\n"
            "| アーティスト名 | Test Artist |\n"
        )
        (disc_dir / "metadata.md").write_text(metadata_content, encoding="utf-8")

    if with_cover:
        (distrokid_dir / "cover_art_3000.jpg").write_bytes(_JPG_BYTES)

    return disc_dir


def _make_collection(
    planning: Path,
    dir_name: str,
    *,
    discs: list[str] | None = None,
    with_metadata_for_disc: str | None = None,
) -> Path:
    """planning dir 配下にコレクションディレクトリ（`*-collection` 接尾辞必須）を作る."""
    coll = planning / dir_name
    coll.mkdir(parents=True)
    if discs:
        for disc in discs:
            with_meta = with_metadata_for_disc is None or disc == with_metadata_for_disc
            _make_disc(coll, disc, with_metadata=with_meta)
    return coll


# ---------------------------------------------------------------------------
# find_distrokid_discs: disc 列挙（mp3 有りのみ）
# ---------------------------------------------------------------------------


def test_find_distrokid_discs_returns_discs_with_mp3(tmp_path):
    """Given `30-distrokid/<disc>/` に mp3 が 1 つ以上あるコレクション
    When find_distrokid_discs を呼ぶ
    Then disc 名のリストをソート済みで返す。
    """
    coll = tmp_path / "20260526-test-collection"
    coll.mkdir()
    _make_disc(coll, "disc1-alpha")
    _make_disc(coll, "disc2-beta")

    result = find_distrokid_discs(coll)

    assert result == ["disc1-alpha", "disc2-beta"]


def test_find_distrokid_discs_excludes_dir_without_mp3(tmp_path):
    """Given mp3 が無い disc ディレクトリ（空 or 非 mp3 のみ）
    When find_distrokid_discs を呼ぶ
    Then mp3 無しの disc は除外される。
    """
    coll = tmp_path / "20260526-test-collection"
    coll.mkdir()
    _make_disc(coll, "disc1-good", mp3_count=2)
    # mp3 なし（空）の disc
    empty_disc = coll / "30-distrokid" / "disc2-empty"
    empty_disc.mkdir(parents=True)

    result = find_distrokid_discs(coll)

    assert result == ["disc1-good"]


def test_find_distrokid_discs_returns_empty_when_no_distrokid_dir(tmp_path):
    """Given `30-distrokid/` が存在しないコレクション
    When find_distrokid_discs を呼ぶ
    Then 空リストを返す（例外は投げない）。
    """
    coll = tmp_path / "20260526-test-collection"
    coll.mkdir()

    assert find_distrokid_discs(coll) == []


# ---------------------------------------------------------------------------
# read_released_discs / write_distrokid_release: 読み書き round-trip
# ---------------------------------------------------------------------------


def test_read_released_discs_returns_empty_when_file_absent(tmp_path):
    """Given distrokid-releases.json が存在しない root
    When read_released_discs を呼ぶ
    Then 空集合を返す（fail-loud せず「未配信」扱い）。
    """
    assert read_released_discs(tmp_path / "channel") == set()


def test_write_and_read_distrokid_release_round_trip(tmp_path):
    """Given write_distrokid_release で 1 件書いた root
    When read_released_discs を呼ぶ
    Then 書き込んだ `<collection_id>/<disc>` が集合に含まれる。
    """
    root = tmp_path / "channel"
    write_distrokid_release(root, "20260526-abc-collection", "disc1-alpha", "Alpha Vol.1")

    released = read_released_discs(root)

    assert "20260526-abc-collection/disc1-alpha" in released


def test_write_distrokid_release_stores_album_title_and_recorded_at(tmp_path):
    """Given write_distrokid_release
    When 書き込み後に JSON を直接読む
    Then album_title と recorded_at（文字列）が保存されている。
    """
    root = tmp_path / "channel"
    write_distrokid_release(root, "20260526-abc-collection", "disc1-alpha", "Alpha Vol.1")

    data = json.loads(distrokid_releases_output_path(root).read_text(encoding="utf-8"))
    entry = data["20260526-abc-collection/disc1-alpha"]

    assert entry["album_title"] == "Alpha Vol.1"
    assert isinstance(entry["recorded_at"], str)
    assert "T" in entry["recorded_at"]  # ISO 8601 に T が含まれる


def test_write_distrokid_release_overwrites_on_repost(tmp_path):
    """Given 同一 <collection_id>/<disc> に 2 回書く（再 POST 冪等）
    When read_released_discs を呼ぶ
    Then 重複せず 1 件のみ存在し、後勝ちで上書きされる。
    """
    root = tmp_path / "channel"
    write_distrokid_release(root, "20260526-abc-collection", "disc1-alpha", "Alpha Vol.1 First")
    write_distrokid_release(root, "20260526-abc-collection", "disc1-alpha", "Alpha Vol.1 Updated")

    data = json.loads(distrokid_releases_output_path(root).read_text(encoding="utf-8"))

    assert len(data) == 1
    assert data["20260526-abc-collection/disc1-alpha"]["album_title"] == "Alpha Vol.1 Updated"


def test_write_distrokid_release_leaves_no_temp_file(tmp_path):
    """Given write_distrokid_release の atomic write
    When 書き込み後に config/ を列挙する
    Then 中間 temp ファイルが残らず最終 JSON のみが存在する。
    """
    root = tmp_path / "channel"
    write_distrokid_release(root, "20260526-abc-collection", "disc1-alpha", "Alpha")

    files = sorted(p.name for p in distrokid_releases_output_path(root).parent.iterdir())

    assert files == ["distrokid-releases.json"]


# ---------------------------------------------------------------------------
# build_distrokid_collections_index: disc 一覧構築
# ---------------------------------------------------------------------------


def test_build_distrokid_collections_index_lists_discs(tmp_path):
    """Given 複数 disc を持つ複数コレクション
    When build_distrokid_collections_index を呼ぶ
    Then collection_id × disc の全組み合わせを列挙する。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-aa-collection", discs=["disc1-alpha", "disc2-beta"])
    _make_collection(planning, "20260527-bb-collection", discs=["disc1-gamma"])

    rows = build_distrokid_collections_index(planning)

    ids = [(r["collection_id"], r["disc"]) for r in rows]
    assert ("20260526-aa-collection", "disc1-alpha") in ids
    assert ("20260526-aa-collection", "disc2-beta") in ids
    assert ("20260527-bb-collection", "disc1-gamma") in ids


def test_build_distrokid_collections_index_excludes_collection_without_distrokid_dir(tmp_path):
    """Given `30-distrokid/` を持たないコレクション
    When build_distrokid_collections_index を呼ぶ
    Then そのコレクションはインデックスに出ない。
    """
    planning = tmp_path / "planning"
    # distrokid なしのコレクション
    no_dk = planning / "20260526-no-dk-collection"
    no_dk.mkdir(parents=True)
    # distrokid ありのコレクション
    _make_collection(planning, "20260527-with-dk-collection", discs=["disc1-alpha"])

    rows = build_distrokid_collections_index(planning)

    coll_ids = {r["collection_id"] for r in rows}
    assert "20260526-no-dk-collection" not in coll_ids
    assert "20260527-with-dk-collection" in coll_ids


def test_build_distrokid_collections_index_uses_metadata_album_title(tmp_path):
    """Given metadata.md に album_title がある disc
    When build_distrokid_collections_index を呼ぶ
    Then album_title が metadata.md 由来の値になる。
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-coding-focus-vol1", album_title="Coding Focus Vol.1")

    rows = build_distrokid_collections_index(planning)

    assert rows[0]["album_title"] == "Coding Focus Vol.1"


def test_build_distrokid_collections_index_fallback_album_title_when_no_metadata(tmp_path):
    """Given metadata.md が存在しない disc
    When build_distrokid_collections_index を呼ぶ
    Then album_title は disc 名を _kebab_to_title でフォールバックする（例外は投げない）。
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-coding-focus-vol1", with_metadata=False)

    rows = build_distrokid_collections_index(planning)

    # _kebab_to_title("disc1-coding-focus-vol1") → "Disc1 Coding Focus Vol1"
    assert rows[0]["album_title"] == "Disc1 Coding Focus Vol1"


def test_build_distrokid_collections_index_track_count(tmp_path):
    """Given disc 内に mp3 が 4 件
    When build_distrokid_collections_index を呼ぶ
    Then track_count が 4 になる。
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-alpha", mp3_count=4)

    rows = build_distrokid_collections_index(planning)

    assert rows[0]["track_count"] == 4


def test_build_distrokid_collections_index_released_false_without_capture_root(tmp_path):
    """Given released_discs=None（capture root 未指定相当）
    When build_distrokid_collections_index を呼ぶ
    Then 全件 released=False になる（#934 要件）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])

    rows = build_distrokid_collections_index(planning, released_discs=None)

    assert all(r["released"] is False for r in rows)


def test_build_distrokid_collections_index_released_true_for_recorded_disc(tmp_path):
    """Given distrokid-releases.json に記録済みの disc
    When released_discs を渡して build_distrokid_collections_index を呼ぶ
    Then 記録済み disc は released=True になる。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha", "disc2-beta"])
    released = {"20260526-abc-collection/disc1-alpha"}

    rows = {
        (r["collection_id"], r["disc"]): r for r in build_distrokid_collections_index(planning, released_discs=released)
    }

    assert rows[("20260526-abc-collection", "disc1-alpha")]["released"] is True
    assert rows[("20260526-abc-collection", "disc2-beta")]["released"] is False


def test_build_distrokid_collections_index_sorted_by_collection_then_disc(tmp_path):
    """Given 複数コレクション × 複数 disc
    When build_distrokid_collections_index を呼ぶ
    Then collection_id 昇順 → disc 昇順でソートされる。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260527-bb-collection", discs=["disc2-z", "disc1-a"])
    _make_collection(planning, "20260526-aa-collection", discs=["disc1-q"])

    rows = [(r["collection_id"], r["disc"]) for r in build_distrokid_collections_index(planning)]

    assert rows == [
        ("20260526-aa-collection", "disc1-q"),
        ("20260527-bb-collection", "disc1-a"),
        ("20260527-bb-collection", "disc2-z"),
    ]


# ---------------------------------------------------------------------------
# HTTP 統合テスト用 serve_dir_dk fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def serve_dir_dk(tmp_path):
    """dir mode + distrokid enabled でサーバーを起動し base URL を返すファクトリ（#934）.

    capture_root=None で起動すると released 判定なし・POST 無効のモード。
    """
    started = []

    def _start(
        planning: Path,
        *,
        distrokid: Distrokid | None = None,
        capture_root: Path | None = None,
        allow_origin: str | None = None,
    ):
        dk = distrokid or Distrokid(enabled=True, profile=_profile())
        playlist_capture = (capture_root, "dummy") if capture_root is not None else None
        server = create_server(
            0,
            allow_origin,
            prompts_path=None,
            collection_dir=None,
            distrokid=dk,
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


# ---------------------------------------------------------------------------
# GET /distrokid/collections
# ---------------------------------------------------------------------------


def test_get_distrokid_collections_returns_array(serve_dir_dk, tmp_path):
    """Given disc を持つ複数コレクション
    When `GET /distrokid/collections`
    Then 200 + JSON 配列（collection_id/name/disc/album_title/track_count/released）を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-aa-collection", discs=["disc1-alpha"])
    _make_collection(planning, "20260527-bb-collection", discs=["disc1-beta"])
    base = serve_dir_dk(planning)

    with urllib.request.urlopen(f"{base}{_DISTROKID_COLLECTIONS_ROUTE}") as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    coll_ids = {r["collection_id"] for r in body}
    assert "20260526-aa-collection" in coll_ids
    assert "20260527-bb-collection" in coll_ids
    # 必須フィールドが揃っている
    for row in body:
        assert set(row.keys()) >= {"collection_id", "name", "disc", "album_title", "track_count", "released"}


def test_get_distrokid_collections_excludes_no_mp3_dir(serve_dir_dk, tmp_path):
    """Given mp3 が無い disc ディレクトリ
    When `GET /distrokid/collections`
    Then mp3 無しの disc は含まれない。
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-good", mp3_count=2)
    # mp3 なし disc
    empty = coll / "30-distrokid" / "disc2-empty"
    empty.mkdir(parents=True)
    base = serve_dir_dk(planning)

    with urllib.request.urlopen(f"{base}{_DISTROKID_COLLECTIONS_ROUTE}") as resp:
        body = json.loads(resp.read().decode("utf-8"))

    discs = [r["disc"] for r in body]
    assert "disc1-good" in discs
    assert "disc2-empty" not in discs


def test_get_distrokid_collections_released_all_false_without_capture_root(serve_dir_dk, tmp_path):
    """Given capture_root 未指定
    When `GET /distrokid/collections`
    Then 全件 released=False。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    base = serve_dir_dk(planning, capture_root=None)

    with urllib.request.urlopen(f"{base}{_DISTROKID_COLLECTIONS_ROUTE}") as resp:
        body = json.loads(resp.read().decode("utf-8"))

    assert all(r["released"] is False for r in body)


def test_get_distrokid_collections_released_true_for_recorded_disc(serve_dir_dk, tmp_path):
    """Given capture_root 有り + distrokid-releases.json に記録済み disc
    When `GET /distrokid/collections`
    Then 記録済み disc の released=True、未記録は False。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha", "disc2-beta"])
    capture_root = tmp_path / "capture"
    write_distrokid_release(capture_root, "20260526-abc-collection", "disc1-alpha", "Alpha")
    base = serve_dir_dk(planning, capture_root=capture_root)

    with urllib.request.urlopen(f"{base}{_DISTROKID_COLLECTIONS_ROUTE}") as resp:
        body = json.loads(resp.read().decode("utf-8"))

    rows = {r["disc"]: r for r in body}
    assert rows["disc1-alpha"]["released"] is True
    assert rows["disc2-beta"]["released"] is False


def test_get_distrokid_collections_fallback_album_title_when_no_metadata(serve_dir_dk, tmp_path):
    """Given metadata.md が存在しない disc
    When `GET /distrokid/collections`
    Then album_title が _kebab_to_title フォールバック値になる（例外を投げない）。
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-coding-focus-vol1", with_metadata=False)
    base = serve_dir_dk(planning)

    with urllib.request.urlopen(f"{base}{_DISTROKID_COLLECTIONS_ROUTE}") as resp:
        body = json.loads(resp.read().decode("utf-8"))

    assert body[0]["album_title"] == "Disc1 Coding Focus Vol1"


# ---------------------------------------------------------------------------
# GET /collections/<id>/distrokid/<disc>/release.json
# ---------------------------------------------------------------------------


def test_get_collection_distrokid_release_json_returns_payload(serve_dir_dk, tmp_path):
    """Given 有効な collection_id + disc
    When `GET /collections/<id>/distrokid/<disc>/release.json`
    Then 200 で profile + release を持つ payload を返す。
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-alpha", mp3_count=2, album_title="Alpha Vol.1")
    base = serve_dir_dk(planning)

    url = f"{base}{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/disc1-alpha/release.json"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert "profile" in body
    assert "release" in body
    assert body["release"]["album_title"] == "Alpha Vol.1"
    assert len(body["release"]["tracks"]) == 2


def test_get_collection_distrokid_release_json_decodes_space_in_collection_id(serve_dir_dk, tmp_path):
    """Given スペース入り collection_id を URL encode した release.json URL
    When `GET /collections/<id>/distrokid/<disc>/release.json`
    Then decode 後の実 collection から payload を返す。
    """
    planning = tmp_path / "planning"
    collection_id = "20260526-rainy jazz-collection"
    coll = planning / collection_id
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-alpha", mp3_count=1, album_title="Rainy Jazz")
    base = serve_dir_dk(planning)
    encoded_id = urllib.parse.quote(collection_id, safe="")

    url = f"{base}{_COLLECTIONS_ROUTE}/{encoded_id}/distrokid/disc1-alpha/release.json"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert body["release"]["album_title"] == "Rainy Jazz"
    track = body["release"]["tracks"][0]
    assert track["asset_path"].startswith(f"{_COLLECTIONS_ROUTE}/{encoded_id}/distrokid/assets/")
    assert collection_id not in track["asset_path"]


def test_get_collection_distrokid_release_json_asset_path_is_collection_scoped(serve_dir_dk, tmp_path):
    """Given collection-scoped release.json
    When track の asset_path を確認する
    Then `/collections/<id>/distrokid/assets/...` 形式になっている（#934 要件）。
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-alpha", mp3_count=1, album_title="Alpha")
    base = serve_dir_dk(planning)

    url = f"{base}{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/disc1-alpha/release.json"
    with urllib.request.urlopen(url) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    track = body["release"]["tracks"][0]
    assert track["asset_path"].startswith(f"{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/assets/")
    # 単一 mode の `/distrokid/assets/` 形式ではない
    assert not track["asset_path"].startswith("/distrokid/assets/")


def test_get_collection_distrokid_release_json_unknown_id_returns_404(serve_dir_dk, tmp_path):
    """Given 存在しない collection_id
    When `GET /collections/<id>/distrokid/<disc>/release.json`
    Then 404 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    base = serve_dir_dk(planning)

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/does-not-exist-collection/distrokid/disc1-alpha/release.json"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_get_collection_distrokid_release_json_unknown_id_cors_json_404(serve_dir_dk, tmp_path):
    """Given 許可 Origin + 存在しない collection_id
    When `GET /collections/<id>/distrokid/<disc>/release.json`
    Then CORS 付き JSON 404 を返す（#1209: send_error CORS 統一）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    base = serve_dir_dk(planning)

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/does-not-exist-collection/distrokid/disc1-alpha/release.json",
        headers={"Origin": "https://www.distrokid.com"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    err = exc_info.value
    assert err.code == 404
    assert err.headers.get_content_type() == "application/json"
    assert err.headers.get("Access-Control-Allow-Origin") == "https://www.distrokid.com"
    assert json.loads(err.read().decode("utf-8")) == {"error": "Not Found"}


def test_get_collection_distrokid_release_json_unknown_disc_returns_404(serve_dir_dk, tmp_path):
    """Given 存在しない disc
    When `GET /collections/<id>/distrokid/<disc>/release.json`
    Then 404 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    base = serve_dir_dk(planning)

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/disc99-does-not-exist/release.json"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_get_collection_distrokid_release_json_traversal_returns_404(serve_dir_dk, tmp_path):
    """Given パストラバーサルを含む collection_id
    When `GET /collections/<id>/distrokid/<disc>/release.json`
    Then 404 を返す（ホワイトリスト弾き）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    base = serve_dir_dk(planning)

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/../20260526-abc-collection/distrokid/disc1-alpha/release.json"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_get_collection_distrokid_release_json_distrokid_disabled_returns_404(serve_dir_dk, tmp_path):
    """Given distrokid.enabled=False
    When `GET /collections/<id>/distrokid/<disc>/release.json`
    Then 404 を返す（distrokid 無効）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    base = serve_dir_dk(planning, distrokid=Distrokid(enabled=False))

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/disc1-alpha/release.json"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_get_collection_distrokid_release_json_broken_spec_returns_500(serve_dir_dk, tmp_path):
    """Given 破損 spec.json（存在するが不正 JSON）
    When `GET /collections/<id>/distrokid/<disc>/release.json`
    Then 接続切断ではなく 500 + JSON エラーボディ（CORS 付き）を返す（#944）。

    fail-loud の設計意図（破損 spec で古いデータを配信しない）は維持しつつ、
    拡張がメッセージなしのネットワークエラーではなく HTTP 500 を受け取れることを担保する。
    """
    planning = tmp_path / "planning"
    coll = _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    (coll / "30-distrokid" / "spec.json").write_text("{ broken", encoding="utf-8")
    base = serve_dir_dk(planning)

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/disc1-alpha/release.json",
        headers={"Origin": "https://distrokid.com"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    err = exc_info.value
    assert err.code == 500
    assert err.headers.get("Access-Control-Allow-Origin") == "https://distrokid.com"
    body = json.loads(err.read().decode("utf-8"))
    assert "spec.json" in body["error"]


# ---------------------------------------------------------------------------
# GET /collections/<id>/distrokid/assets/<rel>
# ---------------------------------------------------------------------------


def test_get_collection_distrokid_asset_serves_mp3(serve_dir_dk, tmp_path):
    """Given 有効な collection_id + disc + 実在 mp3
    When `GET /collections/<id>/distrokid/assets/<rel>`
    Then 200 + audio/mpeg で実バイト列を返す。
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    _make_disc(coll, "disc1-alpha", mp3_count=1)
    base = serve_dir_dk(planning)

    url = f"{base}{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/assets/30-distrokid/disc1-alpha/track-01.mp3"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "audio/mpeg"
        assert resp.read() == _MP3_BYTES


def test_get_collection_distrokid_asset_decodes_space_in_collection_id(serve_dir_dk, tmp_path):
    """Given スペース入り collection_id を URL encode した asset URL
    When `GET /collections/<id>/distrokid/assets/<rel>`
    Then decode 後の実 collection から asset を返す。
    """
    planning = tmp_path / "planning"
    collection_id = "20260526-rainy jazz-collection"
    _make_collection(planning, collection_id, discs=["disc1-alpha"])
    base = serve_dir_dk(planning)
    encoded_id = urllib.parse.quote(collection_id, safe="")

    url = f"{base}{_COLLECTIONS_ROUTE}/{encoded_id}/distrokid/assets/30-distrokid/disc1-alpha/track-01.mp3"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "audio/mpeg"
        assert resp.read() == _MP3_BYTES


def test_get_collection_distrokid_asset_traversal_returns_404(serve_dir_dk, tmp_path):
    """Given `../` を含む asset rel
    When `GET /collections/<id>/distrokid/assets/<rel>`
    Then 404 を返す（トラバーサルガード）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    # コレクション外に置いたファイルへのアクセスを試みる
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    base = serve_dir_dk(planning)

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/assets/../../../secret.txt"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


def test_get_collection_distrokid_asset_missing_returns_404(serve_dir_dk, tmp_path):
    """Given 存在しない asset パス
    When `GET /collections/<id>/distrokid/assets/<rel>`
    Then 404 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    base = serve_dir_dk(planning)

    req = urllib.request.Request(
        f"{base}{_COLLECTIONS_ROUTE}/20260526-abc-collection/distrokid/assets/30-distrokid/disc1-alpha/missing.mp3"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 404


# ---------------------------------------------------------------------------
# POST /distrokid/releases
# ---------------------------------------------------------------------------


def _post(url: str, body, *, headers: dict | None = None):
    """JSON body を POST する。"""
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers or {})
    return urllib.request.urlopen(req)


def _assert_json_error(err: urllib.error.HTTPError, *, status: int, message: str, expected_origin: str | None) -> None:
    assert err.code == status
    assert err.headers.get_content_type() == "application/json"
    assert err.headers.get("Access-Control-Allow-Origin") == expected_origin
    assert json.loads(err.read().decode("utf-8")) == {"error": message}


def _post_declared_length(url: str, *, declared_length: int | str, origin: str):
    """Content-Length だけを大きく宣言して POST する。"""
    parsed = urllib.parse.urlsplit(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    conn.putrequest("POST", path)
    conn.putheader("Host", parsed.netloc)
    conn.putheader("Origin", origin)
    conn.putheader("Content-Length", str(declared_length))
    conn.endheaders()
    return conn, conn.getresponse()


def test_post_distrokid_releases_writes_file_and_returns_recorded(tmp_path, serve_dir_dk):
    """Given 許可 Origin からの POST /distrokid/releases（capture_root あり）
    When 有効な body を送る
    Then 200 + `{recorded, path}` を返し、JSON ファイルに記録される。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    payload = {
        "collection_id": "20260526-abc-collection",
        "disc": "disc1-alpha",
        "album_title": "Alpha Vol.1",
    }
    with _post(f"{base}{_DISTROKID_RELEASES_ROUTE}", payload, headers={"Origin": _EXTENSION_ORIGIN}) as resp:
        assert resp.status == 200
        result = json.loads(resp.read().decode("utf-8"))

    assert result["recorded"] is True
    assert str(result["path"]).endswith("distrokid-releases.json")
    released = read_released_discs(capture_root)
    assert "20260526-abc-collection/disc1-alpha" in released


def test_post_distrokid_releases_ignores_query_side_inputs(tmp_path, serve_dir_dk):
    """Given root route に query だけで collection/disc を渡す
    When body が空の POST /distrokid/releases?... を送る
    Then 記録を書かず 400/404 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)
    query = urllib.parse.urlencode(
        {
            "collection_id": "20260526-abc-collection",
            "disc": "disc1-alpha",
            "album_title": "Alpha Vol.1",
        }
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_DISTROKID_RELEASES_ROUTE}?{query}",
            {},
            headers={"Origin": _EXTENSION_ORIGIN},
        )

    assert exc_info.value.code in {400, 404}
    assert not distrokid_releases_output_path(capture_root).exists()


def test_post_distrokid_releases_rejects_path_side_inputs(tmp_path, serve_dir_dk):
    """Given collection/disc を path 側へ入れた POST
    When POST /distrokid/releases/<collection>/<disc> を送る
    Then 記録を書かず 404 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_DISTROKID_RELEASES_ROUTE}/20260526-abc-collection/disc1-alpha",
            {"album_title": "Alpha Vol.1"},
            headers={"Origin": _EXTENSION_ORIGIN},
        )

    assert exc_info.value.code == 404
    assert not distrokid_releases_output_path(capture_root).exists()


def test_post_distrokid_releases_overwrite_on_repost(tmp_path, serve_dir_dk):
    """Given 同一 disc への再 POST（上書き冪等）
    When 2 回 POST する
    Then 後勝ちで album_title が更新される。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    for title in ["First", "Updated"]:
        _post(
            f"{base}{_DISTROKID_RELEASES_ROUTE}",
            {"collection_id": "20260526-abc-collection", "disc": "disc1-alpha", "album_title": title},
            headers={"Origin": _EXTENSION_ORIGIN},
        ).close()

    data = json.loads(distrokid_releases_output_path(capture_root).read_text(encoding="utf-8"))
    assert data["20260526-abc-collection/disc1-alpha"]["album_title"] == "Updated"


def test_post_distrokid_releases_without_capture_root_returns_404(tmp_path, serve_dir_dk):
    """Given capture_root 未指定（--playlist-capture-root 無し相当）
    When POST する
    Then 404 を返す（endpoint 自体が無い）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    base = serve_dir_dk(planning, capture_root=None)

    payload = {
        "collection_id": "20260526-abc-collection",
        "disc": "disc1-alpha",
        "album_title": "Alpha",
    }
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_DISTROKID_RELEASES_ROUTE}", payload, headers={"Origin": _EXTENSION_ORIGIN})

    _assert_json_error(exc_info.value, status=404, message="Not Found", expected_origin=_EXTENSION_ORIGIN)


def test_post_distrokid_releases_single_mode_with_capture_root_preserves_legacy_write(tmp_path):
    """Given single collection mode + capture_root
    When POST /distrokid/releases する
    Then dir mode の実在検証を要求せず従来どおり記録を書ける。
    """
    planning = tmp_path / "planning"
    collection_dir = _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    server = create_server(
        0,
        _EXTENSION_ORIGIN,
        prompts_path=None,
        collection_dir=collection_dir,
        distrokid=Distrokid(enabled=True, profile=_profile()),
        collections_root=None,
        playlist_capture=(capture_root, "dummy"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://localhost:{server.server_address[1]}"
    try:
        with _post(
            f"{base}{_DISTROKID_RELEASES_ROUTE}",
            {
                "collection_id": "20260526-abc-collection",
                "disc": "disc1-alpha",
                "album_title": "Alpha",
            },
            headers={"Origin": _EXTENSION_ORIGIN},
        ) as resp:
            assert resp.status == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)

    released = read_released_discs(capture_root)
    assert "20260526-abc-collection/disc1-alpha" in released


def test_post_distrokid_releases_without_origin_returns_403(tmp_path, serve_dir_dk):
    """Given Origin ヘッダ無しの POST
    When POST する
    Then 403 を返す（POST は Origin 必須）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    payload = {
        "collection_id": "20260526-abc-collection",
        "disc": "disc1-alpha",
        "album_title": "Alpha",
    }
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_DISTROKID_RELEASES_ROUTE}", payload)

    _assert_json_error(exc_info.value, status=403, message="Forbidden", expected_origin=None)


def test_post_distrokid_releases_with_disallowed_origin_returns_403(tmp_path, serve_dir_dk):
    """Given 許可リスト外 Origin からの POST
    When POST する
    Then CORS ヘッダー無しの JSON 403 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    payload = {
        "collection_id": "20260526-abc-collection",
        "disc": "disc1-alpha",
        "album_title": "Alpha",
    }
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_DISTROKID_RELEASES_ROUTE}", payload, headers={"Origin": "https://evil.com"})

    _assert_json_error(exc_info.value, status=403, message="Forbidden", expected_origin=None)


def test_post_distrokid_releases_invalid_json_returns_400(tmp_path, serve_dir_dk):
    """Given JSON として解釈できない body
    When 許可 Origin から POST する
    Then 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_DISTROKID_RELEASES_ROUTE}", b"{not json", headers={"Origin": _EXTENSION_ORIGIN})

    _assert_json_error(exc_info.value, status=400, message="Bad Request", expected_origin=_EXTENSION_ORIGIN)


def test_post_distrokid_releases_non_dict_body_returns_400(tmp_path, serve_dir_dk):
    """Given dict でない body（配列）
    When 許可 Origin から POST する
    Then 400 を返す（body は object 契約）。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(f"{base}{_DISTROKID_RELEASES_ROUTE}", [], headers={"Origin": _EXTENSION_ORIGIN})

    _assert_json_error(exc_info.value, status=400, message="Bad Request", expected_origin=_EXTENSION_ORIGIN)


def test_post_distrokid_releases_missing_field_returns_400(tmp_path, serve_dir_dk):
    """Given 必須フィールド欠落（disc が無い）
    When 許可 Origin から POST する
    Then 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_DISTROKID_RELEASES_ROUTE}",
            {"collection_id": "20260526-abc-collection", "album_title": "Alpha"},
            headers={"Origin": _EXTENSION_ORIGIN},
        )

    _assert_json_error(exc_info.value, status=400, message="Bad Request", expected_origin=_EXTENSION_ORIGIN)


def test_post_distrokid_releases_non_string_field_returns_400(tmp_path, serve_dir_dk):
    """Given 必須フィールドが string ではない
    When 許可 Origin から POST する
    Then 400 を返し、暗黙の str() 変換で記録しない。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_DISTROKID_RELEASES_ROUTE}",
            {"collection_id": 20260526, "disc": "disc1-alpha", "album_title": "Alpha"},
            headers={"Origin": _EXTENSION_ORIGIN},
        )

    _assert_json_error(exc_info.value, status=400, message="Bad Request", expected_origin=_EXTENSION_ORIGIN)
    assert not distrokid_releases_output_path(capture_root).exists()


def test_post_distrokid_releases_unknown_collection_returns_400(tmp_path, serve_dir_dk):
    """Given collections_root に存在しない collection_id
    When 許可 Origin から POST /distrokid/releases する
    Then リリース記録を書かず 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_DISTROKID_RELEASES_ROUTE}",
            {
                "collection_id": "20990101-missing-collection",
                "disc": "disc1-alpha",
                "album_title": "Ghost Album",
            },
            headers={"Origin": _EXTENSION_ORIGIN},
        )

    _assert_json_error(exc_info.value, status=400, message="Bad Request", expected_origin=_EXTENSION_ORIGIN)
    assert not distrokid_releases_output_path(capture_root).exists()


def test_post_distrokid_releases_unknown_disc_returns_400(tmp_path, serve_dir_dk):
    """Given collection は存在するが disc が存在しない
    When 許可 Origin から POST /distrokid/releases する
    Then リリース記録を書かず 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(
            f"{base}{_DISTROKID_RELEASES_ROUTE}",
            {
                "collection_id": "20260526-abc-collection",
                "disc": "disc99-missing",
                "album_title": "Ghost Album",
            },
            headers={"Origin": _EXTENSION_ORIGIN},
        )

    _assert_json_error(exc_info.value, status=400, message="Bad Request", expected_origin=_EXTENSION_ORIGIN)
    assert not distrokid_releases_output_path(capture_root).exists()


def test_post_distrokid_releases_body_too_large_returns_413(tmp_path, serve_dir_dk):
    """Given 1 MiB を超える body
    When 許可 Origin から POST /distrokid/releases する
    Then body を処理せず 413 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)
    conn, resp = _post_declared_length(
        f"{base}{_DISTROKID_RELEASES_ROUTE}",
        declared_length=1024 * 1024 + 1,
        origin=_EXTENSION_ORIGIN,
    )
    try:
        assert resp.status == 413
        assert resp.getheader("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN
        assert json.loads(resp.read().decode("utf-8")) == {"error": "Payload Too Large"}
    finally:
        conn.close()


def test_post_distrokid_releases_invalid_content_length_returns_400(tmp_path, serve_dir_dk):
    """Given invalid Content-Length
    When 許可 Origin から POST /distrokid/releases する
    Then body を処理せず 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)
    conn, resp = _post_declared_length(
        f"{base}{_DISTROKID_RELEASES_ROUTE}",
        declared_length="not-a-number",
        origin=_EXTENSION_ORIGIN,
    )
    try:
        assert resp.status == 400
        assert resp.getheader("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN
        assert json.loads(resp.read().decode("utf-8")) == {"error": "Bad Request"}
        assert not distrokid_releases_output_path(capture_root).exists()
    finally:
        conn.close()


def test_post_distrokid_releases_negative_content_length_returns_400(tmp_path, serve_dir_dk):
    """Given negative Content-Length
    When 許可 Origin から POST /distrokid/releases する
    Then body を処理せず 400 を返す。
    """
    planning = tmp_path / "planning"
    _make_collection(planning, "20260526-abc-collection", discs=["disc1-alpha"])
    capture_root = tmp_path / "capture"
    base = serve_dir_dk(planning, capture_root=capture_root)
    conn, resp = _post_declared_length(
        f"{base}{_DISTROKID_RELEASES_ROUTE}",
        declared_length=-1,
        origin=_EXTENSION_ORIGIN,
    )
    try:
        assert resp.status == 400
        assert resp.getheader("Access-Control-Allow-Origin") == _EXTENSION_ORIGIN
        assert json.loads(resp.read().decode("utf-8")) == {"error": "Bad Request"}
        assert not distrokid_releases_output_path(capture_root).exists()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# spec.json 優先（#941）: _read_disc_album_title / build_distrokid_collections_index
# ---------------------------------------------------------------------------


def _make_spec_for_disc(distrokid_dir: Path, disc_slug: str, album_title: str) -> None:
    """30-distrokid/spec.json に指定 disc のエントリを書き込む（#941 テスト用）."""
    spec = {
        "version": 1,
        "artist": "Test Artist",
        "language": "English",
        "genre_primary": "Electronic",
        "genre_secondary": None,
        "label": None,
        "discs": [
            {
                "slug": disc_slug,
                "album_title": album_title,
                "tracks": [],
            }
        ],
    }
    write_collection_spec(distrokid_dir, spec)


def test_build_distrokid_collections_index_uses_spec_album_title(tmp_path):
    """Given spec.json に album_title がある disc（metadata.md の値と異なる）
    When build_distrokid_collections_index を呼ぶ
    Then spec の album_title が index に反映される（spec 優先）。
    (#941)
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    disc_slug = "disc1-coding-focus-vol1"
    # metadata.md は "MD Album Title" だが spec は "Spec Album Title"
    _make_disc(coll, disc_slug, album_title="MD Album Title")
    distrokid_dir = coll / "30-distrokid"
    _make_spec_for_disc(distrokid_dir, disc_slug, "Spec Album Title")

    rows = build_distrokid_collections_index(planning)

    assert rows[0]["album_title"] == "Spec Album Title"


def test_build_distrokid_collections_index_spec_corrupted_falls_back_to_metadata(tmp_path):
    """Given 破損した spec.json + 有効な metadata.md
    When build_distrokid_collections_index を呼ぶ
    Then spec 破損は fail-soft で metadata.md の値にフォールバックする（500 にならない）。
    (#941)
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    disc_slug = "disc1-coding-focus-vol1"
    _make_disc(coll, disc_slug, album_title="MD Album Title")

    # 破損した spec.json を書き込む
    distrokid_dir = coll / "30-distrokid"
    (distrokid_dir / "spec.json").write_text("{ broken json }", encoding="utf-8")

    rows = build_distrokid_collections_index(planning)

    # spec 破損は fail-soft → metadata.md の album_title にフォールバック
    assert rows[0]["album_title"] == "MD Album Title"


def test_build_distrokid_collections_index_spec_corrupted_falls_back_to_kebab(tmp_path):
    """Given 破損した spec.json + metadata.md 無し
    When build_distrokid_collections_index を呼ぶ
    Then spec 破損・metadata.md 不在の両方を fail-soft で通過し kebab フォールバック（500 にならない）。
    (#941)
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    disc_slug = "disc1-coding-focus-vol1"
    _make_disc(coll, disc_slug, with_metadata=False)

    # 破損した spec.json を書き込む
    distrokid_dir = coll / "30-distrokid"
    (distrokid_dir / "spec.json").write_text("{ broken json }", encoding="utf-8")

    rows = build_distrokid_collections_index(planning)

    # kebab_to_title("disc1-coding-focus-vol1") → "Disc1 Coding Focus Vol1"
    assert rows[0]["album_title"] == "Disc1 Coding Focus Vol1"


def test_get_distrokid_collections_spec_album_title_reflected_in_index(serve_dir_dk, tmp_path):
    """Given spec.json に album_title がある disc
    When `GET /distrokid/collections`
    Then spec の album_title が collections index に反映される。
    (#941)
    """
    planning = tmp_path / "planning"
    coll = planning / "20260526-abc-collection"
    coll.mkdir(parents=True)
    disc_slug = "disc1-coding-focus-vol1"
    _make_disc(coll, disc_slug, album_title="MD Album Title")
    distrokid_dir = coll / "30-distrokid"
    _make_spec_for_disc(distrokid_dir, disc_slug, "Spec Album Title")
    base = serve_dir_dk(planning)

    with urllib.request.urlopen(f"{base}{_DISTROKID_COLLECTIONS_ROUTE}") as resp:
        body = json.loads(resp.read().decode("utf-8"))

    assert body[0]["album_title"] == "Spec Album Title"
