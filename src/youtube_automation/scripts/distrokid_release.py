"""DistroKid リリースペイロード組み立てと assets パス解決（#698）.

`yt-collection-serve` の `/distrokid/release.json` / `/distrokid/assets/<path>`
エンドポイントが参照する純データロジック。`config.distrokid.profile`（静的）と
`collections/planning/<theme>/` の動的データ（アルバム名 / 曲ファイル / ジャケット /
リリース日）をマージする。HTTP / CORS は collection_serve.py の責務。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from youtube_automation.configuration.distrokid import Distrokid
from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.distrokid_metadata import (
    parse_album_metadata,
    parse_track_table,
)
from youtube_automation.utils.distrokid_spec import (
    find_disc_entry,
    read_collection_spec,
    title_map_from_entry,
)

# 外部 HTTP 契約: distrokid-helper 拡張が fetch するサブパス（単一 mode）。
DISTROKID_RELEASE_ROUTE = "/distrokid/release.json"
DISTROKID_ASSETS_PREFIX = "/distrokid/assets/"

# dir mode で使う collection-scoped リリース / アセットのルートサフィックス（#934）。
# `/collections/<id>/distrokid/<disc>/release.json`
#   → COLLECTIONS_ROUTE + "/<id>" + DISTROKID_COLLECTION_RELEASE_SUFFIX.format(disc=disc)
# `/collections/<id>/distrokid/assets/<rel>`
#   → COLLECTIONS_ROUTE + "/<id>" + DISTROKID_COLLECTION_ASSETS_PREFIX
DISTROKID_COLLECTION_RELEASE_SUFFIX = "/distrokid/{disc}/release.json"
DISTROKID_COLLECTION_ASSETS_PREFIX = "/distrokid/assets/"

# workflow-state.json 内のリリース予定日のキー。
_PLANNING_KEY = "planning"
_PUBLISH_TARGET_KEY = "publish_target_at"

# 30-distrokid disc-source の固定ファイル名。
_METADATA_FILENAME = "metadata.md"
_COVER_ART_FILENAME = "cover_art_3000.jpg"


def _asset_path(root: Path, target: Path, *, assets_prefix: str = DISTROKID_ASSETS_PREFIX) -> str:
    """コレクションルートからの相対パスを `<assets_prefix><rel>` 形式に変換する（#934）.

    dir mode では `assets_prefix` を collection-scoped パス
    (`/collections/<id>/distrokid/assets/`) に差し替えることで後方互換を維持する。
    """
    rel = target.relative_to(root).as_posix()
    return f"{assets_prefix}{rel}"


def _normalize_release_date(raw: object) -> str | None:
    """ISO 8601 文字列を `YYYY-MM-DD` へ正規化する（#932）.

    注入先の `#release-date-dp` は `<input type="date">` のため `YYYY-MM-DD` のみ受け付ける。
    `publish_target_at` はリポジトリ慣行として ISO datetime（例: `"2026-03-22T08:00:00+09:00"`）
    で記録される場合があるため、datetime.fromisoformat で parse して date 部だけを取り出す。
    date のみの文字列（`"2026-03-22"`）も同じ 1 本で処理できる（datetime が付いていない場合
    は date として parse し isoformat をそのまま返す）。
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ConfigError(f"planning.publish_target_at を ISO 8601 形式で指定してください: {raw!r}")
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError as exc:
        raise ConfigError(f"planning.publish_target_at を ISO 8601 形式で指定してください: {raw!r}") from exc


def _read_release_date(paths: CollectionPaths) -> str | None:
    """workflow-state.json の `planning.publish_target_at` を `YYYY-MM-DD` で読む（無ければ None）.

    serve payload に載せる値は `<input type="date">` が受け付ける `YYYY-MM-DD` に正規化する（#932）。
    """
    state_path = paths.workflow_state_path
    if not state_path.is_file():
        return None
    data = json.loads(state_path.read_text(encoding="utf-8"))
    planning = data.get(_PLANNING_KEY) or {}
    raw = planning.get(_PUBLISH_TARGET_KEY)
    return _normalize_release_date(raw)


def _cover_entry(root: Path, cover: Path | None, *, assets_prefix: str = DISTROKID_ASSETS_PREFIX) -> dict | None:
    """ジャケット画像を payload の cover レコードへ変換する（無ければ None）（#934）."""
    if cover is None:
        return None
    return {"filename": cover.name, "asset_path": _asset_path(root, cover, assets_prefix=assets_prefix)}


def build_release_payload(
    collection_dir: Path,
    distrokid: Distrokid,
    *,
    distrokid_source: str | None = None,
    assets_prefix: str = DISTROKID_ASSETS_PREFIX,
) -> dict:
    """profile（静的）と collection 動的データをマージしたリリースペイロードを返す（#934）.

    `distrokid_source` 指定時は `<collection>/<source>/`（30-distrokid の disc 単位）を
    source として組み立てる。未指定時は従来の `02-Individual-music/` 経路（後方互換）。

    `assets_prefix` は `_asset_path` に渡す prefix。dir mode では collection-scoped パス
    （`/collections/<id>/distrokid/assets/`）を指定する。既定は後方互換の `/distrokid/assets/`。
    """
    paths = CollectionPaths(collection_dir)
    profile = asdict(distrokid.profile)
    if distrokid_source is None:
        return {"profile": profile, "release": _default_release(paths, assets_prefix=assets_prefix)}
    return _disc_source_payload(paths, distrokid_source, profile, assets_prefix=assets_prefix)


