"""DistroKid リリースペイロード組み立てと assets パス解決（#698）.

`yt-collection-serve` の `/distrokid/release.json` / `/distrokid/assets/<path>`
エンドポイントが参照する純データロジック。`config.distrokid.profile`（静的）と
`collections/planning/<theme>/` の動的データ（アルバム名 / 曲ファイル / ジャケット /
リリース日）をマージする。HTTP / CORS は collection_serve.py の責務。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.config.distrokid import Distrokid
from youtube_automation.utils.distrokid_metadata import (
    parse_album_metadata,
    parse_track_table,
)
from youtube_automation.utils.exceptions import ConfigError

# 外部 HTTP 契約: distrokid-helper 拡張が fetch するサブパス。
DISTROKID_RELEASE_ROUTE = "/distrokid/release.json"
DISTROKID_ASSETS_PREFIX = "/distrokid/assets/"

# workflow-state.json 内のリリース予定日のキー。
_PLANNING_KEY = "planning"
_PUBLISH_TARGET_KEY = "publish_target_at"

# 30-distrokid disc-source の固定ファイル名。
_METADATA_FILENAME = "metadata.md"
_COVER_ART_FILENAME = "cover_art_3000.jpg"


def _asset_path(root: Path, target: Path) -> str:
    """コレクションルートからの相対パスを `/distrokid/assets/<rel>` 形式に変換する."""
    rel = target.relative_to(root).as_posix()
    return f"{DISTROKID_ASSETS_PREFIX}{rel}"


def _read_release_date(paths: CollectionPaths) -> str | None:
    """workflow-state.json の `planning.publish_target_at` を読む（無ければ None）."""
    state_path = paths.workflow_state_path
    if not state_path.is_file():
        return None
    data = json.loads(state_path.read_text(encoding="utf-8"))
    planning = data.get(_PLANNING_KEY) or {}
    return planning.get(_PUBLISH_TARGET_KEY)


def _cover_entry(root: Path, cover: Path | None) -> dict | None:
    """ジャケット画像を payload の cover レコードへ変換する（無ければ None）."""
    if cover is None:
        return None
    return {"filename": cover.name, "asset_path": _asset_path(root, cover)}


def build_release_payload(
    collection_dir: Path,
    distrokid: Distrokid,
    *,
    distrokid_source: str | None = None,
) -> dict:
    """profile（静的）と collection 動的データをマージしたリリースペイロードを返す.

    `distrokid_source` 指定時は `<collection>/<source>/`（30-distrokid の disc 単位）を
    source として組み立てる。未指定時は従来の `02-Individual-music/` 経路（後方互換）。
    """
    paths = CollectionPaths(collection_dir)
    profile = asdict(distrokid.profile)
    if distrokid_source is None:
        return {"profile": profile, "release": _default_release(paths)}
    return _disc_source_payload(paths, distrokid_source, profile)


def _default_release(paths: CollectionPaths) -> dict:
    """従来経路: `02-Individual-music/` を 1 アルバムとして組み立てる."""
    tracks = [
        {
            "title": track.stem,
            "filename": track.name,
            "asset_path": _asset_path(paths.root, track),
        }
        for track in paths.individual_music_files()
    ]
    return {
        "album_title": paths.collection_name,
        "tracks": tracks,
        "cover": _cover_entry(paths.root, paths.find_thumbnail()),
        "release_date": _read_release_date(paths),
    }


def _disc_source_payload(paths: CollectionPaths, distrokid_source: str, profile: dict) -> dict:
    """30-distrokid disc-source 経路: metadata.md 主導で payload を組み立てる.

    profile.language は `config/channel/distrokid.json` を権威に使う。
    metadata.md の「言語」セルは人間向け転記用テンプレで、DistroKid form 言語 option
    と意味が異なる値（例: "Instrumental" のような楽曲属性表記）が入りうるため、
    payload には反映しない（#888）。
    """
    source_dir = _resolve_source_dir(paths.root, distrokid_source)
    metadata_path = source_dir / _METADATA_FILENAME
    if not metadata_path.is_file():
        raise ConfigError(f"{_METADATA_FILENAME} not found under {distrokid_source}")

    album_meta = parse_album_metadata(metadata_path)
    title_by_filename = {row["filename"]: row["title"] for row in parse_track_table(metadata_path)}

    return {
        "profile": profile,
        "release": {
            "album_title": album_meta["album_title"] or _kebab_to_title(source_dir.name),
            "tracks": _disc_tracks(paths.root, source_dir, title_by_filename),
            "cover": _disc_cover(paths, source_dir),
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


def _disc_tracks(root: Path, source_dir: Path, title_by_filename: dict[str, str]) -> list[dict]:
    """disc-source の mp3 をソート順で組み立てる（タイトルは metadata.md → stem 救済）."""
    return [
        {
            "title": title_by_filename.get(track.name, track.stem),
            "filename": track.name,
            "asset_path": _asset_path(root, track),
        }
        for track in sorted(source_dir.glob("*.mp3"))
    ]


def _disc_cover(paths: CollectionPaths, source_dir: Path) -> dict | None:
    """`30-distrokid/cover_art_3000.jpg` 優先、無ければ既存サムネイルへフォールバック."""
    cover_art = source_dir.parent / _COVER_ART_FILENAME
    cover = cover_art if cover_art.is_file() else paths.find_thumbnail()
    return _cover_entry(paths.root, cover)


def _kebab_to_title(dirname: str) -> str:
    """disc dirname を kebab→Title 化する（"disc1-coding-focus-vol1" → "Disc1 Coding Focus Vol1"）."""
    return " ".join(word.capitalize() for word in dirname.split("-"))


def resolve_asset_path(collection_dir: Path, relpath: str) -> Path | None:
    """assets 相対パスをコレクション配下の実体パスへ解決する.

    トラバーサル（`..` でコレクション外へ脱出）・絶対パス・不在ファイルは None。
    """
    root = Path(collection_dir).resolve()
    candidate = (root / relpath).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate
