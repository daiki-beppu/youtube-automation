"""`--distrokid-source`（30-distrokid disc 単位提出）の payload / 配線テスト（#819）.

`yt-collection-serve <collection> --distrokid-source 30-distrokid/disc1-...` 指定時、
`build_release_payload` が `<collection>/<source>/` を source として:
- tracks を `<source>/*.mp3` ソート順で組み立てる
- track[].title を `<source>/metadata.md` のトラック表から引く
- cover を `<collection>/30-distrokid/cover_art_3000.jpg` 優先で選ぶ
- album_title を metadata.md 枠（空なら disc dirname kebab→Title）から決める
- language は profile（config/channel/distrokid.json）を権威に使う（metadata.md
  「言語」セルは転記用テンプレで payload には影響しない、#888）
ことを検証する。distrokid_source 未指定は従来経路（後方互換）。

契約（draft が実装すべき public API、後方互換拡張）:
- `build_release_payload(collection_dir, distrokid, *, distrokid_source: str | None = None) -> dict`
- `create_server(..., distrokid_source: str | None = None)` … 値を末端の payload まで伝搬。
- release.json の schema（profile / release.tracks[].{title,filename,asset_path} /
  release.cover.{filename,asset_path}）は #815 のまま不変（拡張側契約）。
"""

from __future__ import annotations

import json
import threading
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
)
from youtube_automation.utils.distrokid_spec import write_collection_spec

_EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
_MP3_BYTES = b"ID3\x03\x00\x00\x00fake-mp3-bytes"
_COVER_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"

_DISC_SOURCE = "30-distrokid/disc1-coding-focus-vol1"

# 下流 disc1-coding-focus-vol1/metadata.md のトラック表（全 25 曲）。
# (number, title, filename) ／ 尺・ISRC・作詞・作曲は空欄運用。
_DISC1_TRACKS = [
    (1, "Slip Right Through", "01-slip-right-through.mp3"),
    (2, "Easy Release", "02-easy-release.mp3"),
    (3, "Easy Release — Reprise", "03-easy-release.mp3"),
    (4, "Slip Right Through — Reprise", "04-slip-right-through.mp3"),
    (5, "Slip It On", "05-slip-it-on.mp3"),
    (6, "Slip It Loose", "06-slip-it-loose.mp3"),
    (7, "Slip Right Through — Dusk", "07-slip-right-through.mp3"),
    (8, "Let It Glide", "08-let-it-glide.mp3"),
    (9, "Slip It Loose — Reprise", "09-slip-it-loose.mp3"),
    (10, "Slip It Softly", "10-slip-it-softly.mp3"),
    (11, "Easy Let Go", "11-easy-let-go.mp3"),
    (12, "Dust In The Light", "12-dust-in-the-light.mp3"),
    (13, "Never Leaves", "13-never-leaves.mp3"),
    (14, "Soft Dust Glow", "14-soft-dust-glow.mp3"),
    (15, "Dust On The Spin", "15-dust-on-the-spin.mp3"),
    (16, "Dust In The Light — Reprise", "16-dust-in-the-light.mp3"),
    (17, "Dust On The Vinyl", "17-dust-on-the-vinyl.mp3"),
    (18, "Dust On Vinyl", "18-dust-on-vinyl.mp3"),
    (19, "Dust In The Light — Dusk", "19-dust-in-the-light.mp3"),
    (20, "Dust In The Light — Late Set", "20-dust-in-the-light.mp3"),
    (21, "Dust On The Groove", "21-dust-on-the-groove.mp3"),
    (22, "Velvet Light", "22-velvet-light.mp3"),
    (23, "Velvet Hour", "23-velvet-hour.mp3"),
    (24, "Velvet Light — Reprise", "24-velvet-light.mp3"),
    (25, "Velvet Hour — Reprise", "25-velvet-hour.mp3"),
]


def _profile() -> DistrokidProfile:
    """profile.language は `ja`（metadata.md override 前の元値）。"""
    return DistrokidProfile(
        artist="ABYSS MI",
        language="ja",
        main_genre="Electronic",
        sub_genre="House",
        songwriter=SongwriterName(first="Jane", last="Doe"),
        ai_disclosure=AiDisclosure(),
    )


