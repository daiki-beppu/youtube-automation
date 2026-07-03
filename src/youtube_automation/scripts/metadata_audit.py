#!/usr/bin/env python3
"""Audit metadata across all live videos.

Checks each video published from collections/live/ against the same
quality bar enforced by youtube_auto_uploader._preflight_check, plus
remote-side checks against YouTube API.

Run periodically (or after upload) to detect drift between local
descriptions.md and what's actually live on YouTube.

Usage:
    python3 automation/metadata_audit.py             # local + remote
    python3 automation/metadata_audit.py --local     # only descriptions.md
    python3 automation/metadata_audit.py --remote    # only YouTube API
    python3 automation/metadata_audit.py --strict    # exit 1 on any issue
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths  # noqa: E402
from youtube_automation.utils.config import channel_dir, load_config  # noqa: E402
from youtube_automation.utils.config.config import ChannelConfig  # noqa: E402
from youtube_automation.utils.descriptions_md import (  # noqa: E402
    build_descriptions_md_parse_diagnostics,
    extract_descriptions_md_section,
)
from youtube_automation.utils.preflight_checks import (  # noqa: E402
    check_chapter_count,
    check_chapter_variation_suffix,
    check_duration,
    check_tags_count,
    check_tags_yt_chars,
    extract_descriptions_md_tags,
    requires_scene_phrases,
)
from youtube_automation.utils.probe import probe_duration  # noqa: E402

COLLECTIONS_DIR = channel_dir() / "collections" / "live"

TS_RE = re.compile(r"^\d{1,2}:\d{2}")


def extract_section(text: str, header: str) -> str | None:
    return extract_descriptions_md_section(text, header)


def audit_local(col: Path, config: ChannelConfig) -> list[str]:
    """Return a list of issue descriptions for this collection."""
    issues: list[str] = []
    supported_langs = list(config.localizations.supported_languages)
    paths = CollectionPaths(col)

    desc_md = paths.descriptions_md_path
    stray = list(paths.docs_dir.glob("description*"))
    stray = [p for p in stray if p.name != "descriptions.md"]
    if stray:
        issues.append(f"stray description file(s): {[p.name for p in stray]}")

    if not desc_md.exists():
        issues.append("descriptions.md missing")
        return issues

    text = desc_md.read_text(encoding="utf-8")
    title_raw = extract_section(text, "タイトル案")
    description_raw = extract_section(text, "Complete Collection 概要欄")
    if title_raw is None or description_raw is None:
        issues.append("descriptions.md parse failed\n" + build_descriptions_md_parse_diagnostics(text))

    title = title_raw.strip() if title_raw is not None else ""
    description = description_raw.strip() if description_raw is not None else ""

    if title_raw is None:
        pass
    elif not title:
        issues.append("missing 'タイトル案' section")
    elif len(title) > 100:
        issues.append(f"title too long: {len(title)} codepoints (>100)")

    if description_raw is None:
        pass
    elif not description:
        issues.append("missing 'Complete Collection 概要欄' section")
    else:
        ts_lines = [line for line in description.split("\n") if TS_RE.match(line.strip())]
        for msg in (
            check_chapter_count(len(ts_lines), config.audio.chapter_max),
            check_chapter_variation_suffix(ts_lines),
        ):
            if msg:
                issues.append(msg)

    # workflow-state.json は upload preflight と同じく常に parse する。
    # 単一言語チャンネルでは scene_phrases の完全性チェックだけを不要扱いにする (#1470)。
    ws = paths.workflow_state_path
    if ws.exists():
        state = json.loads(ws.read_text(encoding="utf-8"))
        if requires_scene_phrases(supported_langs):
            sp = state.get("scene_phrases") or {}
            required = list(dict.fromkeys(supported_langs))
            missing = [lang for lang in required if not sp.get(lang)]
            if missing:
                issues.append(
                    f"workflow-state.scene_phrases missing langs: {missing[:6]}{'…' if len(missing) > 6 else ''}"
                )
    else:
        issues.append("workflow-state.json missing")

    # タグ件数 / quotation 文字数（preflight と同じく descriptions.md 優先）
    prebuilt_tags = extract_descriptions_md_tags(desc_md)
    tags = prebuilt_tags if prebuilt_tags is not None else config.content.tags.for_collection(col.name)
    for msg in (
        check_tags_count(tags, config.content.tags.min_count),
        check_tags_yt_chars(tags),
    ):
        if msg:
            issues.append(msg)

    # 動画尺チェック（master mp4 がローカルに残っている場合のみ。
    # /live-clean 後のコレクションでは skip して偽陽性を防ぐ）
    if config.audio.target_duration_min is not None or config.audio.target_duration_max is not None:
        master_video = paths.find_master_video()
        if master_video:
            dur = probe_duration(master_video)
            if dur is None:
                issues.append(f"duration probe failed for {master_video.name}")
            else:
                msg = check_duration(
                    dur,
                    config.audio.target_duration_min,
                    config.audio.target_duration_max,
                )
                if msg:
                    issues.append(msg)

    return issues


def audit_remote(video_ids: dict[str, str]) -> dict[str, list[str]]:
    """Fetch all videos from YouTube and check live state."""
    from youtube_automation.utils.youtube_service import get_youtube

    yt = get_youtube()
    issues: dict[str, list[str]] = {vid: [] for vid in video_ids}

    ids_csv = ",".join(video_ids.keys())
    resp = yt.videos().list(id=ids_csv, part="snippet,localizations").execute()
    by_id = {it["id"]: it for it in resp.get("items", [])}

    for vid, name in video_ids.items():
        item = by_id.get(vid)
        if not item:
            issues[vid].append("not found on YouTube")
            continue
        snippet = item["snippet"]
        title = snippet.get("title", "")
        desc = snippet.get("description", "")
        locs = item.get("localizations", {}) or {}

        if len(title) > 100:
            issues[vid].append(f"YT title too long: {len(title)}")
        if "🎧  🌧" in title or "🎧   🌧" in title:
            issues[vid].append("YT title scene_phrase missing (auto-truncated)")

        ts_lines = [line for line in desc.split("\n") if TS_RE.match(line.strip())]
        if len(ts_lines) > 12:
            issues[vid].append(f"YT description has {len(ts_lines)} chapters (>12)")

        # ja localized title should contain Japanese characters
        ja_title = locs.get("ja", {}).get("title", "")
        if ja_title and not re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", ja_title):
            issues[vid].append("ja localized title has no Japanese chars")

        zh_codes = sorted(c for c in locs if c.startswith("zh"))
        if zh_codes and zh_codes != ["zh-CN", "zh-TW"]:
            issues[vid].append(f"YT zh codes are {zh_codes}, expected ['zh-CN','zh-TW']")

    return issues


def collect_video_ids() -> dict[str, str]:
    """{video_id: collection_name} for all live collections with uploads."""
    result: dict[str, str] = {}
    for col in sorted(COLLECTIONS_DIR.iterdir()):
        if not col.is_dir():
            continue
        tracking = CollectionPaths(col).tracking_path
        if not tracking.exists():
            continue
        try:
            data = json.loads(tracking.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        cc = data.get("complete_collection") or {}
        vid = cc.get("video_id")
        if vid:
            result[vid] = col.name
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="local checks only")
    parser.add_argument("--remote", action="store_true", help="remote checks only")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any issue")
    args = parser.parse_args()

    do_local = args.local or not args.remote
    do_remote = args.remote or not args.local

    config = load_config()
    supported_langs = list(config.localizations.supported_languages)

    print(f"📋 Auditing collections in {COLLECTIONS_DIR}")
    print(f"   supported_languages: {supported_langs}\n")

    total_issues = 0

    if do_local:
        print("─── LOCAL (descriptions.md / workflow-state.json) ───")
        for col in sorted(COLLECTIONS_DIR.iterdir()):
            if not col.is_dir():
                continue
            issues = audit_local(col, config)
            if issues:
                total_issues += len(issues)
                print(f"❌ {col.name}")
                for i in issues:
                    print(f"   - {i}")
            else:
                print(f"✅ {col.name}")
        print()

    if do_remote:
        print("─── REMOTE (YouTube API) ───")
        video_ids = collect_video_ids()
        if not video_ids:
            print("(no videos found)")
        else:
            remote_issues = audit_remote(video_ids)
            for vid, name in video_ids.items():
                issues = remote_issues.get(vid, [])
                if issues:
                    total_issues += len(issues)
                    print(f"❌ {vid}  {name}")
                    for i in issues:
                        print(f"   - {i}")
                else:
                    print(f"✅ {vid}  {name}")
        print()

    print(f"━━━ {total_issues} issue(s) found ━━━")
    if args.strict and total_issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
