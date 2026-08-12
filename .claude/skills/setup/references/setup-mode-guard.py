#!/usr/bin/env python3
"""Resolve the exclusive /setup mode without mutating channel artifacts."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

MODE_FLAGS = ("--tool", "--channel")
EXIT_EXCLUSIVE_MODE = 2


def resolve_mode(arguments: Sequence[str]) -> str | None:
    selected = [argument for argument in arguments if argument in MODE_FLAGS]
    if len(selected) > 1:
        raise ValueError("setup mode は --tool / --channel のどちらか 1 つだけ指定してください")
    return selected[0] if selected else None


def main(arguments: Sequence[str] | None = None) -> int:
    try:
        mode = resolve_mode(sys.argv[1:] if arguments is None else arguments)
    except ValueError as error:
        print(json.dumps({"status": "error", "reason": "exclusive_mode", "message": str(error)}), file=sys.stderr)
        return EXIT_EXCLUSIVE_MODE
    print(json.dumps({"status": "ok", "mode": mode or "default"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
