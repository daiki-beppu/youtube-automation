#!/usr/bin/env python3
"""Compatibility entry point delegating `/automation-run` to `/wf-auto`."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_wf_auto_runner() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "wf-auto" / "references" / "wf-auto-state.py"
    spec = importlib.util.spec_from_file_location("_automation_run_wf_auto_runner", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"wf-auto runner をロードできません: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_RUNNER = _load_wf_auto_runner()
for _name in dir(_RUNNER):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_RUNNER, _name)


if __name__ == "__main__":
    sys.exit(_RUNNER.main())
