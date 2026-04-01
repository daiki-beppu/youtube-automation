#!/usr/bin/env python3
"""{{CHANNEL_NAME}} チャンネル - get_channel_status ラッパー"""
import os
import sys
from pathlib import Path

CHANNEL_DIR = Path(__file__).parent
os.environ.setdefault('CHANNEL_DIR', str(CHANNEL_DIR))
sys.path.insert(0, str(CHANNEL_DIR / 'automation'))

import importlib.util  # noqa: E402
import importlib.machinery
_loader = importlib.machinery.SourceFileLoader("get_channel_status", str(CHANNEL_DIR / "automation" / "get_channel_status"))
spec = importlib.util.spec_from_loader("get_channel_status", _loader)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.main()
