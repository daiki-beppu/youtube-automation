#!/usr/bin/env python3
"""Audit metadata across all live videos.

Checks each video published from collections/live/ against the same
quality bar enforced by the upload PreflightChecker, plus
remote-side checks against YouTube API.

Run periodically (or after upload) to detect drift between local
validated descriptions.json pairs and what's actually live on YouTube.

Usage:
    python3 automation/metadata_audit.py             # local + remote
    python3 automation/metadata_audit.py --local     # only validated descriptions pair
    python3 automation/metadata_audit.py --remote    # only YouTube API
    python3 automation/metadata_audit.py --strict    # exit 1 on any issue
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.configuration.model import ChannelConfig
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.documents.video_description import read_video_description_metadata
from youtube_automation.domains.metadata.descriptions import (
    extract_descriptions_md_section,
)
from youtube_automation.domains.uploads.preflight import (
    check_chapter_count,
    check_chapter_variation_suffix,
    check_duration,
    check_tags_count,
    check_tags_yt_chars,
    check_title_codepoint_limit,
    requires_scene_phrases,
)
from youtube_automation.infrastructure import cost_tracker
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths
from youtube_automation.infrastructure.media.probe import probe_duration


def _collections_dir() -> Path:
    """live collection のルートを遅延解決する.

    モジュールトップで即時評価すると import しただけで ``CHANNEL_DIR`` を要求してしまい、
    ``--help`` すら通らなくなる（`bulk_update_descriptions` と同じ扱い）.
    """
    return channel_dir() / "collections" / "live"


TS_RE = re.compile(r"^\d{1,2}:\d{2}")

# skill-config に chapters.remote_max が無い場合の最終フォールバック
_FALLBACK_REMOTE_CHAPTER_MAX = 12
SKILL_CONFIG_KEY = "audit.metadata"

_QUOTA_SERVICE = "youtube-data-api"
_READ_QUOTA_UNITS = 1


def _record_read_quota(bucket: str) -> None:
    """read 1 リクエスト分の quota 消費を記録する。記録失敗で元の処理は止めない。"""
    try:
        with contextlib.redirect_stdout(sys.stderr):
            cost_tracker.log_quota(_QUOTA_SERVICE, bucket, _READ_QUOTA_UNITS)
    except Exception:
        pass


def _remote_chapter_max() -> int:
    """REMOTE チェックのチャプター上限を skill-config から解決する。

    `.claude/skills/audit/config.default.yaml::metadata.chapters.remote_max` が default、
    `config/skills/audit.yaml::metadata` のチャンネル上書きが優先される。
    """
    chapters = load_skill_config(SKILL_CONFIG_KEY).get("chapters") or {}
    if not isinstance(chapters, dict):
        return _FALLBACK_REMOTE_CHAPTER_MAX
    return int(chapters.get("remote_max", _FALLBACK_REMOTE_CHAPTER_MAX))


def extract_section(text: str, header: str) -> str | None:
    return extract_descriptions_md_section(text, header)


def audit_local(col: Path, config: ChannelConfig) -> list[str]:
    """Return a list of issue descriptions for this collection."""
    issues: list[str] = []
    supported_langs = list(config.localizations.supported_languages)
    paths = CollectionPaths(col)

    desc_json = paths.descriptions_json_path
    stray = list(paths.docs_dir.glob("description*"))
    stray = [p for p in stray if p.name not in {"descriptions.json", "descriptions.html"}]
    if stray:
        issues.append(f"stray description file(s): {[p.name for p in stray]}")

    if not desc_json.exists():
        issues.append("descriptions.json missing")
        return issues
    try:
        metadata = read_video_description_metadata(desc_json)
    except ValidationError as error:
        issues.append(f"descriptions.json invalid: {error}")
        return issues
    title = str(metadata["title"])
    description = str(metadata["description"])

    if msg := check_title_codepoint_limit(title):
        issues.append(msg)
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
        try:
            state = read_workflow_state(ws)
            scene_phrases = state.scene_phrases or {}
        except WorkflowStateError as error:
            issues.append(f"workflow-state.json invalid: {error}")
        else:
            if requires_scene_phrases(supported_langs):
                required = list(dict.fromkeys(supported_langs))
                missing = [lang for lang in required if not scene_phrases.get(lang)]
                if missing:
                    issues.append(
                        f"workflow-state.scene_phrases missing langs: {missing[:6]}{'…' if len(missing) > 6 else ''}"
                    )
    else:
        issues.append("workflow-state.json missing")

    # タグ件数 / quotation 文字数（preflight と同じ JSON 正本）
    tags_value = metadata["tags"]
    tags = list(tags_value) if isinstance(tags_value, list) else []
    for msg in (
        check_tags_count(tags, config.content.tags.min_count),
        check_tags_yt_chars(tags),
    ):
        if msg:
            issues.append(msg)

    # 動画尺チェック（master mp4 がローカルに残っている場合のみ。
    # /publish --clean 後のコレクションでは skip して偽陽性を防ぐ）
    if config.audio.target_duration_min is not None or config.audio.target_duration_max is not None:
        master_video = paths.find_master_video()
        if master_video:
            dur = probe_duration(master_video)
            if dur is None:
                issues.append(f"duration probe failed for {master_video.name}")
            else:
                msg = check_duration(
                    dur,
                    (config.audio.target_duration_min * 60 if config.audio.target_duration_min is not None else None),
                    (config.audio.target_duration_max * 60 if config.audio.target_duration_max is not None else None),
                )
                if msg:
                    issues.append(msg)

    return issues


def audit_remote(video_ids: dict[str, str]) -> dict[str, list[str]]:
    """Fetch all videos from YouTube and check live state."""
    from youtube_automation.infrastructure.google.youtube import create_readonly_youtube_clients

    yt = create_readonly_youtube_clients().youtube_readonly
    issues: dict[str, list[str]] = {vid: [] for vid in video_ids}
    remote_chapter_max = _remote_chapter_max()

    ids_csv = ",".join(video_ids.keys())
    try:
        resp = yt.videos().list(id=ids_csv, part="snippet,localizations").execute()
    finally:
        # 失敗リクエストにも quota は課金されるため、成功・失敗どちらでも記録する
        _record_read_quota("videos.list")
    by_id = {it["id"]: it for it in resp.get("items", [])}

    for vid, _name in video_ids.items():
        item = by_id.get(vid)
        if not item:
            issues[vid].append("not found on YouTube")
            continue
        snippet = item.get("snippet")
        if not isinstance(snippet, dict):
            issues[vid].append("YT snippet missing or not an object")
            continue
        title = snippet.get("title", "")
        desc = snippet.get("description", "")
        locs = item.get("localizations", {}) or {}

        if msg := check_title_codepoint_limit(title):
            issues[vid].append(f"YT {msg}")
        if "🎧  🌧" in title or "🎧   🌧" in title:
            issues[vid].append("YT title scene_phrase missing (auto-truncated)")

        ts_lines = [line for line in desc.split("\n") if TS_RE.match(line.strip())]
        if len(ts_lines) > remote_chapter_max:
            issues[vid].append(f"YT description has {len(ts_lines)} chapters (>{remote_chapter_max})")

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
    for col in sorted(_collections_dir().iterdir()):
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

    print(f"📋 Auditing collections in {_collections_dir()}")
    print(f"   supported_languages: {supported_langs}\n")

    total_issues = 0

    if do_local:
        print("─── LOCAL (descriptions.json + HTML / workflow-state.json) ───")
        for col in sorted(_collections_dir().iterdir()):
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