def _album_value(value: str | None) -> str:
    """アルバム情報セル。None なら HTML コメント枠（未記入状態）。"""
    return "<!-- 例: 記入例 -->" if value is None else value


def _metadata_md(*, album_title: str | None, language: str | None, tracks) -> str:
    """30-distrokid disc の metadata.md 本文（実フォーマット準拠）。"""
    lines = [
        "# DistroKid 入力メタデータ — サンプル",
        "",
        "## アルバム情報",
        "",
        "| 項目 | 値 |",
        "|------|-----|",
        f"| アルバムタイトル | {_album_value(album_title)} |",
        f"| アーティスト名 | {_album_value(None)} |",
        f"| 言語 | {_album_value(language)} |",
        "",
        f"## トラックリスト (1-{len(tracks)})",
        "",
        "| # | タイトル | ファイル | 尺 | ISRC (任意) | 作詞 | 作曲 |",
        "|---|---------|---------|----|------------|------|------|",
        *[f"| {n} | {title} | `{fn}` | 3:18 |  |  |  |" for n, title, fn in tracks],
        "",
    ]
    return "\n".join(lines)


def _make_collection(tmp_path, *, with_thumbnail=True):
    """従来構造（02-Individual-music + 10-assets）の最小コレクションを作る。"""
    collection = tmp_path / "20260526-sg-coding-focus-collection"
    music = collection / "02-Individual-music"
    assets = collection / "10-assets"
    music.mkdir(parents=True)
    assets.mkdir(parents=True)
    (music / "01-foo.mp3").write_bytes(_MP3_BYTES)
    (music / "02-bar.mp3").write_bytes(_MP3_BYTES)
    if with_thumbnail:
        (assets / "thumbnail.png").write_bytes(b"\x89PNGfake")
    return collection


def _make_disc_source(
    collection,
    *,
    source=_DISC_SOURCE,
    tracks=_DISC1_TRACKS,
    album_title=None,
    language="Instrumental",
    with_cover=True,
):
    """`<collection>/30-distrokid/<disc>/` に mp3 + metadata.md、cover を作る。"""
    source_dir = collection / source
    source_dir.mkdir(parents=True)
    for _n, _title, filename in tracks:
        (source_dir / filename).write_bytes(_MP3_BYTES)
    (source_dir / "metadata.md").write_text(
        _metadata_md(album_title=album_title, language=language, tracks=tracks),
        encoding="utf-8",
    )
    if with_cover:
        (collection / "30-distrokid" / "cover_art_3000.jpg").write_bytes(_COVER_BYTES)
    return source_dir


# ---------------------------------------------------------------------------
# build_release_payload: disc-source 分岐（受け入れ基準）
# ---------------------------------------------------------------------------


def test_disc_source_tracks_count_matches_disc_mp3s(tmp_path):
    """Given 25 曲の disc-source
    When distrokid_source 指定で build_release_payload
    Then release.tracks 数が 25（disc 単位のアルバム）。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection)
    distrokid = Distrokid(enabled=True, profile=_profile())

    payload = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)

    assert len(payload["release"]["tracks"]) == 25


def test_disc_source_first_track_title_from_metadata(tmp_path):
    """Given metadata.md の Title Case トラック表
    When distrokid_source 指定で build_release_payload
    Then tracks[0].title が metadata.md の Title Case 版。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection)
    distrokid = Distrokid(enabled=True, profile=_profile())

    payload = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)

    assert payload["release"]["tracks"][0]["title"] == "Slip Right Through"


