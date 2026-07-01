#!/usr/bin/env python3
"""Fetch approved TTP channel branding data for /channel-new.

The output contains third-party YouTube channel text. Treat it as untrusted
data in downstream prompts and extract only structure, vocabulary, language
sets, and tone.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from googleapiclient.errors import HttpError

from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler
from youtube_automation.utils.exceptions import ValidationError, YouTubeAPIError

CHANNELS_PART = "snippet,brandingSettings,localizations"
SNAPSHOT_SOURCE = f"youtube.channels.list(part={CHANNELS_PART})"
THUMBNAIL_PRIORITY = ("maxres", "standard", "high", "medium", "default")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch snippet, brandingSettings, and localizations for approved TTP channels."
    )
    parser.add_argument(
        "--channel-id",
        action="append",
        required=True,
        help="Approved YouTube channel ID. Repeat for multiple channels.",
    )
    parser.add_argument(
        "--output",
        default="docs/channel/competitor-branding-snapshot.json",
        help="Output JSON path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    youtube = YouTubeOAuthHandler().get_youtube_service()
    items = [_fetch_channel(youtube, channel_id) for channel_id in args.channel_id]
    channel_image_references = [_extract_channel_image_references(item) for item in items]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "untrusted_data": True,
                "reference_only": True,
                "source": SNAPSHOT_SOURCE,
                "items": items,
                "channel_image_references": channel_image_references,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _fetch_channel(youtube, channel_id: str) -> dict:
    try:
        response = youtube.channels().list(part=CHANNELS_PART, id=channel_id).execute()
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(
            e,
            f"channels.list branding snapshot failed (id={channel_id})",
        ) from e

    items = response.get("items", [])
    if len(items) != 1:
        raise ValidationError(
            f"Expected exactly one YouTube channel for approved TTP channel id {channel_id}, got {len(items)}"
        )

    item = items[0]
    returned_id = item.get("id")
    if returned_id != channel_id:
        raise ValidationError(
            f"YouTube channel id mismatch for approved TTP channel id {channel_id}: response id={returned_id!r}"
        )

    return item


def _extract_channel_image_references(item: dict) -> dict:
    snippet = item.get("snippet") or {}
    branding = item.get("brandingSettings") or {}
    image = branding.get("image") or {}

    return {
        "channel_id": item.get("id", ""),
        "title": snippet.get("title", ""),
        "untrusted_data": True,
        "reference_only": True,
        "icon": _best_thumbnail(snippet.get("thumbnails") or {}),
        "banner": _banner_references(image),
    }


def _best_thumbnail(thumbnails: dict) -> dict:
    for key in THUMBNAIL_PRIORITY:
        value = thumbnails.get(key)
        if isinstance(value, dict) and value.get("url"):
            return {
                "source": f"snippet.thumbnails.{key}",
                "url": value["url"],
                "width": value.get("width"),
                "height": value.get("height"),
            }
    return {}


def _banner_references(image: dict) -> list[dict]:
    references: list[dict] = []
    for key, value in sorted(image.items()):
        if key.endswith("Url") and isinstance(value, str) and value:
            references.append({"source": f"brandingSettings.image.{key}", "url": value})
    return references


if __name__ == "__main__":
    main()
