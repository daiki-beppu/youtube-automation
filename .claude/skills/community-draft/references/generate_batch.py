#!/usr/bin/env python3
"""Render deterministic community post batches from channel configuration."""

from __future__ import annotations

import argparse
import json
import string
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.utils.exceptions import ConfigError

_ALLOWED_VARIABLES = frozenset({"title", "date", "custom_message"})


@dataclass(frozen=True)
class TemplateVariables:
    title: str
    date: str
    custom_message: str

    def as_mapping(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class CommunityPost:
    text: str
    scheduled_at: str
    image_path: str
    visibility: str = "public"


def _read_state(collection: Path) -> dict[str, object]:
    state_path = collection / "workflow-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"workflow-state.json が見つかりません: {state_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"workflow-state.json が不正な JSON です: {state_path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ConfigError("workflow-state.json の root は object でなければなりません")
    return state


def _planning_value(state: dict[str, object], key: str) -> str:
    planning = state.get("planning")
    if not isinstance(planning, dict):
        raise ConfigError("workflow-state.json::planning が未設定です")
    value = planning.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"workflow-state.json::planning.{key} が未設定です")
    return value


def _publish_local(raw: str, timezone: ZoneInfo) -> datetime:
    try:
        if len(raw) == 10:
            return datetime.combine(date.fromisoformat(raw), time.min, tzinfo=timezone)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError("workflow-state.json::planning.publish_target_at は ISO 8601 で指定してください") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _render(template: str, variables: TemplateVariables) -> str:
    values = variables.as_mapping()
    fields = {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}
    unknown = fields - _ALLOWED_VARIABLES
    if unknown:
        raise ConfigError(f"community_draft template に未知の変数があります: {', '.join(sorted(unknown))}")
    missing = {field for field in fields if not values.get(field)}
    if missing:
        raise ConfigError(f"community_draft template 変数が未設定です: {', '.join(sorted(missing))}")
    return template.format_map(values)


def _output_image_path(channel_root: Path, collection: Path, image: str) -> str:
    image_path = (collection / image).resolve()
    try:
        return image_path.relative_to(channel_root.resolve()).as_posix()
    except ValueError as exc:
        raise ConfigError("community_draft.posts[].image が channel directory の外を指しています") from exc


def generate_batch(collection: Path) -> Path:
    config = load_config()
    channel_root = channel_dir().resolve()
    collection = collection.expanduser().resolve()
    try:
        collection.relative_to(channel_root)
    except ValueError as exc:
        raise ConfigError(f"collection は channel directory 配下を指定してください: {collection}") from exc

    if not config.community_draft.posts:
        raise ConfigError("config/channel/community-draft.json::community_draft.posts が未設定です")

    state = _read_state(collection)
    title = _planning_value(state, "final_title")
    publish_raw = _planning_value(state, "publish_target_at")
    timezone_name = config.youtube.api.default_publish_timezone
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"youtube.default_publish_timezone が不正です: {timezone_name!r}") from exc
    publish_local = _publish_local(publish_raw, timezone)

    variables = TemplateVariables(
        title=title,
        date=publish_local.date().isoformat(),
        custom_message=config.community_draft.variables.get("custom_message", ""),
    )
    posts: list[CommunityPost] = []
    for post in config.community_draft.posts:
        scheduled_date = publish_local.date() + timedelta(days=post.schedule_offset_days)
        scheduled_clock = time.fromisoformat(post.schedule_time)
        scheduled_at = datetime.combine(scheduled_date, scheduled_clock, tzinfo=timezone)
        posts.append(
            CommunityPost(
                text=_render(post.template, variables),
                scheduled_at=scheduled_at.isoformat(),
                image_path=_output_image_path(channel_root, collection, post.image),
            )
        )

    output_path = collection / "30-promo/community-posts.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"posts": [asdict(post) for post in posts]}, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, delete=False) as handle:
            handle.write(payload)
            temporary_path = Path(handle.name)
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="community-draft JSON batch generator")
    parser.add_argument("--batch", action="store_true", required=True, help="deterministic batch generation mode")
    parser.add_argument("--collection", type=Path, required=True, help="target collection directory")
    args = parser.parse_args()
    try:
        output_path = generate_batch(args.collection)
    except (ConfigError, OSError, ValueError) as exc:
        print(f"community-draft: {exc}", file=sys.stderr)
        return 1
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
