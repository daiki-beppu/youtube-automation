"""Finalize a structured music prompt through the shared review lifecycle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from youtube_automation.application.documents.music_prompt import (
    finalize_music_prompt_review,
    music_prompt_artifact_digest,
)
from youtube_automation.application.documents.review import ReviewResult, run_review
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import ValidationError

_FILENAMES = ("suno-prompts.json", "lyria-prompt.json", "minimax-prompt.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-music-prompt-select",
        description="永続music prompt pairを表示し、検証済み承認だけをstate ownerへ渡す",
    )
    parser.add_argument("--collection", type=Path, required=True, help="対象collection directory")
    parser.add_argument("--transport", choices=("web", "terminal"), default="web")
    parser.add_argument("--candidate-id", choices=("approve", "reject"), help="terminal fallbackの選択ID")
    parser.add_argument("--automatic", action="store_true", help="HTML/brokerを省略して承認を確定")
    return parser


def run(args: argparse.Namespace) -> int:
    collection = args.collection.resolve()
    if args.automatic and (args.transport != "web" or args.candidate_id is not None):
        raise ValidationError("--automaticは--transport terminal / --candidate-idと併用できません")
    if args.transport == "web" and args.candidate_id is not None:
        raise ValidationError("--candidate-idは--transport terminal専用です")

    prompt_path = _prompt_path(collection)
    if args.automatic:
        decision = "approve"
        digest = music_prompt_artifact_digest(prompt_path)
        source = "automatic"
    elif args.transport == "web":
        result = run_review(collection, "music-prompt", selection=True, transport="web")
        decision, digest = _selected_result(result)
        source = "web"
    else:
        result = run_review(collection, "music-prompt", transport="terminal")
        digest = _required_digest(result)
        if not args.automatic and args.candidate_id is None:
            print(
                json.dumps(
                    {"status": "terminal_required", "candidates": list(result.candidates), "artifact_digest": digest},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            print("会話で確認後、--candidate-id approve|rejectを明示してください", file=sys.stderr)
            return 2
        decision = args.candidate_id
        if decision is None or decision not in result.candidates:
            raise ValidationError(f"decisionがreview manifest allowlistにありません: {decision}")
        source = "terminal"

    finalize_music_prompt_review(
        prompt_path,
        collection / "workflow-state.json",
        decision=decision,
        source=source,
        expected_artifact_digest=digest,
    )
    print(json.dumps({"status": "approved" if decision == "approve" else "rejected", "source": source}))
    return 0


def _prompt_path(collection: Path) -> Path:
    paths = [collection / "20-documentation" / name for name in _FILENAMES]
    existing = [path for path in paths if path.is_file()]
    if len(existing) != 1:
        raise ValidationError("music promptの永続JSON+HTML pairを一意に解決できません")
    return existing[0]


def _selected_result(result: ReviewResult) -> tuple[str, str]:
    if result.status != "selected" or result.candidate_id not in {"approve", "reject"}:
        raise ValidationError("Web reviewから承認decisionを取得できません")
    return result.candidate_id, _required_digest(result)


def _required_digest(result: ReviewResult) -> str:
    if result.artifact_digest is None:
        raise ValidationError("review manifestにartifact digestがありません")
    return result.artifact_digest


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="music prompt reviewに失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
