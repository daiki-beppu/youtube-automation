#!/usr/bin/env python3
"""Warn when a proposed YouTube title overlaps past local titles."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.config import channel_dir, load_config
from youtube_automation.utils.descriptions_md import (
    build_descriptions_md_parse_diagnostics,
    extract_descriptions_md_section,
)
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.preflight_checks import check_title_duplicate_warnings


def extract_section(text: str, header: str) -> str | None:
    return extract_descriptions_md_section(text, header)


def read_descriptions_title(collection_dir: Path) -> str:
    desc_path = CollectionPaths(collection_dir).descriptions_md_path
    if not desc_path.exists():
        raise FileNotFoundError(f"{desc_path} not found. Pass --title to check a title before saving descriptions.md.")
    text = desc_path.read_text(encoding="utf-8")
    title = extract_section(text, "タイトル案")
    if title is None:
        raise ValueError(f"{desc_path}: descriptions.md parse failed\n{build_descriptions_md_parse_diagnostics(text)}")
    if not title:
        raise ValueError(f"{desc_path}: missing 'タイトル案' section")
    return title.strip()


def collect_live_titles(collections_root: Path, *, exclude_dir: Path | None = None) -> list[str]:
    live_root = collections_root / "live"
    if not live_root.exists():
        return []

    exclude_resolved = exclude_dir.resolve() if exclude_dir else None
    titles: list[str] = []
    for collection in sorted(live_root.iterdir()):
        if not collection.is_dir() or collection.name.startswith("."):
            continue
        if exclude_resolved and collection.resolve() == exclude_resolved:
            continue
        desc_path = CollectionPaths(collection).descriptions_md_path
        if not desc_path.exists():
            continue
        title = extract_section(desc_path.read_text(encoding="utf-8"), "タイトル案")
        if title:
            titles.append(title.strip())
    return titles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-title-duplicate-check",
        description="Warn if a proposed title overlaps titles in collections/live.",
    )
    parser.add_argument("collection", nargs="?", help="collection dir; used for descriptions.md title and self-exclude")
    parser.add_argument("--title", help="proposed title to check before writing descriptions.md")
    parser.add_argument(
        "--collections-root",
        type=Path,
        default=None,
        help="collections root containing live/ (default: CHANNEL_DIR/collections)",
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 when warnings are found")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    collection_dir = Path(args.collection).resolve() if args.collection else None
    if args.title:
        title = args.title.strip()
    elif collection_dir:
        title = read_descriptions_title(collection_dir)
    else:
        raise SystemExit("collection or --title is required")

    try:
        config = load_config()
        title_cfg = config.content.title
        template_check_cfg = {**dict(title_cfg.template_check), "template": title_cfg.template}
    except ConfigError:
        template_check_cfg = {}

    if args.collections_root:
        collections_root = args.collections_root
    else:
        try:
            collections_root = channel_dir() / "collections"
        except ConfigError:
            collections_root = Path("collections")
    existing_titles = collect_live_titles(collections_root, exclude_dir=collection_dir)
    warnings = check_title_duplicate_warnings(title, existing_titles, template_check_cfg)

    if not warnings:
        print(f"✅ title duplicate check OK: {title}")
        return 0

    print(f"⚠️  title duplicate warning: {title}")
    for warning in warnings:
        print(f"  - {warning}")
    print("→ 過去タイトルとの差分が分かるよう、前半または後半の表現を見直してください。")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