def test_disc_source_tracks_are_sorted_by_filename(tmp_path):
    """Given disc-source の mp3 群
    When distrokid_source 指定で build_release_payload
    Then tracks はファイル名ソート順（先頭が 01-）。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection)
    distrokid = Distrokid(enabled=True, profile=_profile())

    tracks = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)["release"]["tracks"]

    assert tracks[0]["filename"] == "01-slip-right-through.mp3"
    assert tracks[-1]["filename"] == "25-velvet-hour.mp3"


def test_disc_source_track_asset_path_points_into_source(tmp_path):
    """Given disc-source
    When build_release_payload
    Then asset_path がコレクション root 相対で disc-source 配下を指す。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection)
    distrokid = Distrokid(enabled=True, profile=_profile())

    first = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)["release"]["tracks"][0]

    assert first["asset_path"] == f"{DISTROKID_ASSETS_PREFIX}{_DISC_SOURCE}/01-slip-right-through.mp3"


def test_disc_source_cover_uses_cover_art_3000(tmp_path):
    """Given 30-distrokid/cover_art_3000.jpg
    When distrokid_source 指定で build_release_payload
    Then cover.filename が cover_art_3000.jpg。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection)
    distrokid = Distrokid(enabled=True, profile=_profile())

    cover = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)["release"]["cover"]

    assert cover["filename"] == "cover_art_3000.jpg"
    assert cover["asset_path"] == f"{DISTROKID_ASSETS_PREFIX}30-distrokid/cover_art_3000.jpg"


def test_disc_source_cover_falls_back_to_thumbnail_when_absent(tmp_path):
    """Given cover_art_3000.jpg 無し + 10-assets/thumbnail.png 有り
    When distrokid_source 指定で build_release_payload
    Then cover は既存サムネイルにフォールバックする。
    """
    collection = _make_collection(tmp_path, with_thumbnail=True)
    _make_disc_source(collection, with_cover=False)
    distrokid = Distrokid(enabled=True, profile=_profile())

    cover = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)["release"]["cover"]

    assert cover["filename"] == "thumbnail.png"


def test_disc_source_cover_does_not_fallback_to_textless_main(tmp_path):
    """#1310: cover_art_3000.jpg と thumbnail.* が無い場合、main.png は cover に使わない。"""
    collection = _make_collection(tmp_path, with_thumbnail=False)
    (collection / "10-assets" / "main.png").write_bytes(_COVER_BYTES)
    _make_disc_source(collection, with_cover=False)
    distrokid = Distrokid(enabled=True, profile=_profile())

    cover = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)["release"]["cover"]

    assert cover is None


def test_disc_source_language_uses_profile_ignoring_metadata(tmp_path):
    """Given metadata.md の 言語=Instrumental（DistroKid form 言語 option と意味が異なる値）
    When distrokid_source 指定で build_release_payload
    Then profile.language は config 由来の "ja" を維持する（metadata.md は権威ではない）。

    metadata.md の「言語」セルは人間が読む転記用テンプレで、DistroKid form の言語
    option（English 等の言語名）と意味が異なる値（例: "Instrumental" は楽曲属性）が
    書かれうるため、payload には反映しない（#888 / 拡張側の OptionNotFoundError 予防）。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection, language="Instrumental")
    distrokid = Distrokid(enabled=True, profile=_profile())

    payload = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)

    assert payload["profile"]["language"] == "ja"


def test_disc_source_language_uses_profile_when_metadata_blank(tmp_path):
    """Given metadata.md の 言語が HTML コメント枠（未記入）
    When distrokid_source 指定で build_release_payload
    Then profile.language は元の profile 値（ja）のまま（非空時と同じ挙動）。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection, language=None)
    distrokid = Distrokid(enabled=True, profile=_profile())

    payload = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)

    assert payload["profile"]["language"] == "ja"


def test_disc_source_album_title_from_metadata_when_filled(tmp_path):
    """Given metadata.md のアルバムタイトルが実値
    When distrokid_source 指定で build_release_payload
    Then release.album_title がその値。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection, album_title="Coding Focus Vol.1")
    distrokid = Distrokid(enabled=True, profile=_profile())

    payload = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)

    assert payload["release"]["album_title"] == "Coding Focus Vol.1"


def test_disc_source_album_title_falls_back_to_disc_dirname(tmp_path):
    """Given metadata.md のアルバムタイトルが未記入（HTML コメント枠）
    When distrokid_source 指定で build_release_payload
    Then disc dirname を kebab→Title 化した値（"disc1-coding-focus-vol1" → 各語頭大文字）。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection, album_title=None)
    distrokid = Distrokid(enabled=True, profile=_profile())

    payload = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)

    assert payload["release"]["album_title"] == "Disc1 Coding Focus Vol1"


