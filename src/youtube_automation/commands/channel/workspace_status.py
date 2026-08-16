"""Workspace 内の全チャンネル統計を 1 request で取得する CLI。"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration import (
    find_workspace_root,
    select_channel,
    workspace_channels,
)
from youtube_automation.configuration.loader import load_config_from_path
from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.infrastructure import cost_tracker
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.google.youtube import (
    create_readonly_youtube_clients,
    execute_youtube_request,
    validate_youtube_response_items,
)

EXIT_OK = 0
EXIT_OUTSIDE_WORKSPACE = 1
EXIT_EMPTY_WORKSPACE = 2
EXIT_UNREADABLE = 3
EXIT_NO_CHANNEL_IDS = 4
EXIT_AUTH_REQUIRED = 5
EXIT_NO_RESULTS = 6

_QUOTA_SERVICE = "youtube-data-api"
_QUOTA_BUCKET = "channels.list"
_READ_QUOTA_UNITS = 1


@dataclass(frozen=True)
class _ChannelTarget:
    slug: str
    channel_id: str
    fallback_name: str


@dataclass(frozen=True)
class WorkspaceChannelStatus:
    """Workspace の1チャンネル分の表示用統計。"""

    slug: str
    channel_id: str
    channel_name: str
    subscriber_count: int
    total_views: int
    video_count: int


def _workspace_root(start: Path | None = None) -> Path | None:
    """有効な workspace を探し、空の ``channels/`` も識別する。"""
    current = (start or Path.cwd()).expanduser().resolve()
    detected = find_workspace_root(current)
    if detected is not None:
        return detected
    for candidate in (current, *current.parents):
        if (candidate / "channels").is_dir():
            return candidate
    return None


def _targets(channels: Mapping[str, Path]) -> list[_ChannelTarget]:
    targets: list[_ChannelTarget] = []
    for slug, channel_path in channels.items():
        config = load_config_from_path(channel_path)
        channel_id = config.meta.channel_id.strip()
        if not channel_id:
            print(
                f"[warning] {slug}: config.meta.channel_id が空のため取得対象から除外します",
                file=sys.stderr,
            )
            continue
        targets.append(
            _ChannelTarget(
                slug=slug,
                channel_id=channel_id,
                fallback_name=config.meta.channel_name,
            )
        )
    return targets


def _has_readonly_token(channel_path: Path) -> bool:
    return (channel_path / "auth" / YouTubeOAuthHandler.READONLY_TOKEN_FILENAME).is_file()


def _credential_provider(channels: Mapping[str, Path], override: str | None) -> str | None:
    if override is not None:
        if override not in channels:
            candidates = ", ".join(channels) or "(なし)"
            raise ConfigError(f"--channel={override!r} が workspace にありません。候補: {candidates}")
        return override if _has_readonly_token(channels[override]) else None
    return next((slug for slug, path in channels.items() if _has_readonly_token(path)), None)


def _record_quota() -> None:
    """JSON stdout を守りながら read request 1回分を記録する。"""
    with contextlib.redirect_stdout(sys.stderr):
        cost_tracker.log_quota(_QUOTA_SERVICE, _QUOTA_BUCKET, _READ_QUOTA_UNITS)


def _as_mapping(value: object, field: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"channels.list の {field} は object でなければなりません")
    return value


def _as_count(value: object, field: str, channel_id: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"channels.list の {field} が不正です: channel_id={channel_id}")
    try:
        count = int(value) if isinstance(value, (int, str)) else -1
    except ValueError as error:
        raise ValidationError(f"channels.list の {field} が不正です: channel_id={channel_id}") from error
    if count < 0:
        raise ValidationError(f"channels.list の {field} が不正です: channel_id={channel_id}")
    return count


def _response_by_id(response: object) -> dict[str, Mapping[object, object]]:
    items = validate_youtube_response_items(response, "channels.list")
    by_id: dict[str, Mapping[object, object]] = {}
    for value in items:
        item = _as_mapping(value, "items entry")
        channel_id = item.get("id")
        if not isinstance(channel_id, str) or not channel_id:
            raise ValidationError("channels.list item.id が空です")
        by_id[channel_id] = item
    return by_id


def _status(target: _ChannelTarget, item: Mapping[object, object]) -> WorkspaceChannelStatus:
    snippet = _as_mapping(item.get("snippet", {}), "snippet")
    statistics = _as_mapping(item.get("statistics", {}), "statistics")
    title = snippet.get("title")
    channel_name = title.strip() if isinstance(title, str) and title.strip() else target.fallback_name
    channel_name = " ".join(channel_name.split())
    return WorkspaceChannelStatus(
        slug=target.slug,
        channel_id=target.channel_id,
        channel_name=channel_name,
        subscriber_count=_as_count(statistics.get("subscriberCount", 0), "subscriberCount", target.channel_id),
        total_views=_as_count(statistics.get("viewCount", 0), "viewCount", target.channel_id),
        video_count=_as_count(statistics.get("videoCount", 0), "videoCount", target.channel_id),
    )


def _fetch_statuses(targets: list[_ChannelTarget]) -> list[WorkspaceChannelStatus]:
    clients = create_readonly_youtube_clients()
    request = clients.youtube_readonly.channels().list(
        part="snippet,statistics",
        id=",".join(target.channel_id for target in targets),
    )
    response = execute_youtube_request(request, "workspace channel statistics", on_attempt=_record_quota)
    items = _response_by_id(response)
    statuses: list[WorkspaceChannelStatus] = []
    for target in targets:
        item = items.get(target.channel_id)
        if item is None:
            print(
                f"[warning] {target.slug}: channels.list に channel_id={target.channel_id} の結果がありません",
                file=sys.stderr,
            )
            continue
        statuses.append(_status(target, item))
    return statuses


def _print_table(statuses: list[WorkspaceChannelStatus]) -> None:
    print("slug\tチャンネル名\t登録者数\t総再生回数\t動画数")
    for status in statuses:
        print(
            f"{status.slug}\t{status.channel_name}\t{status.subscriber_count:,}"
            f"\t{status.total_views:,}\t{status.video_count:,}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-workspace-status",
        description="workspace 配下の全チャンネル統計を channels.list 1 request で取得する。",
    )
    parser.add_argument("--json", action="store_true", help="表の代わりに機械可読 JSON を出力する")
    parser.add_argument(
        "--channel",
        metavar="slug",
        help="readonly token を使う credential 提供元チャンネルを明示する",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    try:
        workspace_root = _workspace_root()
        if workspace_root is None:
            print(
                "[error] workspace が見つかりません。"
                "channels/<slug>/config/channel/ を持つ workspace 配下で実行してください。",
                file=sys.stderr,
            )
            return EXIT_OUTSIDE_WORKSPACE
        channels = workspace_channels(workspace_root)
        if not channels:
            print(
                f"[error] workspace に channel がありません: {workspace_root / 'channels'}. "
                "channels/<slug>/config/channel/ を作成してください。",
                file=sys.stderr,
            )
            return EXIT_EMPTY_WORKSPACE
        targets = _targets(channels)
    except OSError as error:
        print(
            f"[error] workspace の channel directory を読み取れません: {error}. "
            "channels/ 配下の読み取り・実行権限を確認してください。",
            file=sys.stderr,
        )
        return EXIT_UNREADABLE

    if not targets:
        print("[error] channel_id が設定されたチャンネルがありません", file=sys.stderr)
        return EXIT_NO_CHANNEL_IDS

    provider = _credential_provider(channels, args.channel)
    if provider is None:
        detail = f" --channel {args.channel}" if args.channel is not None else ""
        candidates = ", ".join(channels)
        print(
            f"[error] readonly token が見つかりません（確認済み: {candidates}）。対話可能なターミナルで "
            f"`uv run yt-oauth --readonly{detail}` を実行してください。",
            file=sys.stderr,
        )
        return EXIT_AUTH_REQUIRED

    select_channel(provider)
    statuses = _fetch_statuses(targets)
    if not statuses:
        print("[error] channels.list からチャンネル統計を取得できませんでした", file=sys.stderr)
        return EXIT_NO_RESULTS
    if args.json:
        print(json.dumps([asdict(status) for status in statuses], ensure_ascii=False, indent=2))
    else:
        _print_table(statuses)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="workspace status 取得エラー")


if __name__ == "__main__":
    raise SystemExit(main())
