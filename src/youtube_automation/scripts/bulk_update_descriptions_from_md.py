#!/usr/bin/env python3
"""Push descriptions.md content to YouTube via videos().update(part='snippet').

For each collection in TARGETS, read its 'Complete Collection 概要欄' and
'タイトル案' sections from descriptions.md, and update the corresponding
YouTube video's snippet (title, description, tags, categoryId).

The required video_id is read from
collections/live/<col>/20-documentation/upload_tracking.json.

Usage:
    python3 automation/bulk_update_descriptions_from_md.py --dry-run
    python3 automation/bulk_update_descriptions_from_md.py
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from youtube_automation.utils.youtube_service import get_youtube  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
COLLECTIONS_DIR = ROOT / "collections" / "live"

# Collections whose snippet should be refreshed from descriptions.md.
TARGETS = [
    "20260328-rjn-last-platform-collection",
    "20260330-rjn-rainy-studio-collection",
    "20260331-rjn-dorm-window-collection",
    "20260331-rjn-library-after-hours-collection",
    "20260401-rjn-rain-nest-collection",
    "20260404-rjn-empty-gallery-collection",
    "20260404-rjn-parking-garage-collection",
]


def extract_md_section(md_text: str, header: str) -> str | None:
    pattern = rf"## {re.escape(header)}\s*\n+```\n(.*?)```"
    m = re.search(pattern, md_text, re.DOTALL)
    return m.group(1).strip() if m else None


def utf16_units(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def load_collection(col: str) -> dict:
    col_dir = COLLECTIONS_DIR / col
    desc_md = (col_dir / "20-documentation" / "descriptions.md").read_text(
        encoding="utf-8"
    )
    upload_tracking = json.loads(
        (col_dir / "20-documentation" / "upload_tracking.json").read_text(
            encoding="utf-8"
        )
    )
    cc = upload_tracking.get("complete_collection") or {}
    video_id = cc.get("video_id")
    if not video_id:
        raise RuntimeError(f"no complete_collection.video_id in {col}")

    description = extract_md_section(desc_md, "Complete Collection 概要欄")
    title = extract_md_section(desc_md, "タイトル案")
    tags_raw = extract_md_section(desc_md, "タグ（YouTube タグ欄）")
    tags = []
    if tags_raw:
        tags = [t.strip() for t in tags_raw.replace("\n", ",").split(",") if t.strip()]

    if not (description and title):
        raise RuntimeError(f"missing description or title section in {col}")

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
    parser.add_argument(
        "--only", help="comma-separated substring filter for collection names"
    )
    args = parser.parse_args()

    targets = TARGETS
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
