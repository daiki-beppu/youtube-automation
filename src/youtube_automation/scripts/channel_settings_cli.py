#!/usr/bin/env python3
"""yt-channel-settings: YouTube チャンネル設定の双方向同期 CLI。

サブコマンド:
    diff   remote と local の差分を表示（読み取り専用）
    push   local → YouTube（デフォルト dry-run、--apply で反映）
    pull   YouTube → local（デフォルト dry-run、--apply でファイル書き換え）

対象: brandingSettings.channel (description, keywords, country, defaultLanguage,
unsubscribedTrailer), localizations, status.selfDeclaredMadeForKids。

Usage:
    yt-channel-settings diff
    yt-channel-settings push
    yt-channel-settings push --apply
    yt-channel-settings pull
    yt-channel-settings pull --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from youtube_automation.utils.channel_settings import (
    build_update_body,
    diff_settings,
    fetch_channel,
    parse_api_response,
    verify_channel_id,
)
from youtube_automation.utils.config import ChannelConfig, load_config
from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.exceptions import ConfigError, YouTubeAPIError
from youtube_automation.utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)


def _load_local(config: ChannelConfig, include_localizations: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    channel = dict(config.meta.branding.as_api_dict())
    localizations: dict[str, Any] = {}
    if include_localizations and config.localizations.exists:
        localizations = dict(config.localizations.data)
    return channel, localizations


def _print_diff(lines: list[str], direction: str) -> None:
    if not lines:
        print("✨ no diff; local and remote are in sync.")
        return
    print(f"🔍 diff ({direction}):")
    for line in lines:
        print(line)


def _cmd_diff(args: argparse.Namespace) -> int:
    config = load_config()
    local_channel, local_loc = _load_local(config, include_localizations=not args.no_localizations)

    youtube = get_youtube()
    remote_raw = fetch_channel(youtube)
    remote_channel, remote_loc = parse_api_response(remote_raw)
    if args.no_localizations:
        remote_loc = {}
    channel_id = remote_raw.get("id", "<unknown>")
    print(f"📡 fetched remote channel settings (channelId={channel_id})")

    lines = diff_settings(local_channel, local_loc, remote_channel, remote_loc)
    _print_diff(lines, direction="local → remote")
    return 0


def _cmd_push(args: argparse.Namespace) -> int:
    config = load_config()
    local_channel, local_loc = _load_local(config, include_localizations=not args.no_localizations)

    youtube = get_youtube()
    remote_raw = fetch_channel(youtube)
    remote_channel, remote_loc = parse_api_response(remote_raw)
    if args.no_localizations:
        remote_loc = {}
    channel_id = remote_raw["id"]
    print(f"📡 fetched remote channel settings (channelId={channel_id})")

    # safety: 別チャンネルの OAuth トークンで設定を取り違えて上書きする事故を防ぐ (#561)。
    verify_channel_id(config.meta.channel_id, channel_id)
    if not config.meta.channel_id:
        print(
            "⚠️  config/channel/meta.json に channel.channel_id が未設定です。\n"
            f'   取り違え防止のため channel.channel_id: "{channel_id}" の追記を推奨します。'
        )

    lines = diff_settings(local_channel, local_loc, remote_channel, remote_loc)
    _print_diff(lines, direction="local → remote")

    if not lines:
        return 0

    if not args.apply:
        print("✋ dry-run. re-run with --apply to push changes.")
        return 0

    body = build_update_body(
        local_channel,
        local_loc if not args.no_localizations else None,
        channel_id,
    )
    parts = [p for p in ("brandingSettings", "localizations", "status") if p in body]
    if not parts:
        print("⚠️  no updatable fields in local config; nothing to push.")
        return 0

    # YouTube Data API は `brandingSettings` を他の part と同時に送ると 400 を返す
    # (`branding_settings cannot be used with other parts`)。part 単位で個別に
    # channels().update() を呼ぶ。(#230)
    for part in parts:
        try:
            youtube.channels().update(
                part=part,
                body={"id": channel_id, part: body[part]},
            ).execute()
        except Exception as e:
            raise YouTubeAPIError(f"channels().update(part={part}) failed: {e}") from e
    print(f"✅ pushed {len(lines) // 3} change(s) to YouTube ({len(parts)} API call(s)).")
    return 0


def _cmd_pull(args: argparse.Namespace) -> int:
    config = load_config()
    local_channel, local_loc = _load_local(config, include_localizations=not args.no_localizations)

    youtube = get_youtube()
    remote_raw = fetch_channel(youtube)
    remote_channel, remote_loc = parse_api_response(remote_raw)
    channel_id = remote_raw["id"]
    print(f"📡 fetched remote channel settings (channelId={channel_id})")

    if args.channel_id_only:
        if not args.apply:
            print("✋ dry-run. re-run with --apply to write channel.channel_id.")
            return 0
        config_path = _channel_dir() / "config" / "channel" / "meta.json"
        _write_channel_settings(config_path, channel_id)
        print(f"📝 wrote channel.channel_id → {config_path}")
        return 0

    lines = diff_settings(remote_channel, remote_loc, local_channel, local_loc)
    _print_diff(lines, direction="remote → local")

    if not lines:
        return 0

    if not args.apply:
        print("✋ dry-run. re-run with --apply to overwrite local files.")
        return 0

    channel_dir = _channel_dir()
    config_path = channel_dir / "config" / "channel" / "meta.json"
    _write_channel_settings(config_path, channel_id, remote_channel)
    print(f"📝 wrote channel.channel_id and youtube_channel section → {config_path}")

    if not args.no_localizations and remote_loc:
        loc_path = channel_dir / "config" / "localizations.json"
        _write_localizations(loc_path, remote_loc)
        print(f"📝 wrote localizations → {loc_path}")

    print("✅ pulled remote settings to local.")
    return 0


def _write_channel_settings(
    path: Path,
    channel_id: str,
    youtube_channel: dict[str, Any] | None = None,
) -> None:
    """config/channel/meta.json の channel_id（と任意で youtube_channel）を差し替える。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    _set_channel_id(data, channel_id)
    if youtube_channel is not None:
        data["youtube_channel"] = youtube_channel
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _set_channel_id(data: dict[str, Any], channel_id: str) -> None:
    channel = data.get("channel")
    if not isinstance(channel, dict):
        raise ConfigError("config/channel/meta.json の channel セクションが不正です")
    channel["channel_id"] = channel_id


