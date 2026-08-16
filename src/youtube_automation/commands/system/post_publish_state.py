"""Evaluate or atomically mark the canonical post-publish step state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.domains.post_publish import STEPS, evaluate, mark_complete


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--step", choices=STEPS, required=True)
    parser.add_argument("--mark-complete", action="store_true")
    return parser


def run(args: argparse.Namespace) -> int:
    root = args.channel_dir.resolve()
    collection = args.collection if args.collection.is_absolute() else root / args.collection
    decision = (
        mark_complete(root, collection, args.step) if args.mark_complete else evaluate(root, collection, args.step)
    )
    print(
        json.dumps(
            {
                "step": args.step,
                "decision": decision.status,
                "reason": decision.reason,
                "video_id": decision.video_id,
                "history_file": "post_publish_history.json",
                "completed_steps": decision.completed_steps,
            },
            ensure_ascii=False,
        )
    )
    return 0 if decision.status == "skip" or args.mark_complete else 10


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="post-publish state error")


if __name__ == "__main__":
    raise SystemExit(main())
