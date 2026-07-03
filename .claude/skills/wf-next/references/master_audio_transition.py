#!/usr/bin/env python3
"""Resolve `/wf-next` prepared phase master-audio transition."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIO_EXTENSIONS = (".m4a", ".wav", ".flac", ".aac", ".mp3")


def _bool_arg(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("must be true or false")


def _approval_arg(value: str) -> bool:
    if value == "yes":
        return True
    if value == "no":
        return False
    raise argparse.ArgumentTypeError("must be yes or no")


def _load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid workflow-state.json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("workflow-state.json root must be an object")
    assets = data.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("workflow-state.json::assets must be an object")
    return data


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_filename(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"workflow-state.json::{field} must be a non-empty filename string")
    if "/" in value or "\\" in value or ".." in value:
        raise ValueError(f"workflow-state.json::{field} must be a filename: {value}")
    return value


def _final_candidates(master_dir: Path, raw_master: str) -> list[str]:
    if not master_dir.is_dir():
        return []
    candidates = []
    for path in sorted(master_dir.iterdir()):
        if path.name == raw_master or not path.is_file():
            continue
        if path.suffix.lower() in AUDIO_EXTENSIONS:
            candidates.append(path.name)
    return candidates


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _emit(action: str, **payload: Any) -> None:
    print(json.dumps({"action": action, **payload}, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("--skip-manual-mastering", required=True, type=_bool_arg)
    parser.add_argument("--approval-gate-audio", required=True, type=_bool_arg)
    parser.add_argument("--approved", type=_approval_arg)
    parser.add_argument("--selected-master-audio")
    args = parser.parse_args(argv)

    collection = args.collection
    state_path = collection / "workflow-state.json"
    state = _load_state(state_path)
    assets = state["assets"]
    master_dir = collection / "01-master"

    raw_master = _validate_filename(assets.get("raw_master"), "assets.raw_master")
    current_master = _validate_filename(assets.get("master_audio"), "assets.master_audio")
    selected_arg = _validate_filename(args.selected_master_audio, "selected-master-audio")
    if state.get("phase") != "prepared":
        _emit("noop", reason="phase is not prepared")
        return 0
    if raw_master is None or current_master is not None:
        _emit("noop", reason="master-audio step is not pending")
        return 0

    candidates = _final_candidates(master_dir, raw_master)
    if selected_arg is not None:
        if selected_arg == raw_master:
            if candidates:
                raise ValueError("selected-master-audio must be one of the final candidates")
        elif selected_arg not in candidates:
            raise ValueError(f"selected-master-audio is not a final candidate: {selected_arg}")
    elif len(candidates) > 1:
        _emit("needs_selection", candidates=candidates, reason="multiple final candidates")
        return 0

    selected = selected_arg or (candidates[0] if candidates else None)
    reason = "final candidate" if selected else "raw master as final"

    if selected is None:
        if not args.skip_manual_mastering:
            _emit("wait_for_master", reason="manual mastering is required")
            return 0
        selected = raw_master

    if not (master_dir / selected).is_file():
        raise ValueError(f"master audio file does not exist: 01-master/{selected}")

    if args.approval_gate_audio:
        if args.approved is None:
            _emit("needs_approval", master_audio=selected, reason=reason)
            return 0
        if args.approved is False:
            _emit("approval_rejected", master_audio=selected, reason=reason)
            return 0

    assets["master_audio"] = selected
    state["phase"] = "mastered"
    state["updated_at"] = _utc_now()
    _write_state(state_path, state)
    _emit("adopted", master_audio=selected, phase="mastered", reason=reason, updated_at=state["updated_at"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
