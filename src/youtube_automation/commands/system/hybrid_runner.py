"""Canonical CLI for the platform-neutral hybrid sandwich runner."""

from __future__ import annotations

import argparse
from pathlib import Path

from youtube_automation.application.hybrid_runner import SandwichRequest, run_sandwich
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.media_store.local import LocalMediaStore
from youtube_automation.infrastructure.media_store.r2 import R2MediaStore, R2MediaStoreConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--channel-slug", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--collection-dir", required=True)
    parser.add_argument("--agent", choices=("claude", "codex"), default="claude")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--commit-message", default="chore(hybrid): update workflow state")
    parser.add_argument("--input-handoff")
    parser.add_argument("--input-destination")
    parser.add_argument("--output-handoff")
    parser.add_argument("--output-root")
    parser.add_argument("--output-file", action="append", default=[])
    parser.add_argument("--media-store", choices=("r2", "local"), default="r2")
    parser.add_argument("--local-store-root", type=Path)
    return parser


def run(args: argparse.Namespace) -> int:
    if args.media_store == "local":
        if args.local_store_root is None:
            raise ConfigError("--media-store local には --local-store-root が必要です")
        store = LocalMediaStore(args.local_store_root)
    else:
        if args.local_store_root is not None:
            raise ConfigError("--local-store-root は local MediaStore 専用です")
        store = R2MediaStore(R2MediaStoreConfig.from_environment())
    request = SandwichRequest(
        channel_dir=args.channel_dir.resolve(),
        collection_dir=args.collection_dir,
        channel=args.channel_slug,
        collection=args.collection,
        agent=args.agent,
        prompt=args.prompt,
        commit_message=args.commit_message,
        input_handoff=args.input_handoff,
        input_destination=args.input_destination,
        output_handoff=args.output_handoff,
        output_root=args.output_root,
        output_files=tuple(args.output_file),
    )
    run_sandwich(request, store)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="sandwich runner error")


if __name__ == "__main__":
    raise SystemExit(main())