def _default_release(paths: CollectionPaths, *, assets_prefix: str = DISTROKID_ASSETS_PREFIX) -> dict:
    """従来経路: `02-Individual-music/` を 1 アルバムとして組み立てる（#934 assets_prefix 追加）."""
    tracks = [
        {
            "title": track.stem,
            "filename": track.name,
            "asset_path": _asset_path(paths.root, track, assets_prefix=assets_prefix),
        }
        for track in paths.individual_music_files()
    ]
    return {
        "album_title": paths.collection_name,
        "tracks": tracks,
        "cover": _cover_entry(paths.root, paths.find_thumbnail(), assets_prefix=assets_prefix),
        "release_date": _read_release_date(paths),
    }


def _disc_source_payload(
    paths: CollectionPaths,
    distrokid_source: str,
    profile: dict,
    assets_prefix: str = DISTROKID_ASSETS_PREFIX,
) -> dict:
    """30-distrokid disc-source 経路: spec.json 優先 / metadata.md フォールバックで payload を組み立てる（#941）.

    読み取り優先順位:
    1. <collection>/30-distrokid/spec.json が存在し、対象 disc のエントリがある場合
       → spec.json を SSOT として album_title / title_by_filename を決定する。
       metadata.md は読まない（不在でも raise しない）。
    2. spec.json が不在 or 対象 disc のエントリが無い場合
       → 従来の metadata.md 必須経路（不在は ConfigError、fail-loud）。
    3. spec.json が存在するが破損している場合
       → read_collection_spec が ConfigError を raise し、そのまま伝播（fail-loud）。
       黙って metadata.md にフォールバックすると古いデータを配信しうるため（#941）。

    profile.language は `config/channel/distrokid.json` を権威に使う。
    metadata.md の「言語」セルは人間向け転記用テンプレで、DistroKid form 言語 option
    と意味が異なる値（例: "Instrumental" のような楽曲属性表記）が入りうるため、
    payload には反映しない（#888）。
    """
    source_dir = _resolve_source_dir(paths.root, distrokid_source)

    # spec.json 優先経路: <collection>/30-distrokid/spec.json を読む（#941）。
    # read_collection_spec は破損 spec で ConfigError を raise するので try で包まない。
    distrokid_dir = source_dir.parent
    spec = read_collection_spec(distrokid_dir)
    entry = find_disc_entry(spec, source_dir.name) if spec is not None else None

    if entry is not None:
        # spec に disc エントリあり → spec を SSOT として組み立てる。metadata.md は読まない。
        album_title = entry.get("album_title") or kebab_to_title(source_dir.name)
        title_by_filename = title_map_from_entry(entry)
    else:
        # spec 不在 or disc エントリ無し → 従来の metadata.md 必須経路（後方互換）。
        metadata_path = source_dir / _METADATA_FILENAME
        if not metadata_path.is_file():
            raise ConfigError(f"{_METADATA_FILENAME} not found under {distrokid_source}")
        album_meta = parse_album_metadata(metadata_path)
        album_title = album_meta["album_title"] or kebab_to_title(source_dir.name)
        title_by_filename = {row["filename"]: row["title"] for row in parse_track_table(metadata_path)}

    return {
        "profile": profile,
        "release": {
            "album_title": album_title,
            "tracks": _disc_tracks(paths.root, source_dir, title_by_filename, assets_prefix=assets_prefix),
            "cover": _disc_cover(paths, source_dir, assets_prefix=assets_prefix),
            "release_date": _read_release_date(paths),
        },
    }


def _resolve_source_dir(root: Path, distrokid_source: str) -> Path:
    """`<root>/<source>/` を解決する。トラバーサル・不在は ConfigError（fail-loud）."""
    candidate = (root / distrokid_source).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ConfigError(f"distrokid_source escapes collection: {distrokid_source}") from exc
    if not candidate.is_dir():
        raise ConfigError(f"distrokid_source dir not found: {distrokid_source}")
    return candidate


def _disc_tracks(
    root: Path,
    source_dir: Path,
    title_by_filename: dict[str, str],
    *,
    assets_prefix: str = DISTROKID_ASSETS_PREFIX,
) -> list[dict]:
    """disc-source の mp3 をソート順で組み立てる（タイトルは metadata.md → stem 救済）（#934 assets_prefix 追加）."""
    return [
        {
            "title": title_by_filename.get(track.name, track.stem),
            "filename": track.name,
            "asset_path": _asset_path(root, track, assets_prefix=assets_prefix),
        }
        for track in sorted(source_dir.glob("*.mp3"))
    ]


def _disc_cover(
    paths: CollectionPaths,
    source_dir: Path,
    *,
    assets_prefix: str = DISTROKID_ASSETS_PREFIX,
) -> dict | None:
    """`30-distrokid/cover_art_3000.jpg` 優先、無ければ既存サムネイルへフォールバック（#934 assets_prefix 追加）."""
    cover_art = source_dir.parent / _COVER_ART_FILENAME
    cover = cover_art if cover_art.is_file() else paths.find_thumbnail()
    return _cover_entry(paths.root, cover, assets_prefix=assets_prefix)


def kebab_to_title(dirname: str) -> str:
    """disc dirname を kebab→Title 化する（"disc1-coding-focus-vol1" → "Disc1 Coding Focus Vol1"）."""
    return " ".join(word.capitalize() for word in dirname.split("-"))


def resolve_asset_path(collection_dir: Path, relpath: str) -> Path | None:
    """assets 相対パスをコレクション配下の実体パスへ解決する.

    トラバーサル（`..` でコレクション外へ脱出）・絶対パス・不正 path・不在ファイルは None。
    """
    try:
        root = Path(collection_dir).resolve()
        candidate = (root / relpath).resolve()
        candidate.relative_to(root)
        if not candidate.is_file():
            return None
    except (OSError, ValueError):
        return None
    return candidate