def _write_localizations(path: Path, remote_loc: dict[str, Any]) -> None:
    """localizations.json をマージ書き換えする。

    既存ファイルがあれば supported_languages と各言語エントリを更新、
    無ければ新規作成する。既存の不要フィールドは残す。
    """
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}
    data["supported_languages"] = list(remote_loc.get("supported_languages", []))
    for lang, entry in remote_loc.items():
        if lang == "supported_languages":
            continue
        existing = data.get(lang, {})
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.update(entry)
            data[lang] = merged
        else:
            data[lang] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-channel-settings",
        description="Sync YouTube channel settings between local config and YouTube.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable DEBUG logging")
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--no-localizations",
            action="store_true",
            help="skip localizations sync",
        )

    p_diff = sub.add_parser("diff", help="show diff between local and remote (read-only)")
    _add_common(p_diff)
    p_diff.set_defaults(func=_cmd_diff)

    p_push = sub.add_parser("push", help="local → YouTube (dry-run by default)")
    _add_common(p_push)
    p_push.add_argument("--apply", action="store_true", help="actually call channels().update()")
    p_push.set_defaults(func=_cmd_push)

    p_pull = sub.add_parser("pull", help="YouTube → local (dry-run by default)")
    _add_common(p_pull)
    p_pull.add_argument("--apply", action="store_true", help="actually overwrite local config files")
    p_pull.add_argument(
        "--channel-id-only",
        action="store_true",
        help="write only config/channel/meta.json::channel.channel_id",
    )
    p_pull.set_defaults(func=_cmd_pull)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    try:
        return args.func(args)
    except (ConfigError, YouTubeAPIError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
