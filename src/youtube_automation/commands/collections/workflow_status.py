"""Generate and open the read-only /wf-status HTML snapshot."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from youtube_automation.application.workflow_status import build_workflow_status_snapshot
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import BrowserOpenError, DocumentRenderError
from youtube_automation.domains.documents.workflow_status_rendering import (
    render_workflow_status,
    validate_workflow_status_html,
)
from youtube_automation.infrastructure.browser import open_local_file
from youtube_automation.infrastructure.documents.publishing import publish_html_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="制作状況のread-only HTML snapshotを生成してブラウザで開く")
    parser.add_argument("--target", type=Path, default=Path.cwd(), help="チャンネルディレクトリ（default: cwd）")
    return parser


def run(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    destination = target / "tmp" / "reviews" / "workflow-status.html"
    try:
        snapshot = build_workflow_status_snapshot(target, now=datetime.now(UTC))
        html = render_workflow_status(snapshot)
        publish_html_snapshot(destination, html, validate_workflow_status_html)
    except (DocumentRenderError, OSError, UnicodeError) as exc:
        print(f"snapshot path: {destination}", file=sys.stderr)
        raise DocumentRenderError(f"workflow status HTML生成失敗: {destination}: {exc}") from exc
    print(destination)
    if not open_local_file(destination.resolve()):
        print(f"snapshot path: {destination.resolve()}", file=sys.stderr)
        raise BrowserOpenError(f"ブラウザで開けませんでした。snapshot: {destination.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="workflow status の表示に失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