def test_disc_source_track_title_falls_back_to_stem_when_unmatched(tmp_path):
    """Given metadata.md トラック表に無いファイルが disc に存在
    When distrokid_source 指定で build_release_payload
    Then 未マッチ行は filename stem をタイトルにフォールバック（行単位の救済）。
    """
    collection = _make_collection(tmp_path)
    source_dir = _make_disc_source(collection, tracks=_DISC1_TRACKS[:2])
    # metadata.md に載っていない 99-extra.mp3 を追加。
    (source_dir / "99-extra.mp3").write_bytes(_MP3_BYTES)
    distrokid = Distrokid(enabled=True, profile=_profile())

    tracks = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)["release"]["tracks"]
    extra = next(t for t in tracks if t["filename"] == "99-extra.mp3")

    assert extra["title"] == "99-extra"


# ---------------------------------------------------------------------------
# fail-loud（silent degrade 禁止）
# ---------------------------------------------------------------------------


def test_disc_source_missing_dir_raises_config_error(tmp_path):
    """Given 指定した source dir が存在しない
    When distrokid_source 指定で build_release_payload
    Then ConfigError（明示指定は 30-distrokid 構造前提・degrade しない）。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())

    with pytest.raises(ConfigError):
        build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)


def test_disc_source_missing_metadata_raises_config_error(tmp_path):
    """Given source dir はあるが metadata.md が無い
    When distrokid_source 指定で build_release_payload
    Then ConfigError（fail-loud）。
    """
    collection = _make_collection(tmp_path)
    source_dir = collection / _DISC_SOURCE
    source_dir.mkdir(parents=True)
    (source_dir / "01-slip-right-through.mp3").write_bytes(_MP3_BYTES)
    distrokid = Distrokid(enabled=True, profile=_profile())

    with pytest.raises(ConfigError):
        build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)


def test_disc_source_traversal_outside_collection_raises_config_error(tmp_path):
    """Given `..` でコレクション外へ脱出する source
    When distrokid_source 指定で build_release_payload
    Then ConfigError（トラバーサルガード）。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())

    with pytest.raises(ConfigError):
        build_release_payload(collection, distrokid, distrokid_source="../secret")


# ---------------------------------------------------------------------------
# 後方互換: distrokid_source 未指定は従来経路
# ---------------------------------------------------------------------------


def test_default_path_unchanged_when_source_omitted(tmp_path):
    """Given distrokid_source 未指定
    When build_release_payload
    Then 従来通り 02-Individual-music/ から tracks を組み立てる（後方互換）。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection)  # disc-source が存在しても未指定なら無視される
    distrokid = Distrokid(enabled=True, profile=_profile())

    payload = build_release_payload(collection, distrokid)

    assert [t["filename"] for t in payload["release"]["tracks"]] == ["01-foo.mp3", "02-bar.mp3"]
    assert payload["profile"]["language"] == "ja"


def test_explicit_none_source_equals_default(tmp_path):
    """Given distrokid_source=None を明示
    When build_release_payload
    Then 未指定時と同一の payload（既定値の同値性）。
    """
    collection = _make_collection(tmp_path)
    distrokid = Distrokid(enabled=True, profile=_profile())

    assert build_release_payload(collection, distrokid, distrokid_source=None) == (
        build_release_payload(collection, distrokid)
    )


# ---------------------------------------------------------------------------
# create_server 経由の配線（distrokid_source が末端まで伝搬する統合）
# ---------------------------------------------------------------------------


@pytest.fixture
def serve(tmp_path):
    """空きポートでサーバーを起動し base URL を返すファクトリ（distrokid_source 注入可）。"""
    started = []

    def _start(*, collection_dir, distrokid, distrokid_source=None):
        prompts_path = tmp_path / "suno-prompts.json"
        prompts_path.write_text("[]", encoding="utf-8")
        server = create_server(
            0,
            None,
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


def test_release_endpoint_serves_disc_source_payload(serve, tmp_path):
    """Given create_server に distrokid_source を渡す
    When `GET /distrokid/release.json`
    Then disc-source の payload（25 tracks / cover_art_3000 / profile.language=ja）を返す。

    distrokid_source が create_server → _serve_distrokid_release →
    build_release_payload まで伝搬することの統合検証。language は profile 値を維持する
    （metadata.md の「言語」は payload に影響しない、#888）。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid, distrokid_source=_DISC_SOURCE)

    with urllib.request.urlopen(f"{base}{DISTROKID_RELEASE_ROUTE}") as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert len(body["release"]["tracks"]) == 25
    assert body["release"]["tracks"][0]["title"] == "Slip Right Through"
    assert body["release"]["cover"]["filename"] == "cover_art_3000.jpg"
    assert body["profile"]["language"] == "ja"


