"""DistroKid spec.json の読み書き共有モジュール（#941）.

commands 層（distrokid_prepare / collection_serve）と domain 層（release）の
両方から import される SSOT 読み取り・書き込みモジュール。

依存制約:
- このモジュールは scripts 層を import してはならない。
  domains.distrokid.preparation → domains.distrokid.release（kebab_to_title）の既存依存と
  循環するためである（#941）。

spec.json スキーマ（build_draft_spec が生成する形式）:
{
  "version": 1,
  "artist": "...",
  "language": "...",
  "genre_primary": "...",
  "genre_secondary": null,
  "label": null,
  "discs": [
    {
      "slug": "disc1-coding-focus-vol1",
      "album_title": "Coding Focus Vol.1",
      "tracks": [{"filename": "01-x.mp3", "title": "X"}]
    }
  ]
}
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError

# spec.json のファイル名（SSOT として 30-distrokid/ 直下に置く）（#941）。
SPEC_FILENAME = "spec.json"


def read_collection_spec(distrokid_dir: Path) -> dict | None:
    """<distrokid_dir>/spec.json を読み込んで dict を返す（#941）.

    spec.json は build_draft_spec が生成する機械生成物であるため、
    ファイルが存在しない場合は None を返す（後方互換フォールバック用）が、
    存在するのに破損している場合は ConfigError を raise する（fail-loud）。
    破損 spec を黙って metadata.md にフォールバックすると古いデータを配信しうる
    リスクがあるため、バグとして即停止する設計としている（#941）。

    Args:
        distrokid_dir: 30-distrokid ディレクトリのパス

    Returns:
        spec dict、またはファイル不在の場合は None

    Raises:
        ConfigError: spec.json が存在するが不正 JSON / トップレベル非 dict の場合
    """
    spec_path = distrokid_dir / SPEC_FILENAME
    if not spec_path.is_file():
        return None

    try:
        raw = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"spec.json を読み取れませんでした: {spec_path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"spec.json が不正な JSON です: {spec_path}\n"
            "spec は機械生成物であるため破損はバグです。手動で修復してください。"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigError(
            f"spec.json のトップレベルが object ではありません: {spec_path}\n"
            "spec は機械生成物であるため破損はバグです。手動で修復してください。"
        )

    return data


def find_disc_entry(spec: dict, slug: str) -> dict | None:
    """spec["discs"] から slug が一致するエントリを返す（#941）.

    discs キーが無い・非 list の場合は None を返す（防御的）。
    エントリが見つからない場合も None を返す。

    Args:
        spec: read_collection_spec の戻り値
        slug: disc ディレクトリ名（例: "disc1-coding-focus-vol1"）

    Returns:
        一致する disc エントリ dict、またはマッチなしの場合は None
    """
    discs = spec.get("discs")
    if not isinstance(discs, list):
        return None
    for entry in discs:
        if isinstance(entry, dict) and entry.get("slug") == slug:
            return entry
    return None


def title_map_from_entry(entry: dict) -> dict[str, str]:
    """disc エントリの tracks から {filename: title} マッピングを返す（#941）.

    filename または title が欠ける行はスキップする（防御的）。
    spec.json が SSOT になった後も、mp3 が spec に存在しない場合は
    _disc_tracks の stem 救済ロジックに引き継がれる。

    Args:
        entry: find_disc_entry の戻り値（disc エントリ dict）

    Returns:
        {filename: title} の dict（欠損行は除外）
    """
    tracks = entry.get("tracks")
    if not isinstance(tracks, list):
        return {}
    result: dict[str, str] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        filename = track.get("filename")
        title = track.get("title")
        if filename and title:
            result[str(filename)] = str(title)
    return result


def write_collection_spec(distrokid_dir: Path, spec: dict) -> None:
    """spec dict を <distrokid_dir>/spec.json へ atomic 書き込みする（#941）.

    tempfile.mkstemp → os.replace パターン（write_distrokid_release と同方針）で
    書き込み中断による中途半端なファイルを残さない。
    canonical パス（30-distrokid/spec.json）への自己上書きも安全に動作する。

    Args:
        distrokid_dir: 30-distrokid ディレクトリのパス（存在しない場合は作成する）
        spec: 書き込む spec dict
    """
    distrokid_dir.mkdir(parents=True, exist_ok=True)
    target = distrokid_dir / SPEC_FILENAME
    fd, tmp_name = tempfile.mkstemp(
        dir=str(distrokid_dir),
        prefix=".spec-",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, target)
    except BaseException:
        # 書き込み失敗時に temp を残さない（atomic write の後始末）。
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
