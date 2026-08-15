#!/usr/bin/env python3
"""Validate and atomically update `/wf-new --batch` ledger state."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

PLAN_STATUSES = {"pending", "in_progress", "blocked", "failed", "completed"}
BATCH_STATUSES = {"running", "blocked", "failed", "completed"}
TRANSITIONS = {
    "pending": {"in_progress"},
    "in_progress": {"blocked", "failed", "completed"},
    "blocked": {"in_progress"},
    "failed": {"in_progress"},
    "completed": {"blocked"},
}

ACTIVE_PLAN_STATUSES = {"in_progress", "blocked", "failed"}


def validate_ledger(ledger: object) -> dict:
    if not isinstance(ledger, dict):
        raise ValueError("ledger root は object でなければなりません")
    if ledger.get("schema_version") != 1:
        raise ValueError("ledger schema_version は 1 でなければなりません")
    for field in ("batch_id", "manifest_path", "manifest_sha256", "created_at", "updated_at"):
        if not isinstance(ledger.get(field), str) or not ledger[field]:
            raise ValueError(f"ledger.{field} は空でない string でなければなりません")
    requested_count = ledger.get("requested_count")
    plans = ledger.get("plans")
    if (
        isinstance(requested_count, bool)
        or not isinstance(requested_count, int)
        or requested_count < 2
        or not isinstance(plans, list)
        or len(plans) != requested_count
    ):
        raise ValueError("ledger requested_count と plans 件数が一致しません")
    if ledger.get("status") not in BATCH_STATUSES:
        raise ValueError("ledger.status が不正です")

    plan_ids = []
    for index, plan in enumerate(plans):
        if not isinstance(plan, dict):
            raise ValueError(f"ledger.plans[{index}] は object でなければなりません")
        plan_id = plan.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            raise ValueError(f"ledger.plans[{index}].plan_id が不正です")
        if plan.get("status") not in PLAN_STATUSES:
            raise ValueError(f"ledger.plans[{index}].status が不正です")
        plan_ids.append(plan_id)
    if len(set(plan_ids)) != len(plan_ids):
        raise ValueError("ledger plan_id に重複があります")
    current = ledger.get("current_plan_id")
    if current is not None and current not in plan_ids:
        raise ValueError("ledger.current_plan_id が plans に存在しません")

    active_plans = [plan for plan in plans if plan["status"] in ACTIVE_PLAN_STATUSES]
    if len(active_plans) > 1:
        raise ValueError("ledger には active plan を 1 件だけ保持できます")
    if current is None and active_plans:
        raise ValueError("active plan がある ledger には current_plan_id が必要です")
    if current is not None and (len(active_plans) != 1 or active_plans[0]["plan_id"] != current):
        raise ValueError("ledger.current_plan_id は唯一の active plan と一致しなければなりません")

    if ledger["status"] == "running" and current is not None and active_plans[0]["status"] != "in_progress":
        raise ValueError("running batch の current plan は in_progress でなければなりません")
    if ledger["status"] in {"blocked", "failed"} and (current is None or active_plans[0]["status"] != ledger["status"]):
        raise ValueError(f"{ledger['status']} batch の current plan status が一致しません")
    if ledger["status"] == "completed" and (
        current is not None or any(plan["status"] != "completed" for plan in plans)
    ):
        raise ValueError("completed batch は全 plan completed かつ current_plan_id null が必要です")
    return ledger


def _plan(ledger: dict, plan_id: str) -> dict:
    matches = [plan for plan in ledger["plans"] if plan["plan_id"] == plan_id]
    if len(matches) != 1:
        raise ValueError(f"ledger に plan_id={plan_id!r} が一意に存在しません")
    return matches[0]


def transition_plan(
    ledger: dict,
    *,
    plan_id: str,
    target_status: str,
    updated_at: str,
    collection_dir: str | None = None,
    reason: str | None = None,
    resume_action: str | None = None,
) -> dict:
    validate_ledger(ledger)
    updated = copy.deepcopy(ledger)
    plan = _plan(updated, plan_id)
    source_status = plan["status"]
    if target_status not in TRANSITIONS[source_status]:
        raise ValueError(f"不正な plan 遷移です: {source_status} -> {target_status}")
    if source_status == "completed" and target_status == "blocked":
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("completed -> blocked には空でない reason が必要です")
        if not isinstance(resume_action, str) or not resume_action.strip():
            raise ValueError("completed -> blocked には空でない resume_action が必要です")
    if target_status == "in_progress":
        other_active = [
            item["plan_id"]
            for item in updated["plans"]
            if item["plan_id"] != plan_id and item["status"] in ACTIVE_PLAN_STATUSES
        ]
        if other_active:
            raise ValueError(f"別の active plan が存在します: {other_active[0]}")
    plan.update(
        {
            "status": target_status,
            "collection_dir": collection_dir if collection_dir is not None else plan.get("collection_dir"),
            "reason": reason,
            "resume_action": resume_action,
            "updated_at": updated_at,
        }
    )
    updated["updated_at"] = updated_at
    if target_status == "in_progress":
        updated.update(status="running", current_plan_id=plan_id)
    elif target_status in {"blocked", "failed"}:
        updated.update(status=target_status, current_plan_id=plan_id)
    elif all(item["status"] == "completed" for item in updated["plans"]):
        updated.update(status="completed", current_plan_id=None)
    else:
        updated.update(status="running", current_plan_id=None)
    return validate_ledger(updated)


def reconcile_prepared_plan(ledger: dict, *, plan_id: str, actual: object, updated_at: str) -> tuple[dict, bool]:
    """Reconcile the crash window after child completion but before ledger update."""
    validate_ledger(ledger)
    if not isinstance(actual, dict) or not isinstance(actual.get("provenance"), dict):
        raise ValueError("actual state は provenance を持つ object でなければなりません")
    provenance = actual["provenance"]
    if provenance.get("batch_id") != ledger["batch_id"] or provenance.get("plan_id") != plan_id:
        raise ValueError("actual state の batch_id/plan_id provenance が一致しません")
    plan = _plan(ledger, plan_id)
    if plan["status"] == "completed":
        return copy.deepcopy(ledger), False
    if actual.get("phase") != "prepared" or actual.get("hard_artifacts_valid") is not True:
        return copy.deepcopy(ledger), False
    collection_dir = actual.get("collection_dir")
    if not isinstance(collection_dir, str) or not collection_dir:
        raise ValueError("prepared actual state には collection_dir が必要です")

    source_status = plan["status"]
    reconciled = copy.deepcopy(ledger)
    reconciled_plan = _plan(reconciled, plan_id)
    reconciled_plan.update(
        status="completed",
        collection_dir=collection_dir,
        reason="reconciled_after_child_completion",
        resume_action=None,
        updated_at=updated_at,
    )
    reconciled["updated_at"] = updated_at
    if all(item["status"] == "completed" for item in reconciled["plans"]):
        reconciled.update(status="completed", current_plan_id=None)
    else:
        reconciled.update(status="running", current_plan_id=None)
    if source_status not in PLAN_STATUSES:
        raise ValueError(f"reconcile 元 status が不正です: {source_status}")
    return validate_ledger(reconciled), True


def save_ledger(path: Path, ledger: dict) -> None:
    validate_ledger(ledger)
    if path.is_symlink():
        raise ValueError(f"ledger に symlink は使えません: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(ledger, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    return validate_ledger(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("ledger", type=Path)
    transition = subparsers.add_parser("transition")
    transition.add_argument("ledger", type=Path)
    transition.add_argument("--plan-id", required=True)
    transition.add_argument("--status", choices=sorted(PLAN_STATUSES - {"pending"}), required=True)
    transition.add_argument("--updated-at", required=True)
    transition.add_argument("--collection-dir")
    transition.add_argument("--reason")
    transition.add_argument("--resume-action")
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("ledger", type=Path)
    reconcile.add_argument("--plan-id", required=True)
    reconcile.add_argument("--actual", type=Path, required=True)
    reconcile.add_argument("--updated-at", required=True)
    args = parser.parse_args(argv)
    try:
        ledger = _read(args.ledger)
        changed = False
        if args.command == "transition":
            ledger = transition_plan(
                ledger,
                plan_id=args.plan_id,
                target_status=args.status,
                updated_at=args.updated_at,
                collection_dir=args.collection_dir,
                reason=args.reason,
                resume_action=args.resume_action,
            )
            changed = True
        elif args.command == "reconcile":
            actual = json.loads(args.actual.read_text(encoding="utf-8"))
            ledger, changed = reconcile_prepared_plan(
                ledger, plan_id=args.plan_id, actual=actual, updated_at=args.updated_at
            )
        if changed:
            save_ledger(args.ledger, ledger)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"batch ledger error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "updated" if changed else "unchanged"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
