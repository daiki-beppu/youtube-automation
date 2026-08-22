"""Finalize a structured music prompt through the shared review lifecycle."""

from __future__ import annotations

import argparse
from pathlib import Path

from youtube_automation.application.documents.review import MusicPromptReviewSource
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.commands.documents.select import run_document_select


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-music-prompt-select", description="永続music prompt pairを表示し、検証済み承認だけをstate ownerへ渡す"
    )
    parser.add_argument("--collection", type=Path, required=True, help="対象collection directory")
    parser.add_argument("--transport", choices=("web", "terminal"), default="web")
    parser.add_argument("--candidate-id", choices=("approve", "reject"), help="terminal fallbackの選択ID")
    parser.add_argument("--automatic", action="store_true", help="HTML/brokerを省略して承認を確定")
    return parser


def run(args: argparse.Namespace) -> int:
    collection = args.collection.resolve()
    return run_document_select(
        args,
        lambda source: MusicPromptReviewSource(collection, source),
        success_payload=lambda candidate, source: {
            "status": "approved" if candidate == "approve" else "rejected",
            "source": source,
        },
        terminal_hint="会話で確認後、--candidate-id approve|rejectを明示してください",
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="music prompt reviewに失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
