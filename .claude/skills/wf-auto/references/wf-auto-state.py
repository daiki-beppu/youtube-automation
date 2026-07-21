#!/usr/bin/env python3
"""Resolve `/wf-auto` bootstrap and resume actions."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Literal, TypedDict


def _load_automation_runner() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "automation-run" / "references" / "automation-run-state.py"
    spec = importlib.util.spec_from_file_location("_wf_auto_automation_runner", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"automation runner をロードできません: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_RUNNER = _load_automation_runner()
RunnerConfig = _RUNNER.RunnerConfig
LeaseBusyError = _RUNNER.LeaseBusyError
acquire_lease = _RUNNER.acquire_lease
heartbeat_lease = _RUNNER.heartbeat_lease
release_lease = _RUNNER.release_lease
record_attempt = _RUNNER.record_attempt


class AutoDecision(TypedDict):
    collection: str | None
    phase: str
    engine: str | None
    action: str
    reason: str
    resume_action: str | None
    allow_external_publish: bool


def record_bootstrap_attempt(
    root: Path,
    *,
    token: str,
    status: Literal["blocked", "failed"],
    reason: str,
    now: str,
) -> None:
    """Record an unattended `/wf-new` stop before a collection exists."""
    _RUNNER.record_attempt(
        root,
        token=token,
        collection=None,
        action="wf-new",
        status=status,
        reason=reason,
        resume_action="wf-new",
        now=now,
    )


def resolve_action(
    root: Path,
    requested: str | None = None,
    *,
    config: RunnerConfig | None = None,
) -> AutoDecision:
    """Return the next delegated action without mutating workflow state."""
    resolved_config = config or _RUNNER._load_runner_config(root)
    try:
        collection = _RUNNER.select_collection(root, requested)
    except _RUNNER.NoActiveCollectionError:
        if requested is not None:
            raise
        return {
            "collection": None,
            "phase": "absent",
            "engine": None,
            "action": "wf-new",
            "reason": "no_active_collection",
            "resume_action": "wf-new",
            "allow_external_publish": resolved_config.allow_external_publish,
        }
    return _RUNNER.evaluate_collection(root, collection, resolved_config)


def main(argv: list[str] | None = None) -> int:
    """Run the shared lease/history CLI with `/wf-auto` plan semantics."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "record-bootstrap":
        parser = argparse.ArgumentParser(description="Record a pre-collection /wf-auto stop.")
        parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
        parser.add_argument("--token", required=True)
        parser.add_argument("--status", choices=("blocked", "failed"), required=True)
        parser.add_argument("--reason", required=True)
        bootstrap = parser.parse_args(arguments[1:])
        try:
            record_bootstrap_attempt(
                bootstrap.channel_dir.resolve(),
                token=bootstrap.token,
                status=bootstrap.status,
                reason=bootstrap.reason,
                now=datetime.now(UTC).isoformat(),
            )
        except LeaseBusyError as exc:
            print(json.dumps({"status": "busy", "reason": str(exc)}, ensure_ascii=False))
            return 20
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({"status": "recorded"}, ensure_ascii=False))
        return 0

    args = _RUNNER._parser().parse_args(arguments)
    if args.command != "plan":
        return _RUNNER.main(arguments)
    try:
        result = resolve_action(args.channel_dir.resolve(), args.collection)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
