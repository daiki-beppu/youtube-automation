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
import logging
import time

from googleapiclient.errors import HttpError

from youtube_automation.configuration import channel_dir
from youtube_automation.utils.cost_tracker import log_quota
from youtube_automation.utils.descriptions_md import (
    build_descriptions_md_parse_diagnostics,
    extract_descriptions_md_section,
)
from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.youtube_service import get_youtube
from youtube_automation.utils.youtube_tag import parse_youtube_tags

logger = logging.getLogger(__name__)

# videos.update(part="snippet") で書き込み可能な mutable フィールド。
# videos().list(part="snippet") のレスポンスにはこれ以外に publishedAt / channelId /
# thumbnails / channelTitle / localized / liveBroadcastContent 等の read-only
# フィールドが混ざるため、丸ごとコピーせず whitelist で保持する。
# YouTube Data API quota 記録（Issue #2058）。units は公式 quota 表に従う
# （https://developers.google.com/youtube/v3/determine_quota_cost）。
QUOTA_SERVICE = "youtube-data-api"
QUOTA_UNITS = {
    "videos.list": 1,
    "videos.update": 50,
}

MUTABLE_SNIPPET_KEYS = (
    "title",
    "description",
    "tags",
    "categoryId",
    "defaultLanguage",
    "defaultAudioLanguage",
)


def build_snippet_update_body(video_id: str, old_snippet: dict, title: str, description: str, tags: list) -> dict:
    """現 snippet の mutable キーを保持したまま title/description/tags を差し替えた update body を返す.

    ``videos.update(part='snippet')`` は snippet リソース全体を置換するため、
    body に含まれない mutable フィールド（defaultAudioLanguage 等）は消える。
    bulk_update_synthetic_media.build_update_body と同じ read-modify-write 方式。
    """
    new_snippet = {k: old_snippet[k] for k in MUTABLE_SNIPPET_KEYS if k in old_snippet}
    new_snippet["title"] = title
    new_snippet["description"] = description
    new_snippet["tags"] = tags
    new_snippet.setdefault("categoryId", "10")
    return {"id": video_id, "snippet": new_snippet}


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


def _execute_youtube_request(
    request,
    context: str,
    *,
    quota_bucket: str,
    quota_metadata: dict | None = None,
) -> dict:
    """YouTube API の HttpError を呼び出し文脈付きドメイン例外へ変換する.

    quota はリクエストの成否に関わらず消費されるため、失敗時も記録してから
    例外を伝播させる（Issue #2058）。
    """
    try:
        return request.execute()
    except HttpError as error:
        raise YouTubeAPIError.from_http_error(error, context) from error
    finally:
        log_quota(QUOTA_SERVICE, quota_bucket, QUOTA_UNITS[quota_bucket], metadata=quota_metadata)


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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
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
        # 1 collection の意味的な metadata 不備は他 collection の更新を妨げない。
        # JSON 破損や I/O error はここで捕捉せず、修復が必要な失敗として伝播させる。
        except RuntimeError as error:
            logger.error("❌ %s: %s", col, error)

    if not payloads:
        logger.info("nothing to do")
        return

    yt = get_youtube()
    ids = ",".join(p["video_id"] for p in payloads)
    current = _execute_youtube_request(
        yt.videos().list(id=ids, part="snippet"),
        "Failed to fetch current video snippets",
        quota_bucket="videos.list",
        quota_metadata={"video_count": len(payloads)},
    )
    by_id = {item["id"]: item for item in current.get("items", [])}

    first_update_error: YouTubeAPIError | None = None
    for p in payloads:
        item = by_id.get(p["video_id"])
        if not item:
            logger.error("❌ %s (%s): not found on YouTube", p["video_id"], p["collection"])
            continue
        old_snippet = item["snippet"]
        old_title = old_snippet.get("title", "")
        old_desc = old_snippet.get("description", "")

        new_title = p["title"]
        new_desc = p["description"]
        new_tags = p["tags"] or old_snippet.get("tags", [])

        title_units = utf16_units(new_title)
        if title_units > 100:
            logger.warning(
                "⚠️  %s (%s): new title is %s UTF-16 units (>100). Keeping old title; updating description only.",
                p["video_id"],
                p["collection"],
                title_units,
            )
            new_title = old_title

        logger.info("\n%s", "─" * 60)
        logger.info("🎬 %s  %s", p["video_id"], p["collection"])
        logger.info("   title (old → new):")
        logger.info("     %s", old_title)
        logger.info("     %s  [%s units]", new_title, title_units)
        logger.info("   description first lines (old → new):")
        for line in old_desc.split("\n")[:6]:
            logger.info("     - %s", line)
        logger.info("       …")
        for line in new_desc.split("\n")[:6]:
            logger.info("     + %s", line)

        if args.dry_run:
            continue

        body = build_snippet_update_body(p["video_id"], old_snippet, new_title, new_desc, new_tags)
        try:
            _execute_youtube_request(
                yt.videos().update(part="snippet", body=body),
                f"Failed to update video {p['video_id']}",
                quota_bucket="videos.update",
                quota_metadata={"video_id": p["video_id"]},
            )
            logger.info("   ✅ updated")
        except YouTubeAPIError as error:
            logger.error("   ❌ update failed: %s", error)
            if first_update_error is None:
                first_update_error = error
        time.sleep(0.4)

    if first_update_error is not None:
        raise first_update_error

    if args.dry_run:
        logger.info("\n🔍 dry-run; %s videos would be updated", len(payloads))
    else:
        logger.info("\n✅ done")


if __name__ == "__main__":
    main()
