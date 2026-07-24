#!/usr/bin/env python3
"""Return the resumable state of one analytics chain step as JSON."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.skill_config import load_skill_config

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_BLOCKED = 20
EXIT_ERROR = 2
_STEPS = ("collect", "analyze", "report")


@dataclass(frozen=True)
class Artifact:
    path: Path
    mtime: float


class ArtifactPayload(TypedDict):
    path: str
    mtime: float
    age_minutes: float


class StateResult(TypedDict):
    step: str
    decision: str
    reason: str
    freshness_minutes: float
    freshness_source: str
    artifacts: list[ArtifactPayload]


class ErrorResult(TypedDict):
    step: str
    decision: str
    reason: str
    artifacts: list[ArtifactPayload]


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _artifact_json(artifact: Artifact, root: Path, now: float) -> ArtifactPayload:
    return {
        "path": _relative(artifact.path, root),
        "mtime": artifact.mtime,
        "age_minutes": round(max(0.0, now - artifact.mtime) / 60, 3),
    }


def _latest(paths: list[Path]) -> Artifact | None:
    existing = [Artifact(path, path.stat().st_mtime) for path in paths if path.is_file()]
    return max(existing, key=lambda artifact: artifact.mtime, default=None)


def _latest_analysis_pair(root: Path) -> tuple[Artifact, Artifact] | None:
    reports = root / "reports"
    pairs: list[tuple[Artifact, Artifact]] = []
    for md_path in reports.glob("analysis_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].md"):
        json_path = md_path.with_suffix(".json")
        if json_path.is_file():
            pairs.append(
                (
                    Artifact(md_path, md_path.stat().st_mtime),
                    Artifact(json_path, json_path.stat().st_mtime),
                )
            )
    return max(pairs, key=lambda pair: min(pair[0].mtime, pair[1].mtime), default=None)


def _freshness(root: Path) -> tuple[float, str]:
    config = load_skill_config("analytics-collect", use_cache=False, channel_dir=root)
    value = config.get("freshness_minutes", 30)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"analytics-collect.freshness_minutes は正の数である必要があります: {value!r}")
    override = root / "config" / "skills" / "analytics-collect.yaml"
    source = _relative(override, root) if override.is_file() else ".claude/skills/analytics-collect/config.default.yaml"
    return float(value), source


def _result(
    *,
    step: str,
    decision: str,
    reason: str,
    freshness_minutes: float,
    freshness_source: str,
    artifacts: list[ArtifactPayload],
) -> StateResult:
    return {
        "step": step,
        "decision": decision,
        "reason": reason,
        "freshness_minutes": freshness_minutes,
        "freshness_source": freshness_source,
        "artifacts": artifacts,
    }


def evaluate(root: Path, step: str, now: float) -> tuple[int, StateResult]:
    root = root.resolve()
    freshness_minutes, freshness_source = _freshness(root)
    freshness_seconds = freshness_minutes * 60
    analytics = _latest(list((root / "data").glob("analytics_data_*.json")))

    if step == "collect":
        if analytics is None:
            return EXIT_RUN, _result(
                step=step,
                decision="run",
                reason="analytics_data_missing",
                freshness_minutes=freshness_minutes,
                freshness_source=freshness_source,
                artifacts=[],
            )
        artifact = _artifact_json(analytics, root, now)
        if now - analytics.mtime >= freshness_seconds:
            return EXIT_RUN, _result(
                step=step,
                decision="run",
                reason="analytics_data_stale",
                freshness_minutes=freshness_minutes,
                freshness_source=freshness_source,
                artifacts=[artifact],
            )
        return EXIT_SKIP, _result(
            step=step,
            decision="skip",
            reason="analytics_data_fresh",
            freshness_minutes=freshness_minutes,
            freshness_source=freshness_source,
            artifacts=[artifact],
        )

    if analytics is None:
        return EXIT_BLOCKED, _result(
            step=step,
            decision="blocked",
            reason="analytics_data_missing",
            freshness_minutes=freshness_minutes,
            freshness_source=freshness_source,
            artifacts=[],
        )
    analytics_json = _artifact_json(analytics, root, now)
    if now - analytics.mtime >= freshness_seconds:
        return EXIT_BLOCKED, _result(
            step=step,
            decision="blocked",
            reason="analytics_data_stale_run_collect_first",
            freshness_minutes=freshness_minutes,
            freshness_source=freshness_source,
            artifacts=[analytics_json],
        )

    pair = _latest_analysis_pair(root)
    if pair is None:
        decision = "run" if step == "analyze" else "blocked"
        code = EXIT_RUN if step == "analyze" else EXIT_BLOCKED
        return code, _result(
            step=step,
            decision=decision,
            reason="analysis_pair_missing",
            freshness_minutes=freshness_minutes,
            freshness_source=freshness_source,
            artifacts=[analytics_json],
        )

    md_artifact, json_artifact = pair
    artifacts = [
        analytics_json,
        _artifact_json(md_artifact, root, now),
        _artifact_json(json_artifact, root, now),
    ]
    pair_mtime = min(md_artifact.mtime, json_artifact.mtime)
    if pair_mtime < analytics.mtime:
        decision = "run" if step == "analyze" else "blocked"
        code = EXIT_RUN if step == "analyze" else EXIT_BLOCKED
        return code, _result(
            step=step,
            decision=decision,
            reason="analysis_pair_older_than_analytics_data",
            freshness_minutes=freshness_minutes,
            freshness_source=freshness_source,
            artifacts=artifacts,
        )
    if now - pair_mtime >= freshness_seconds:
        decision = "run" if step == "analyze" else "blocked"
        code = EXIT_RUN if step == "analyze" else EXIT_BLOCKED
        return code, _result(
            step=step,
            decision=decision,
            reason="analysis_pair_stale",
            freshness_minutes=freshness_minutes,
            freshness_source=freshness_source,
            artifacts=artifacts,
        )
    if step == "analyze":
        return EXIT_SKIP, _result(
            step=step,
            decision="skip",
            reason="analysis_pair_fresh",
            freshness_minutes=freshness_minutes,
            freshness_source=freshness_source,
            artifacts=artifacts,
        )
    return EXIT_RUN, _result(
        step=step,
        decision="run",
        reason="latest_report_ready_for_display",
        freshness_minutes=freshness_minutes,
        freshness_source=freshness_source,
        artifacts=artifacts,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--step", choices=_STEPS, required=True)
    parser.add_argument("--now", type=float, default=None, help="Unix timestamp override for deterministic checks")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result: StateResult | ErrorResult
    try:
        code, state_result = evaluate(args.channel_dir, args.step, time.time() if args.now is None else args.now)
        result = state_result
    except (ConfigError, OSError, ValueError) as exc:
        code = EXIT_ERROR
        result = {"step": args.step, "decision": "error", "reason": str(exc), "artifacts": []}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
