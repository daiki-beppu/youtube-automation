"""yt-distrokid-migrate — 旧 distrokid.json を実 DOM 検証ベースの新 schema へ変換する（#813）.

PR #803 当時のフラット profile（`artist_name` / `apple_music_credit` / `track_type` を含む
6 文字列）を、nested `songwriter` + `ai_disclosure` を持つ新 schema へ in-place 変換する。
`yt-config-migrate` の dry-run / `--apply` / backup パターンを踏襲した単一目的 CLI。

    引数なし          : dry-run（プレビューのみ、書き込みなし）
    --apply           : 実書き込み
    --backup（既定）  : distrokid.json.bak を残す（--no-backup で無効化）
    --target DIR      : 対象チャンネルディレクトリ（既定: CHANNEL_DIR / CWD 祖先探索）

変換規則:
    - songwriter "First Last"    → {"first": "First", "last": "Last"}
    - songwriter "First M Last"  → 中間語を middle に
    - songwriter が既に object   → そのまま（冪等）
    - ai_disclosure 省略         → 新 schema の default を付与
    - artist_name                   → artist
    - apple_music_credit / track_type → drop
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError

# config/channel/distrokid.json への相対パス（契約文字列の SSOT）。
_DISTROKID_RELPATH = ("config", "channel", "distrokid.json")

# ai_disclosure 省略時に付与する default（utils.config.distrokid.AiDisclosure と一致させる）。
_DEFAULT_AI_DISCLOSURE: dict[str, object] = {
    "enabled": True,
    "lyrics": True,
    "music": True,
    "recording_scope": "full",
    "partial_audio_type": None,
    "artist_persona": True,
    "apply_to_all": True,
}


def _convert_ai_disclosure(raw: object) -> dict:
    """旧 ai_disclosure（`composition` field のみ）を新 schema へ正規化する（#877）.

    - dict でなければ default を付与
    - 旧 `composition` → 新 `music` にリネーム（`music` 明示時は `music` を優先）
    - recording_scope / artist_persona / apply_to_all など新フィールドは default で補完
    - 旧 schema は `recording_scope` を持たず `partial_audio_type` のみで partial を表現して
      いたため、`recording_scope` 未指定かつ `partial_audio_type` 非 null のときは
      `recording_scope="partial"` を導出する（loader のクロスバリデーションで読める形にする）
    """
    merged: dict = dict(_DEFAULT_AI_DISCLOSURE)
    if isinstance(raw, dict):
        merged.update(raw)
        if "music" not in raw and "composition" in raw:
            merged["music"] = raw["composition"]
        if "recording_scope" not in raw and raw.get("partial_audio_type") is not None:
            merged["recording_scope"] = "partial"
    merged.pop("composition", None)
    return merged


def _resolve_target_dir(target: str | None) -> Path:
    """対象チャンネルディレクトリを解決する.

    優先順: --target → CHANNEL_DIR → CWD 祖先探索で config/channel/ を持つディレクトリ.
    """
    if target:
        path = Path(target).resolve()
        if not path.is_dir():
            raise ConfigError(f"--target で指定されたディレクトリが存在しません: {path}")
        return path

    env = os.environ.get("CHANNEL_DIR")
    if env:
        path = Path(env).resolve()
        if not path.is_dir():
            raise ConfigError(f"CHANNEL_DIR で指定されたディレクトリが存在しません: {path}")
        return path

    for parent in [Path.cwd()] + list(Path.cwd().parents):
        if (parent / "config" / "channel").is_dir():
            return parent

    raise ConfigError(
        "対象チャンネルディレクトリが特定できません。"
        "--target DIR を指定するか、CHANNEL_DIR 環境変数を設定するか、"
        "config/channel/ を持つディレクトリ配下で実行してください"
    )


def _distrokid_path(target: Path) -> Path:
    return target.joinpath(*_DISTROKID_RELPATH)


def _split_songwriter(value: object) -> dict | None:
    """songwriter（旧: "First Last" 文字列 / 新: object）を新 schema の dict へ正規化する."""
    if value is None:
        return None
    if isinstance(value, dict):
        # 既に新 schema。冪等のためそのまま（破壊しない）。
        return dict(value)
    if not isinstance(value, str):
        raise ConfigError(f"songwriter は文字列または object でなければなりません（got {type(value).__name__}）")

    parts = value.split()
    if not parts:
        return None
    if len(parts) == 1:
        return {"first": parts[0], "last": ""}
    result = {"first": parts[0], "last": parts[-1]}
    middle = " ".join(parts[1:-1])
    if middle:
        result["middle"] = middle
    return result


def _convert_profile(old_profile: dict) -> dict:
    """旧フラット profile を新 schema profile へ変換する（legacy フィールドは drop）."""
    new_profile: dict = {}
    artist = old_profile.get("artist", old_profile.get("artist_name"))
    if artist is not None:
        new_profile["artist"] = artist
    if old_profile.get("language") is not None:
        new_profile["language"] = old_profile["language"]
    if old_profile.get("main_genre") is not None:
        new_profile["main_genre"] = old_profile["main_genre"]
    if old_profile.get("sub_genre"):
        new_profile["sub_genre"] = old_profile["sub_genre"]

    songwriter = _split_songwriter(old_profile.get("songwriter"))
    if songwriter is not None:
        new_profile["songwriter"] = songwriter

    new_profile["ai_disclosure"] = _convert_ai_disclosure(old_profile.get("ai_disclosure"))
    return new_profile


def _convert(data: dict) -> dict:
    """distrokid.json 全体を新 schema へ変換する（enabled は保持）."""
    if not isinstance(data, dict):
        raise ConfigError("distrokid.json のトップレベルは object でなければなりません")
    section = data.get("distrokid")
    if not isinstance(section, dict):
        raise ConfigError("distrokid.json に object の distrokid セクションが必要です")
    profile_raw = section.get("profile") or {}
    if not isinstance(profile_raw, dict):
        raise ConfigError("distrokid.profile は object でなければなりません")
    return {
        "distrokid": {
            "enabled": bool(section.get("enabled", False)),
            "profile": _convert_profile(profile_raw),
        }
    }


def _load_distrokid(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"distrokid.json の JSON パース失敗: {path}: {e}")
    return data


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yt-distrokid-migrate",
        description="旧 distrokid.json を実 DOM 検証ベースの新 schema へ変換する（#813）",
    )
    parser.add_argument("--target", default=None, help="対象チャンネルディレクトリ (default: 自動解決)")
    parser.add_argument("--apply", action="store_true", help="実書き込み (default: dry-run)")
    parser.add_argument(
        "--backup",
        dest="backup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="distrokid.json.bak を残す (default: 有効、--apply 時のみ)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        target = _resolve_target_dir(args.target)
        path = _distrokid_path(target)
        if not path.is_file():
            raise ConfigError(f"distrokid.json が見つかりません: {path}")

        converted = _convert(_load_distrokid(path))
        preview = json.dumps(converted, indent=2, ensure_ascii=False)

        if not args.apply:
            print(f"[dry-run] {path} を新 schema へ変換します（--apply で書き込み）:")
            print(preview)
            return 0

        if args.backup:
            backup_path = path.with_name(path.name + ".bak")
            shutil.copy2(path, backup_path)
            print(f"  backup: {backup_path.name}")

        path.write_text(preview + "\n", encoding="utf-8")
        print(f"  migrated: {path}")
        return 0
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
