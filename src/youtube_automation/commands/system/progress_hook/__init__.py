"""Claude Code のバックグラウンド Bash 開始時に進捗を表示する hook。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

_PROGRESS = """```
  ✓  企画
  ✓  音源生成
  ✓  マスター化
  ▸  動画化
  ○  サムネイル
  ○  アップロード
  ○  公開後処理
  ○  分析
```"""


def _is_background_bash(payload: object) -> bool:
    if not isinstance(payload, Mapping) or payload.get("tool_name") != "Bash":
        return False
    tool_input = payload.get("tool_input")
    return isinstance(tool_input, Mapping) and tool_input.get("run_in_background") is True


def main(argv: Sequence[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """hook payload を読み、対象の Bash 開始時だけ進捗図を返す。"""

    parser = argparse.ArgumentParser(description="バックグラウンド Bash 開始時の進捗図を claude.app へ表示する")
    parser.parse_args(argv)
    source = stdin if stdin is not None else sys.stdin
    try:
        payload = json.load(source)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0

    if _is_background_bash(payload):
        print(json.dumps({"systemMessage": _PROGRESS}, ensure_ascii=False))
    return 0
