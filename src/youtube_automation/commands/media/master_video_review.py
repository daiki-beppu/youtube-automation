"""Review a generated preview or full master video."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from youtube_automation.application.master_video_review import VideoReviewPresentation, review_master_video
from youtube_automation.commands._shared.cli_harness import run_cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="preview/full master動画を安全な固定HTMLで確認する")
    parser.add_argument("--collection", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=("preview", "full"))
    parser.add_argument("--background-route", required=True)
    parser.add_argument("--effect", required=True)
    parser.add_argument("--overlays", required=True)
    parser.add_argument("--full-output-outlook", required=True)
    parser.add_argument("--automatic", action="store_true", help="HTML/brokerを省略してprobe後に確定")
    parser.add_argument("--transport", choices=("web", "terminal"), default="web")
    parser.add_argument("--candidate-id", help="terminal fallbackで返されたkind付き候補ID")
    return parser


def run(args: argparse.Namespace) -> int:
    result = review_master_video(
        args.collection.resolve(),
        kind=args.kind,
        presentation=VideoReviewPresentation(
            args.background_route,
            args.effect,
            args.overlays,
            args.full_output_outlook,
        ),
        automatic=args.automatic,
        transport=args.transport,
        candidate_id=args.candidate_id,
        now=datetime.now(UTC),
        timeout=300,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "artifact_digest": result.artifact_digest,
                "candidate_id": result.candidate_id,
                "candidates": list(result.candidates),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result.status == "terminal_required":
        print("候補を確認後、--candidate-id <kind:filename>を指定してください", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="master video reviewに失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
