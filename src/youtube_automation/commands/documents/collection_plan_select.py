"""Finalize a collection plan through the shared review lifecycle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from youtube_automation.application.documents.collection_plan import finalize_collection_plan_selection
from youtube_automation.application.documents.review import ReviewResult, run_review
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import ValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="永続plan proposal pairを表示し、検証済みproposal IDだけを企画ownerへ渡す"
    )
    parser.add_argument("--collection", type=Path, required=True, help="対象collection directory")
    parser.add_argument(
        "--transport",
        choices=("web", "terminal"),
        default="web",
        help="terminalは会話選択への明示fallback",
    )
    parser.add_argument("--candidate-id", help="terminal fallbackで会話確認済みのproposal ID")
    parser.add_argument("--automatic", action="store_true", help="HTML/brokerを省略し推奨順1位を自動確定")
    return parser


def run(args: argparse.Namespace) -> int:
    collection = args.collection.resolve()
    if args.automatic and (args.transport != "web" or args.candidate_id is not None):
        raise ValidationError("--automaticは--transport terminal / --candidate-idと併用できません")
    if args.transport == "web" and args.candidate_id is not None:
        raise ValidationError("--candidate-idは--transport terminal専用です")

    if args.transport == "web" and not args.automatic:
        result = run_review(collection, "plan", selection=True, transport="web")
        proposal_id, digest = _selected_result(result)
        source = "web"
    else:
        result = run_review(collection, "plan", transport="terminal")
        digest = _required_digest(result)
        if not args.automatic and args.candidate_id is None:
            print(
                json.dumps(
                    {"status": "terminal_required", "candidates": list(result.candidates), "artifact_digest": digest},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            print("候補を会話で確認後、--candidate-id <proposal_id>を明示して再実行してください", file=sys.stderr)
            return 2
        proposal_id = result.candidates[0] if args.automatic else args.candidate_id
        if proposal_id is None or proposal_id not in result.candidates:
            raise ValidationError(f"proposal IDがreview manifest allowlistにありません: {proposal_id}")
        source = "automatic" if args.automatic else "terminal"

    finalize_collection_plan_selection(
        collection / "20-documentation" / "plan_proposals.json",
        collection / "workflow-state.json",
        proposal_id=proposal_id,
        source=source,
        expected_artifact_digest=digest,
    )
    print(json.dumps({"status": "selected", "proposal_id": proposal_id, "source": source}, ensure_ascii=False))
    return 0


def _selected_result(result: ReviewResult) -> tuple[str, str]:
    if result.status != "selected" or result.candidate_id is None:
        raise ValidationError("Web reviewからproposal IDを取得できません")
    return result.candidate_id, _required_digest(result)


def _required_digest(result: ReviewResult) -> str:
    if result.artifact_digest is None or (not result.candidates and result.status == "terminal_required"):
        raise ValidationError("review manifestにproposal ID / artifact digestがありません")
    return result.artifact_digest


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="企画reviewに失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
