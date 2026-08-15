#!/usr/bin/env python3
"""Validate extension mode/modifier arguments before side effects."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

MODES = ("install", "update", "serve", "stop")
TARGETS = ("suno", "distrokid", "community")


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    known = {f"--{name}" for name in (*MODES, *TARGETS)}
    unknown = [argument for argument in arguments if argument not in known]
    if unknown:
        _emit({"reason": "unknown_argument", "arguments": unknown})
        return 2

    selected_modes = [name for argument in arguments for name in MODES if argument == f"--{name}"]
    if len(selected_modes) > 1:
        _emit({"reason": "exclusive_mode_required", "modes": selected_modes})
        return 2

    selected_target_occurrences = [name for argument in arguments for name in TARGETS if argument == f"--{name}"]
    mode = selected_modes[0] if selected_modes else "auto"
    if mode in {"serve", "stop"} and len(selected_target_occurrences) != 1:
        _emit({"reason": "single_target_required", "mode": mode, "targets": selected_target_occurrences})
        return 2
    selected_targets = [name for name in TARGETS if name in selected_target_occurrences]
    if not selected_targets:
        selected_targets = list(TARGETS)
    _emit({"mode": mode, "targets": selected_targets})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
