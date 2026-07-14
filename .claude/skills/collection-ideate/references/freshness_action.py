#!/usr/bin/env python3
"""Estimate stale-analysis cost and resolve the user's requested action."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Decision:
    action: str
    estimate_usd: float | None
    report_count: int
    reason: str | None
    outcome: str
    choices: list[str]
    skills: list[str]


@dataclass(frozen=True)
class WorkflowStep:
    outcome: str
    skill: str | None = None
    message: str | None = None


def next_workflow_step(
    decision: Decision,
    skill_results: list[str],
    revalidation: str | None,
) -> WorkflowStep:
    """Advance the production stale workflow after the decision stage."""
    if decision.outcome != "execute":
        return WorkflowStep(decision.outcome)
    if "failure" in skill_results:
        return WorkflowStep("error", message="Skill 呼び出し失敗。再開手順を案内して停止")
    if len(skill_results) < len(decision.skills):
        return WorkflowStep("tool_call", skill=decision.skills[len(skill_results)])
    if revalidation is None:
        return WorkflowStep("revalidate")
    if revalidation == "failure":
        return WorkflowStep("error", message="成果物の再検証失敗。企画生成へ進まず停止")
    return WorkflowStep("continue")


def _estimate(reports_dir: Path, count: int, usd_per_kib: float) -> tuple[float | None, int, str | None]:
    reports = sorted(reports_dir.glob("analysis_*.md"), reverse=True)[:count]
    if not reports:
        return None, 0, "分析 report がないため見積不能（安全側上限）"
    sizes = [report.stat().st_size for report in reports]
    if any(size == 0 for size in sizes):
        return None, len(reports), "空の分析 report があるため見積不能（安全側上限）"
    # The report size is the explicitly configured conservative proxy; it is
    # not presented as observed provider billing.
    average_kib = sum(math.ceil(size / 1024) for size in sizes) / len(sizes)
    return average_kib * usd_per_kib, len(reports), None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--action", choices=("ask", "auto", "manual"), default="ask")
    parser.add_argument("--choice", choices=("auto", "manual", "abort"))
    parser.add_argument("--stale-kind", choices=("relative", "absolute"), required=True)
    parser.add_argument("--recent-reports", type=int, default=3)
    parser.add_argument("--usd-per-kib", type=float, required=True)
    parser.add_argument("--auto-run-max-cost-usd", type=float)
    parser.add_argument("--skill-result", action="append", choices=("success", "failure"), default=[])
    parser.add_argument("--revalidation", choices=("success", "failure"))
    args = parser.parse_args()

    estimate, report_count, reason = _estimate(args.reports_dir, args.recent_reports, args.usd_per_kib)
    action = args.action
    if action == "auto" and (
        estimate is None or (args.auto_run_max_cost_usd is not None and estimate > args.auto_run_max_cost_usd)
    ):
        action = "ask"
        reason = reason or "見積額が auto_run_max_cost_usd を超えたため ask にフォールバック"

    if action == "manual":
        print(
            json.dumps(asdict(Decision(action, estimate, report_count, reason, "manual", [], [])), ensure_ascii=False)
        )
        return 0
    if action == "ask":
        if args.choice is None:
            print(
                json.dumps(
                    asdict(
                        Decision(
                            action,
                            estimate,
                            report_count,
                            reason,
                            "ask",
                            ["auto", "manual", "abort"],
                            [],
                        )
                    ),
                    ensure_ascii=False,
                )
            )
            return 0
        if args.choice != "auto":
            print(
                json.dumps(
                    asdict(Decision(action, estimate, report_count, reason, args.choice, [], [])),
                    ensure_ascii=False,
                )
            )
            return 0

    skills = ["analytics-analyze"]
    if args.stale_kind == "absolute":
        skills.insert(0, "analytics-collect")
    decision = Decision(action, estimate, report_count, reason, "execute", [], skills)
    step = next_workflow_step(decision, args.skill_result, args.revalidation)
    print(json.dumps({**asdict(decision), "workflow": asdict(step)}, ensure_ascii=False))
    return 1 if step.outcome == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
