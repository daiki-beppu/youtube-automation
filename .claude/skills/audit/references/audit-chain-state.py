#!/usr/bin/env python3
"""Return the resumable state of one audit chain step as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_BLOCKED = 20
EXIT_ERROR = 2
STEPS = ("alignment", "video", "metadata", "value-loop")


class StateResult(TypedDict):
    step: str
    decision: str
    reason: str
    artifacts: list[str]


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _result(*, step: str, decision: str, reason: str, artifacts: list[str]) -> StateResult:
    return {"step": step, "decision": decision, "reason": reason, "artifacts": artifacts}


def _published_videos(root: Path) -> list[str]:
    video_ids: list[str] = []
    for state_path in sorted((root / "collections" / "live").glob("*/workflow-state.json")):
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            relative = _relative(state_path, root)
            raise ValueError(f"{relative} の JSON が不正です: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{_relative(state_path, root)} は JSON object である必要があります")
        upload = payload.get("upload")
        if upload is None:
            continue
        if not isinstance(upload, dict):
            raise ValueError(f"{_relative(state_path, root)}::upload は object である必要があります")
        video_id = upload.get("video_id")
        if isinstance(video_id, str) and video_id.strip():
            video_ids.append(video_id.strip())
    return video_ids


def _video_outputs(root: Path, video_ids: list[str]) -> list[str]:
    paths: list[Path] = []
    for video_id in video_ids:
        matches = sorted((root / "data" / "video_analysis").glob(f"*/{video_id}.json"))
        if not matches:
            return []
        paths.append(matches[0])
    reports = sorted((root / "reports" / "video_analysis").glob("*.json"))
    if not reports or not reports[0].with_suffix(".html").is_file():
        return []
    read_published_json_document(reports[0], RepositorySchema.AUDIT_REPORT)
    paths.append(reports[0])
    paths.append(reports[0].with_suffix(".html"))
    return [_relative(path, root) for path in paths]


def evaluate(root: Path, step: str) -> tuple[int, StateResult]:
    root = root.resolve()
    if step == "alignment":
        report = root / "docs" / "plans" / "alignment-audit.json"
        html = report.with_suffix(".html")
        if report.is_file() and html.is_file():
            read_published_json_document(report, RepositorySchema.AUDIT_REPORT)
            return EXIT_SKIP, _result(
                step=step,
                decision="skip",
                reason="alignment_report_exists",
                artifacts=[_relative(report, root), _relative(html, root)],
            )
        return EXIT_RUN, _result(
            step=step,
            decision="run",
            reason="alignment_report_missing",
            artifacts=[],
        )

    video_ids = _published_videos(root)
    if not video_ids:
        return EXIT_BLOCKED, _result(
            step=step,
            decision="blocked",
            reason="published_video_missing",
            artifacts=[],
        )

    video_outputs = _video_outputs(root, video_ids)
    if step == "video":
        if video_outputs:
            return EXIT_SKIP, _result(
                step=step,
                decision="skip",
                reason="video_analysis_exists",
                artifacts=video_outputs,
            )
        return EXIT_RUN, _result(
            step=step,
            decision="run",
            reason="video_analysis_missing",
            artifacts=[],
        )

    if step == "metadata":
        return EXIT_RUN, _result(
            step=step,
            decision="run",
            reason="metadata_audit_is_not_persisted",
            artifacts=[],
        )

    alignment_report = root / "docs" / "plans" / "alignment-audit.json"
    alignment_html = alignment_report.with_suffix(".html")
    if not alignment_report.is_file() or not alignment_html.is_file():
        return EXIT_BLOCKED, _result(
            step=step,
            decision="blocked",
            reason="alignment_report_missing",
            artifacts=[],
        )
    if not video_outputs:
        return EXIT_BLOCKED, _result(
            step=step,
            decision="blocked",
            reason="video_analysis_missing",
            artifacts=[_relative(alignment_report, root)],
        )
    read_published_json_document(alignment_report, RepositorySchema.AUDIT_REPORT)
    return EXIT_RUN, _result(
        step=step,
        decision="run",
        reason="value_loop_audit_is_not_persisted",
        artifacts=[_relative(alignment_report, root), _relative(alignment_html, root), *video_outputs],
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--step", choices=STEPS, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, result = evaluate(args.channel_dir, args.step)
    except (AutomationError, OSError, ValueError) as exc:
        code = EXIT_ERROR
        result = _result(step=args.step, decision="error", reason=str(exc), artifacts=[])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
