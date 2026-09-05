"""Channel registry の一覧表示と直列更新を行う CLI。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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


@dataclass(frozen=True)
class ChannelUpdate:
    path: str
    status: str
    ref: str
    actions: tuple[str, ...] = ()
    detail: str = ""


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


def _run_list(args: argparse.Namespace) -> int:
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


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _selected_channels(channels: list[Path], selected: list[Path] | None) -> list[Path]:
    if not selected:
        return channels
    result: list[Path] = []
    for requested in selected:
        match = next((channel for channel in channels if _same_path(channel, requested)), None)
        if match is None:
            raise ConfigError(f"--channel は registry 内の path に限定されます: {requested}")
        if match not in result:
            result.append(match)
    return [channel for channel in channels if channel in result]


def _run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _ineligible_update(listing: ChannelListing, tag: str | None) -> ChannelUpdate | None:
    if listing.status == "workspace":
        return ChannelUpdate(listing.path, "skipped", listing.pin, detail="workspace")
    if listing.status == "missing":
        return ChannelUpdate(listing.path, "error", listing.pin, detail="path 不在")

    pin_kind = listing.pin.split(maxsplit=1)[0]
    if tag is None and pin_kind in {"tag", "sha"}:
        return ChannelUpdate(listing.path, "skipped", listing.pin, detail=f"{pin_kind} pin（--tag 未指定）")
    if tag is not None and pin_kind != "tag":
        return ChannelUpdate(listing.path, "skipped", listing.pin, detail=f"{pin_kind} pin（--tag は tag pin 専用）")
    return None


def _update_command(args: argparse.Namespace) -> list[str]:
    operation = "check" if args.dry_run else "apply"
    command = ["uv", "run", "yt-automation-update", operation]
    if not args.dry_run and not args.no_commit:
        command.append("--commit")
    if args.tag is not None:
        command.extend(["--tag", args.tag])
    if not args.dry_run and args.force_sync:
        command.append("--force-sync")
    if not args.dry_run and args.allow_dirty:
        command.append("--allow-dirty")
    if not args.dry_run and args.accept_hooks:
        command.append("--accept-hooks")
    return command


def _followup_actions(path: Path, apply_output: str) -> tuple[str, ...]:
    actions: list[str] = []
    if "Claude Code を再起動" in apply_output:
        actions.append("Claude Code 再起動")
    try:
        migrate = _run_command(
            ["uv", "run", "yt-skills", "migrate-config", "--channel-dir", str(path), "--dry-run"], path
        )
        if "dry-run 完了:" in migrate.stdout:
            actions.append("要 migrate")
    except OSError:
        actions.append("migrate 確認失敗")
    try:
        render = _run_command(["uv", "run", "yt-document-render", "--check", "--all"], path)
        if render.returncode != 0:
            actions.append("要 render")
    except OSError:
        actions.append("render 確認失敗")
    return tuple(actions)


def _update_one(path: Path, args: argparse.Namespace) -> ChannelUpdate:
    listing = _classify(path)
    ineligible = _ineligible_update(listing, args.tag)
    if ineligible is not None:
        return ineligible

    try:
        completed = _run_command(_update_command(args), path)
    except OSError as exc:
        return ChannelUpdate(str(path), "failed", args.tag or listing.pin, detail=str(exc))
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    if args.dry_run and completed.returncode in {0, 1}:
        detail = "更新差分あり" if completed.returncode == 1 else "最新です"
        return ChannelUpdate(str(path), "success", args.tag or listing.pin, detail=detail)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        return ChannelUpdate(str(path), "failed", args.tag or listing.pin, detail=detail)
    return ChannelUpdate(str(path), "success", args.tag or listing.pin, _followup_actions(path, output))


def _run_update(args: argparse.Namespace) -> int:
    registered = load_channel_registry(args.registry)
    try:
        channels = _selected_channels(registered, args.channel)
    except ConfigError as error:
        print(f"[error] 更新対象の指定が不正です: {error}", file=sys.stderr)
        return 1
    cwd = Path.cwd()
    channels.sort(key=lambda channel: _same_path(channel, cwd))
    results = [_update_one(channel, args) for channel in channels]
    summary = {
        "total": len(results),
        "success": sum(result.status == "success" for result in results),
        "skipped": sum(result.status == "skipped" for result in results),
        "failed": sum(result.status in {"failed", "error"} for result in results),
    }
    if args.json:
        print(json.dumps({"channels": [asdict(result) for result in results], "summary": summary}, ensure_ascii=False))
    else:
        for result in results:
            actions = ", ".join(result.actions) or "なし"
            detail = f"\t{result.detail}" if result.detail else ""
            print(f"{result.path}\t{result.status}\t{result.ref}\t要対応: {actions}{detail}")
        print(" ".join(f"{key}={value}" for key, value in summary.items()))
    return 1 if summary["failed"] else 0


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
    list_parser.set_defaults(func=_run_list)
    update_parser = subcommands.add_parser("update", help="registry の適格チャンネルを宣言順に直列更新する")
    update_parser.add_argument(
        "--registry", type=Path, default=DEFAULT_CHANNEL_REGISTRY, help="channel registry の JSON path"
    )
    update_parser.add_argument("--channel", type=Path, action="append", help="registry 内の更新対象 path（複数指定可）")
    update_parser.add_argument("--tag", help="tag pin チャンネルの追従先 vX.Y.Z")
    update_parser.add_argument("--force-sync", action="store_true", help="apply の local fix guard を bypass する")
    update_parser.add_argument("--allow-dirty", action="store_true", help="apply に dirty 作業ツリーの続行を許可する")
    update_parser.add_argument("--dry-run", action="store_true", help="apply せず各チャンネルで check のみ実行する")
    update_parser.add_argument("--no-commit", action="store_true", help="apply に --commit を渡さない")
    update_parser.add_argument(
        "--no-accept-hooks", dest="accept_hooks", action="store_false", help="hook 追加への同意を渡さない"
    )
    update_parser.add_argument("--json", action="store_true", help="チャンネル別結果と summary を JSON で出力する")
    update_parser.set_defaults(func=_run_update, accept_hooks=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        build_parser,
        lambda args: args.func(args),
        argv,
        failure_message="channel registry を読み込めません",
        failure_exit_code=EXIT_REGISTRY_ERROR,
    )


if __name__ == "__main__":
    raise SystemExit(main())
