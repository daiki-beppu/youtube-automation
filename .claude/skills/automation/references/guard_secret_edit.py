"""Reject secret edits without reading targets; missing/malformed stdin blocks with exit 2."""

from __future__ import annotations

import argparse
import json
import os
import sys

_SECRET_SUFFIXES = ("auth/client_secrets.json", "auth/token.json", ".env")
_LOCK_NAMES = ("uv.lock", "flake.lock")


def edit_path(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Expected a PreToolUse object")
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in ("Edit", "Write"):
        raise ValueError("Expected a PreToolUse Edit/Write event")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise ValueError("Expected tool_input")
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip() or "\x00" in file_path:
        raise ValueError("Expected a nonempty file_path")
    return os.path.normpath(file_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protect-lockfiles", action="store_true", help="Also reject repository lockfile edits")
    args = parser.parse_args()
    try:
        file_path = edit_path(json.load(sys.stdin))
    except ValueError:
        print("BLOCKED: 編集対象を確認できません。PreToolUse JSON 入力を確認してください。", file=sys.stderr)
        return 2
    if file_path.endswith(_SECRET_SUFFIXES) or (args.protect_lockfiles and os.path.basename(file_path) in _LOCK_NAMES):
        print("BLOCKED: 秘密ファイル・保護ファイルは専用ツール経由で更新してください。", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
