"""Product-neutral CLI for review display and loopback candidate selection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from youtube_automation.application.documents.review import run_review
from youtube_automation.commands._shared.cli_harness import run_cli


def _timeout(value: str) -> float:
    timeout = float(value)
    if not 1 <= timeout <= 3600:
        raise argparse.ArgumentTypeError("timeoutは1〜3600秒で指定してください")
    return timeout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="成果物review HTMLを表示し、安全な候補IDだけを受け取る")
    parser.add_argument("--collection", type=Path, required=True, help="対象collection directory")
    parser.add_argument(
        "--artifact",
        required=True,
        choices=("plan", "music-prompt", "thumbnail", "audio", "video"),
        help="固定resolverで解決するreview対象",
    )
    parser.add_argument("--select", action="store_true", help="single-use loopback brokerで候補を1件選ぶ")
    parser.add_argument("--automatic", action="store_true", help="自動承認経路としてHTML生成・browser表示を省略")
    parser.add_argument(
        "--transport",
        choices=("web", "terminal"),
        default="web",
        help="terminalは会話選択への明示fallback（Web失敗から自動切替しない）",
    )
    parser.add_argument("--timeout", type=_timeout, default=300.0, help="Web選択待機秒（1〜3600）")
    return parser


def run(args: argparse.Namespace) -> int:
    result = run_review(
        args.collection,
        args.artifact,
        automatic=args.automatic,
        selection=args.select,
        transport=args.transport,
        timeout=args.timeout,
    )
    payload: dict[str, object] = {"status": result.status}
    if result.artifact_digest is not None:
        payload["artifact_digest"] = result.artifact_digest
    if result.candidate_id is not None:
        payload["candidate_id"] = result.candidate_id
    if result.candidates:
        payload["candidates"] = list(result.candidates)
    if result.html_path is not None:
        payload["html_path"] = str(result.html_path)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if result.status == "terminal_required":
        print(
            "Web reviewを使わずterminal fallbackを明示しました。表示候補から会話で選択し、"
            "選択後もartifact digestと候補実体を再検証してください。",
            file=sys.stderr,
        )
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="成果物reviewに失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