def test_release_asset_serves_disc_source_mp3(serve, tmp_path):
    """Given disc-source の mp3
    When `GET /distrokid/assets/30-distrokid/disc1-.../01-slip-right-through.mp3`
    Then 200 + audio/mpeg で実バイト列を返す（asset 配信は root 相対で素通し）。
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection)
    distrokid = Distrokid(enabled=True, profile=_profile())
    base = serve(collection_dir=collection, distrokid=distrokid, distrokid_source=_DISC_SOURCE)

    url = f"{base}{DISTROKID_ASSETS_PREFIX}{_DISC_SOURCE}/01-slip-right-through.mp3"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "audio/mpeg"
        assert resp.read() == _MP3_BYTES


# ---------------------------------------------------------------------------
# spec.json 優先経路（#941）
# ---------------------------------------------------------------------------


def _make_spec(distrokid_dir, disc_slug, tracks, *, album_title="Spec Album Title"):
    """30-distrokid/spec.json を作成する（#941 テスト用）."""
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
                "tracks": [{"filename": fn, "title": title} for fn, title in tracks],
            }
        ],
    }
    write_collection_spec(distrokid_dir, spec)
    return spec


def test_spec_priority_over_metadata_md_no_metadata(tmp_path):
    """Given spec.json あり + metadata.md 無し
    When distrokid_source 指定で build_release_payload
    Then spec の album_title / track title で payload が組み上がる。
    (#941: spec が SSOT、metadata.md 不在でも raise しない)
    """
    collection = _make_collection(tmp_path)
    disc_slug = "disc1-coding-focus-vol1"
    source_dir = collection / _DISC_SOURCE
    source_dir.mkdir(parents=True)
    # mp3 を 2 つ置く
    (source_dir / "01-slip-right-through.mp3").write_bytes(_MP3_BYTES)
    (source_dir / "02-easy-release.mp3").write_bytes(_MP3_BYTES)
    # metadata.md は置かない
    # cover_art_3000.jpg
    (collection / "30-distrokid" / "cover_art_3000.jpg").write_bytes(_COVER_BYTES)

    distrokid_dir = collection / "30-distrokid"
    _make_spec(
        distrokid_dir,
        disc_slug,
        [
            ("01-slip-right-through.mp3", "Slip Right Through"),
            ("02-easy-release.mp3", "Easy Release"),
        ],
        album_title="Spec Album Title",
    )

    distrokid = Distrokid(enabled=True, profile=_profile())
    payload = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)

    assert payload["release"]["album_title"] == "Spec Album Title"
    assert payload["release"]["tracks"][0]["title"] == "Slip Right Through"
    assert payload["release"]["tracks"][1]["title"] == "Easy Release"
    assert len(payload["release"]["tracks"]) == 2


