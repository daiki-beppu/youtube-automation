#!/usr/bin/env python3
"""ボツ画像を ``assets/stock/<theme>/`` に退避する CLI。

skill 側の ``rm -f ...`` の置き換えとして呼び出される想定。

メタデータは ``--meta-json`` でファイル / ``-`` (stdin) から JSON を読み込むか、
個別フラグ (``--theme`` / ``--source-collection`` / ``--source-role``) で指定する。

skill-config の ``image_generation.stock.enabled`` が ``False`` のときは
退避せず ``unlink`` のみ実施する (従来挙動への opt-out)。

Usage:
    yt-stock-archive 10-assets/main-v*.jpg \\
        --theme tavern --source-collection "$(pwd)" \\
        --source-role thumbnail_candidate

    cat meta.json | yt-stock-archive 10-assets/main-v1.jpg --meta-json -
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.stock import SOURCE_ROLES, archive_to_stock, load_stock_config


def _load_meta_from_arg(meta_arg: str | None) -> dict[str, Any]:
    if not meta_arg:
        return {}
    if meta_arg == "-":
        text = sys.stdin.read()
    else:
        text = Path(meta_arg).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"--meta-json の JSON パースに失敗: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("--meta-json は dict (JSON object) である必要があります")
    return data


def _stock_enabled() -> bool:
    stock = load_stock_config(load_skill_config("thumbnail"))
    return bool(stock.get("enabled", True))


def _excluded(path: Path, patterns: list[str]) -> bool:
    if not patterns:
        return False
    name = path.name
    abs_str = str(path.resolve())
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(abs_str, pattern):
            return True
    return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ボツ画像を assets/stock/<theme>/ に退避する")
    parser.add_argument("images", nargs="+", help="退避対象の画像パス (複数指定可)")
    parser.add_argument("--theme", help="テーマ slug (kebab-case 推奨)")
    parser.add_argument("--source-collection", help="元コレクションのパス (meta に記録)")
    parser.add_argument(
        "--source-role",
        choices=SOURCE_ROLES,
        help="退避元の役割",
    )
    parser.add_argument(
        "--meta-json",
        help="メタデータ JSON ファイルパス、または '-' で stdin から読み込み",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="退避対象から除外するファイル名 / 絶対パスのパターン (fnmatch、複数指定可)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    meta_base = _load_meta_from_arg(args.meta_json)
    if args.theme:
        meta_base["theme"] = args.theme
    if args.source_collection:
        meta_base["source_collection"] = args.source_collection
    if args.source_role:
        meta_base["source_role"] = args.source_role

    enabled = _stock_enabled()
    ch_dir = channel_dir()

    archived: list[Path] = []
    skipped: list[Path] = []
    unlinked: list[Path] = []

    for raw in args.images:
        path = Path(raw)
        if not path.exists():
            print(f"  [SKIP]   not found: {path}", file=sys.stderr)
            skipped.append(path)
            continue
        if _excluded(path, args.exclude):
            print(f"  [SKIP]   excluded:  {path}")
            skipped.append(path)
            continue

        try:
            if enabled:
                dest = archive_to_stock(path, dict(meta_base), channel_dir=ch_dir)
                if dest is not None:
                    archived.append(dest)
                    print(f"  [STOCK]  archived → {dest}")
            else:
                archive_to_stock(path, dict(meta_base), channel_dir=ch_dir, enabled=False)
                unlinked.append(path)
                print(f"  [SKIP]   unlinked (stock disabled): {path}")
        except ValidationError as exc:
            print(f"  [ERROR]  {path}: {exc}", file=sys.stderr)
            return 2

    print()
    print(f"Summary: archived={len(archived)} unlinked={len(unlinked)} skipped={len(skipped)} (enabled={enabled})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
