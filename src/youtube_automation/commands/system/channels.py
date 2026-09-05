"""Channel registry を読み取り専用で一覧表示する CLI。"""

from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.commands.system.automation_update_refs import _detect_pin
from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.analytics.channel_registry import (
    DEFAULT_CHANNEL_REGISTRY,
    load_channel_registry,
)

EXIT_REGISTRY_ERROR = 2


@dataclass(frozen=True)
class ChannelListing:
    path: str
    status: str
    pin: str


def _pin_label(path: Path) -> str | None:
    pyproject_path = path / "pyproject.toml"
    if not pyproject_path.is_file():
        return None
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        pin = _detect_pin(pyproject)
    except (OSError, tomllib.TOMLDecodeError, ConfigError):
        return None
    if pin.kind == "branch":
        return "main"
    if pin.kind == "tag":
        return f"tag {pin.value}"
    if pin.kind == "sha":
        return f"sha {pin.value[:12]}"
    return None


def _classify(path: Path) -> ChannelListing:
    if not path.is_dir():
        return ChannelListing(str(path), "missing", "none")
    if not (path / ".git").exists():
        return ChannelListing(str(path), "workspace", "none")
    pin = _pin_label(path)
    if pin is None:
        return ChannelListing(str(path), "workspace", "none")
    return ChannelListing(str(path), "eligible", pin)


def _summary(channels: list[ChannelListing]) -> dict[str, int]:
    return {
        "total": len(channels),
        "eligible": sum(channel.status == "eligible" for channel in channels),
        "workspace": sum(channel.status == "workspace" for channel in channels),
        "missing": sum(channel.status == "missing" for channel in channels),
    }


def _run(args: argparse.Namespace) -> int:
    channels = [_classify(path) for path in load_channel_registry(args.registry)]
    summary = _summary(channels)
    if args.json:
        payload = {"channels": [asdict(channel) for channel in channels], "summary": summary}
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    for channel in channels:
        print(f"{channel.path}\t{channel.status}\t{channel.pin}")
    print(" ".join(f"{key}={value}" for key, value in summary.items()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt-channels", description="channel registry の登録内容を操作する")
    subcommands = parser.add_subparsers(dest="command", required=True)
    list_parser = subcommands.add_parser("list", help="registry の各 path・適格状態・pin 種別を宣言順に表示する")
    list_parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_CHANNEL_REGISTRY,
        help=f"読み込む channel registry の JSON path（既定: {DEFAULT_CHANNEL_REGISTRY}）",
    )
    list_parser.add_argument("--json", action="store_true", help="各 entry と件数 summary を JSON で出力する")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        build_parser,
        _run,
        argv,
        failure_message="channel registry を読み込めません",
        failure_exit_code=EXIT_REGISTRY_ERROR,
    )


if __name__ == "__main__":
    raise SystemExit(main())
