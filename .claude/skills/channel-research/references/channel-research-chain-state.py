#!/usr/bin/env python3
"""Return the resumable state of one channel-research chain step as JSON."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import NotRequired, TypedDict

from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, DocumentRenderError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_BLOCKED = 20
EXIT_ERROR = 2


class StateResult(TypedDict):
    step: str
    decision: str
    reason: str
    freshness_days: float
    freshness_source: str
    artifacts: list[str]
    branch: NotRequired[str]


def _freshness(root: Path) -> tuple[float, str]:
    config = load_skill_config("benchmark", use_cache=False, channel_dir=root)
    value = config.get("freshness_days", 3)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"benchmark.freshness_days は正の数である必要があります: {value!r}")
    override = root / "config" / "skills" / "benchmark.yaml"
    source = (
        override.relative_to(root).as_posix()
        if override.is_file()
        else ".claude/skills/channel-research/config.default.yaml"
    )
    return float(value), source


def _validated_report(path: Path, report_type: str) -> list[Path]:
    if not path.is_file() or not path.with_suffix(".html").is_file():
        return []
    document = read_published_json_document(path, RepositorySchema.CHANNEL_RESEARCH_REPORT)
    if not isinstance(document, dict) or document.get("report_type") != report_type:
        raise DocumentRenderError(f"channel research report_type が一致しません: {path}")
    return [path, path.with_suffix(".html")]


def _benchmark_reports(root: Path) -> list[Path]:
    return _validated_report(root / "docs" / "benchmarks" / "benchmark-report.json", "benchmark")


def _result(
    step: str,
    decision: str,
    reason: str,
    freshness_days: float,
    source: str,
    artifacts: list[Path],
    root: Path,
    branch: str | None = None,
) -> StateResult:
    result: StateResult = {
        "step": step,
        "decision": decision,
        "reason": reason,
        "freshness_days": freshness_days,
        "freshness_source": source,
        "artifacts": sorted(path.relative_to(root).as_posix() for path in artifacts),
    }
    if branch is not None:
        result["branch"] = branch
    return result


def _evaluate_market(
    root: Path,
    data: list[Path],
    reports: list[Path],
    comments: list[Path],
) -> tuple[int, StateResult]:
    inputs = [*data, *reports, *comments]
    if not inputs:
        saved_reports = [
            artifact
            for report in (root / "docs" / "research").glob("market-*.json")
            for artifact in _validated_report(report, "market")
        ]
        if saved_reports:
            return EXIT_SKIP, _result(
                "market",
                "skip",
                "market_comparison_report_exists",
                0.0,
                "",
                saved_reports,
                root,
                "market-comparison",
            )
        return EXIT_RUN, _result(
            "market",
            "run",
            "market_comparison_required",
            0.0,
            "",
            [],
            root,
            "market-comparison",
        )

    if not data or not reports or not comments:
        return EXIT_BLOCKED, _result(
            "market",
            "blocked",
            "collected_analysis_inputs_incomplete",
            0.0,
            "",
            inputs,
            root,
            "collected-analysis",
        )

    outputs = _validated_report(root / "docs" / "channel-research.json", "market")
    if not outputs:
        return EXIT_RUN, _result(
            "market",
            "run",
            "collected_analysis_outputs_missing",
            0.0,
            "",
            inputs,
            root,
            "collected-analysis",
        )
    return EXIT_SKIP, _result(
        "market",
        "skip",
        "collected_analysis_outputs_complete",
        0.0,
        "",
        [*inputs, *outputs],
        root,
        "collected-analysis",
    )


def _evaluate_voice(root: Path, data: list[Path], reports: list[Path]) -> tuple[int, StateResult]:
    discovery_markdown = list((root / "research").glob("*-discovery.md"))
    discovery_csv = list((root / "research").glob("*-discovery.csv"))
    markdown_stems = {path.with_suffix("") for path in discovery_markdown}
    csv_stems = {path.with_suffix("") for path in discovery_csv}
    prerequisites = [*data, *reports, *discovery_markdown, *discovery_csv]
    if not data or not reports or not discovery_markdown or markdown_stems != csv_stems:
        return EXIT_BLOCKED, _result(
            "voice",
            "blocked",
            "voice_prerequisites_missing",
            0.0,
            "",
            prerequisites,
            root,
        )

    comments = list((root / "data").glob("comments_*.json"))
    report = root / "docs" / "plans" / "viewer-voice-analysis.json"
    report_pair = _validated_report(report, "viewer_voice")
    outputs = [*comments, *report_pair]
    if not outputs:
        return EXIT_RUN, _result("voice", "run", "voice_outputs_missing", 0.0, "", prerequisites, root)
    if not comments or not report_pair:
        return EXIT_RUN, _result(
            "voice",
            "run",
            "voice_outputs_incomplete",
            0.0,
            "",
            [*prerequisites, *outputs],
            root,
        )
    return EXIT_SKIP, _result(
        "voice",
        "skip",
        "voice_outputs_complete",
        0.0,
        "",
        [*prerequisites, *outputs],
        root,
    )


def evaluate(root: Path, step: str, now: float) -> tuple[int, StateResult]:
    root = root.resolve()
    freshness_days, source = (0.0, "") if step in {"market", "voice"} else _freshness(root)
    analytics = root / "config" / "channel" / "analytics.json"
    if step == "benchmark" and not analytics.is_file():
        return EXIT_BLOCKED, {
            "step": step,
            "decision": "blocked",
            "reason": "config_channel_analytics_missing",
            "freshness_days": freshness_days,
            "freshness_source": source,
            "artifacts": [],
        }

    data = list((root / "data").glob("benchmark_*.json"))
    reports = _benchmark_reports(root)
    if step == "voice":
        return _evaluate_voice(root, data, reports)
    if step == "market":
        comments = list((root / "data").glob("comments_*.json"))
        return _evaluate_market(root, data, reports, comments)

    if step == "discover":
        if not reports:
            return EXIT_BLOCKED, _result(
                step,
                "blocked",
                "benchmark_reports_missing",
                freshness_days,
                source,
                [],
                root,
            )
        markdown = list((root / "research").glob("*-discovery.md"))
        csv = list((root / "research").glob("*-discovery.csv"))
        artifacts = [*markdown, *csv]
        if not artifacts:
            return EXIT_RUN, _result(
                step,
                "run",
                "discover_outputs_missing",
                freshness_days,
                source,
                artifacts,
                root,
            )
        markdown_stems = {path.with_suffix("") for path in markdown}
        csv_stems = {path.with_suffix("") for path in csv}
        if markdown_stems != csv_stems:
            return EXIT_RUN, _result(
                step,
                "run",
                "discover_output_pair_incomplete",
                freshness_days,
                source,
                artifacts,
                root,
            )
        return EXIT_SKIP, _result(
            step,
            "skip",
            "discover_output_pair_complete",
            freshness_days,
            source,
            artifacts,
            root,
        )

    artifacts = sorted(path.relative_to(root).as_posix() for path in (*data, *reports))
    if not data or not reports:
        return EXIT_RUN, {
            "step": step,
            "decision": "run",
            "reason": "benchmark_outputs_missing",
            "freshness_days": freshness_days,
            "freshness_source": source,
            "artifacts": artifacts,
        }

    newest_data = max(path.stat().st_mtime for path in data)
    oldest_report = min(path.stat().st_mtime for path in reports)
    if now - min(newest_data, oldest_report) >= freshness_days * 86400:
        return EXIT_RUN, {
            "step": step,
            "decision": "run",
            "reason": "benchmark_outputs_stale",
            "freshness_days": freshness_days,
            "freshness_source": source,
            "artifacts": artifacts,
        }
    return EXIT_SKIP, {
        "step": step,
        "decision": "skip",
        "reason": "benchmark_outputs_fresh",
        "freshness_days": freshness_days,
        "freshness_source": source,
        "artifacts": artifacts,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--step", choices=("benchmark", "discover", "voice", "market"), required=True)
    parser.add_argument("--now", type=float, default=None)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, result = evaluate(args.channel_dir, args.step, time.time() if args.now is None else args.now)
    except (ConfigError, DocumentRenderError, OSError, ValueError) as exc:
        code = EXIT_ERROR
        result = {
            "step": args.step,
            "decision": "error",
            "reason": str(exc),
            "freshness_days": 0.0,
            "freshness_source": "",
            "artifacts": [],
        }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