def test_spec_priority_unknown_mp3_falls_back_to_stem(tmp_path):
    """Given spec.json あり + spec に存在しない mp3 が disc に追加された
    When distrokid_source 指定で build_release_payload
    Then 未知 filename は stem をタイトルにフォールバック（既存 _disc_tracks の救済ロジック）。
    (#941)
    """
    collection = _make_collection(tmp_path)
    disc_slug = "disc1-coding-focus-vol1"
    source_dir = collection / _DISC_SOURCE
    source_dir.mkdir(parents=True)
    (source_dir / "01-slip-right-through.mp3").write_bytes(_MP3_BYTES)
    (source_dir / "99-extra-unknown.mp3").write_bytes(_MP3_BYTES)  # spec に無い
    (collection / "30-distrokid" / "cover_art_3000.jpg").write_bytes(_COVER_BYTES)

    distrokid_dir = collection / "30-distrokid"
    _make_spec(
        distrokid_dir,
        disc_slug,
        [("01-slip-right-through.mp3", "Slip Right Through")],  # 99-extra-unknown.mp3 は含めない
    )

    distrokid = Distrokid(enabled=True, profile=_profile())
    tracks = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)["release"]["tracks"]

    extra = next(t for t in tracks if t["filename"] == "99-extra-unknown.mp3")
    assert extra["title"] == "99-extra-unknown"  # stem フォールバック


def test_spec_disc_entry_missing_falls_back_to_metadata(tmp_path):
    """Given spec.json はあるが対象 disc のエントリが無い
    When distrokid_source 指定で build_release_payload
    Then metadata.md フォールバック経路に乗る（metadata.md 不在なら従来どおり ConfigError）。
    (#941)
    """
    collection = _make_collection(tmp_path)
    source_dir = collection / _DISC_SOURCE
    source_dir.mkdir(parents=True)
    (source_dir / "01-slip-right-through.mp3").write_bytes(_MP3_BYTES)
    (collection / "30-distrokid" / "cover_art_3000.jpg").write_bytes(_COVER_BYTES)
    # metadata.md を置かない → フォールバック先も不在 → ConfigError

    distrokid_dir = collection / "30-distrokid"
    # spec には別の disc しかない
    _make_spec(
        distrokid_dir,
        "disc99-other-vol99",  # 対象 disc1-coding-focus-vol1 とは別 slug
        [("01-slip-right-through.mp3", "Slip Right Through")],
    )

    distrokid = Distrokid(enabled=True, profile=_profile())

    with pytest.raises(ConfigError, match="metadata.md"):
        build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)


def test_spec_disc_entry_missing_uses_metadata_when_present(tmp_path):
    """Given spec.json に対象 disc エントリ無し + metadata.md あり
    When distrokid_source 指定で build_release_payload
    Then metadata.md の値を使う（後方互換フォールバック）。
    (#941)
    """
    collection = _make_collection(tmp_path)
    _make_disc_source(collection, album_title="MD Album Title")

    distrokid_dir = collection / "30-distrokid"
    # spec には別の disc しかない（対象エントリ無し）
    _make_spec(
        distrokid_dir,
        "disc99-other",
        [("01-slip-right-through.mp3", "Slip Right Through")],
    )

    distrokid = Distrokid(enabled=True, profile=_profile())
    payload = build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)

    # metadata.md の album_title を使う
    assert payload["release"]["album_title"] == "MD Album Title"


def test_spec_corrupted_raises_config_error(tmp_path):
    """Given 破損した spec.json（不正 JSON）
    When distrokid_source 指定で build_release_payload
    Then ConfigError を raise する（fail-loud; 黙った md フォールバックは行わない）。
    (#941)
    """
    collection = _make_collection(tmp_path)
    source_dir = collection / _DISC_SOURCE
    source_dir.mkdir(parents=True)
    (source_dir / "01-slip-right-through.mp3").write_bytes(_MP3_BYTES)
    (collection / "30-distrokid" / "cover_art_3000.jpg").write_bytes(_COVER_BYTES)

    # 破損した spec.json を書き込む
    distrokid_dir = collection / "30-distrokid"
    (distrokid_dir / "spec.json").write_text("{ broken json }", encoding="utf-8")

    distrokid = Distrokid(enabled=True, profile=_profile())

    with pytest.raises(ConfigError):
        build_release_payload(collection, distrokid, distrokid_source=_DISC_SOURCE)
