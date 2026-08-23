"""Finalize a collection plan through the shared review lifecycle."""

from __future__ import annotations

import argparse
from pathlib import Path

from youtube_automation.application.documents.review import CollectionPlanReviewSource
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.commands.documents.select import run_document_select


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="永続plan proposal pairを表示し、検証済みproposal IDだけを企画ownerへ渡す"
    )
    parser.add_argument("--collection", type=Path, required=True, help="対象collection directory")
    parser.add_argument(
        "--transport", choices=("web", "terminal"), default="web", help="terminalは会話選択への明示fallback"
    )
    parser.add_argument("--candidate-id", help="terminal fallbackで会話確認済みのproposal ID")
    parser.add_argument("--automatic", action="store_true", help="HTML/brokerを省略し推奨順1位を自動確定")
    return parser


def run(args: argparse.Namespace) -> int:
    collection = args.collection.resolve()
    return run_document_select(
        args,
        lambda source: CollectionPlanReviewSource(collection, source),
        success_payload=lambda candidate, source: {"status": "selected", "proposal_id": candidate, "source": source},
        terminal_hint="候補を会話で確認後、--candidate-id <proposal_id>を明示して再実行してください",
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="企画reviewに失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
