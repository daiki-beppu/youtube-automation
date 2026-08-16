"""Review and finalize one master audio candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from youtube_automation.application.master_audio_review import review_and_finalize_master_audio
from youtube_automation.commands._shared.cli_harness import run_cli


def _bool_arg(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("true または false を指定してください")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="master audio候補を再生・比較し、検証済みIDだけを確定する")
    parser.add_argument("--collection", required=True, type=Path)
    parser.add_argument("--skip-manual-mastering", required=True, type=_bool_arg)
    parser.add_argument("--skip-audio-approval", required=True, type=_bool_arg)
    parser.add_argument("--transport", choices=("web", "terminal"), default="web")
    parser.add_argument("--candidate-id", help="terminal fallbackまたは複数候補skip時のsource付きID")
    parser.add_argument("--main-repo-root", type=Path, help="worktree比較用main repository root")
    return parser


def run(args: argparse.Namespace) -> int:
    result = review_and_finalize_master_audio(
        args.collection.resolve(),
        skip_manual_mastering=args.skip_manual_mastering,
        skip_audio_approval=args.skip_audio_approval,
        transport=args.transport,
        candidate_id=args.candidate_id,
        main_repo_root=args.main_repo_root.resolve() if args.main_repo_root is not None else None,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "candidate_id": result.candidate_id,
                "candidates": list(result.candidates),
                "artifact_digest": result.artifact_digest,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result.status == "terminal_required":
        print("候補を確認後、--candidate-id <source:filename>を指定してください", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="master audio reviewに失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
