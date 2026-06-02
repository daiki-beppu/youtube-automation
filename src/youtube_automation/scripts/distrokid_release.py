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

# 外部 HTTP 契約: distrokid-helper 拡張が fetch するサブパス。
DISTROKID_RELEASE_ROUTE = "/distrokid/release.json"
DISTROKID_ASSETS_PREFIX = "/distrokid/assets/"

# workflow-state.json 内のリリース予定日のキー。
_PLANNING_KEY = "planning"
_PUBLISH_TARGET_KEY = "publish_target_at"


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


def build_release_payload(collection_dir: Path, distrokid: Distrokid) -> dict:
    """profile（静的）と collection 動的データをマージしたリリースペイロードを返す."""
    paths = CollectionPaths(collection_dir)

    tracks = [
        {
            "title": track.stem,
            "filename": track.name,
            "asset_path": _asset_path(paths.root, track),
        }
        for track in paths.individual_music_files()
    ]

    thumbnail = paths.find_thumbnail()
    cover = (
        {"filename": thumbnail.name, "asset_path": _asset_path(paths.root, thumbnail)}
        if thumbnail is not None
        else None
    )

    return {
        "profile": asdict(distrokid.profile),
        "release": {
            "album_title": paths.collection_name,
            "tracks": tracks,
            "cover": cover,
            "release_date": _read_release_date(paths),
        },
    }


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
