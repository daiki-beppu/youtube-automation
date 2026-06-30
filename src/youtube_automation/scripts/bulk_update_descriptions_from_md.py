#!/usr/bin/env python3
"""Push descriptions.md content to YouTube via videos().update(part='snippet').

For each collection discovered under ``collections/live/`` that has both
``20-documentation/descriptions.md`` and ``20-documentation/upload_tracking.json``,
read its 'Complete Collection 概要欄' and 'タイトル案' sections from
descriptions.md, and update the corresponding YouTube video's snippet
(title, description, tags, categoryId).

The required video_id is read from
``collections/live/<col>/20-documentation/upload_tracking.json``.

Usage:
    yt-bulk-update-desc --dry-run
    yt-bulk-update-desc --only midnight-flow-state
    yt-bulk-update-desc
"""

from __future__ import annotations

import argparse
import json
import time

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.descriptions_md import (
    build_descriptions_md_parse_diagnostics,
    extract_descriptions_md_section,
)
from youtube_automation.utils.youtube_service import get_youtube
from youtube_automation.utils.youtube_tag import parse_youtube_tags


def discover_collections() -> list[str]:
    """``collections/live/*`` から description 更新可能な collection 名を返す.

    `20-documentation/descriptions.md` と `20-documentation/upload_tracking.json`
    が **両方** 存在する collection のみを対象とする（silent skip）.
    戻り値は決定論的な `sorted()` 順.
    """
    live_dir = channel_dir() / "collections" / "live"
    if not live_dir.exists():
        return []

    results: list[str] = []
    for col_dir in sorted(live_dir.iterdir()):
        doc_dir = col_dir / "20-documentation"
        if not (doc_dir / "descriptions.md").exists():
            continue
        if not (doc_dir / "upload_tracking.json").exists():
            continue
        results.append(col_dir.name)
    return results


def extract_md_section(md_text: str, header: str) -> str | None:
    return extract_descriptions_md_section(md_text, header)


def utf16_units(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def load_collection(col: str) -> dict:
    col_dir = channel_dir() / "collections" / "live" / col
    desc_md = (col_dir / "20-documentation" / "descriptions.md").read_text(encoding="utf-8")
    upload_tracking = json.loads((col_dir / "20-documentation" / "upload_tracking.json").read_text(encoding="utf-8"))
    cc = upload_tracking.get("complete_collection") or {}
    video_id = cc.get("video_id")
    if not video_id:
        raise RuntimeError(f"no complete_collection.video_id in {col}")

    description = extract_md_section(desc_md, "Complete Collection 概要欄")
    title = extract_md_section(desc_md, "タイトル案")
    tags_raw = extract_md_section(desc_md, "タグ（YouTube タグ欄）")
    tags = []
    if tags_raw:
        tags = parse_youtube_tags(tags_raw)

    if not (description and title):
        raise RuntimeError(f"descriptions.md parse failed in {col}\n{build_descriptions_md_parse_diagnostics(desc_md)}")

    return {
        "collection": col,
        "video_id": video_id,
        "title": title,
        "description": description,
        "tags": tags,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", help="comma-separated substring filter for collection names")
    args = parser.parse_args()

    targets = discover_collections()
    if args.only:
        substrs = [s.strip() for s in args.only.split(",") if s.strip()]
        targets = [c for c in targets if any(s in c for s in substrs)]

    payloads = []
    for col in targets:
        try:
            payloads.append(load_collection(col))
        except Exception as e:
            print(f"❌ {col}: {e}")

    if not payloads:
        print("nothing to do")
        return

    yt = get_youtube()
    ids = ",".join(p["video_id"] for p in payloads)
    current = yt.videos().list(id=ids, part="snippet").execute()
    by_id = {item["id"]: item for item in current.get("items", [])}

    for p in payloads:
        item = by_id.get(p["video_id"])
        if not item:
            print(f"❌ {p['video_id']} ({p['collection']}): not found on YouTube")
            continue
        old_snippet = item["snippet"]
        old_title = old_snippet.get("title", "")
        old_desc = old_snippet.get("description", "")

        new_title = p["title"]
        new_desc = p["description"]
        new_tags = p["tags"] or old_snippet.get("tags", [])

        title_units = utf16_units(new_title)
        if title_units > 100:
            print(
                f"⚠️  {p['video_id']} ({p['collection']}): "
                f"new title is {title_units} UTF-16 units (>100). "
                f"Keeping old title; updating description only."
            )
            new_title = old_title

        print(f"\n{'─' * 60}")
        print(f"🎬 {p['video_id']}  {p['collection']}")
        print("   title (old → new):")
        print(f"     {old_title}")
        print(f"     {new_title}  [{title_units} units]")
        print("   description first lines (old → new):")
        for line in old_desc.split("\n")[:6]:
            print(f"     - {line}")
        print("       …")
        for line in new_desc.split("\n")[:6]:
            print(f"     + {line}")

        if args.dry_run:
            continue

        body = {
            "id": p["video_id"],
            "snippet": {
                "title": new_title,
                "description": new_desc,
                "tags": new_tags,
                "categoryId": old_snippet.get("categoryId", "10"),
                "defaultLanguage": old_snippet.get("defaultLanguage", "en"),
            },
        }
        try:
            yt.videos().update(part="snippet", body=body).execute()
            print("   ✅ updated")
        except Exception as e:
            print(f"   ❌ update failed: {e}")
        time.sleep(0.4)

    if args.dry_run:
        print(f"\n🔍 dry-run; {len(payloads)} videos would be updated")
    else:
        print("\n✅ done")


if __name__ == "__main__":
    main()
