"""data/experiments.jsonl を experiment-entry.schema.json に照らして検証する。"""

from __future__ import annotations

import sys
from pathlib import Path

from youtube_automation.commands.analytics.experiment import validate_entries


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <path/to/experiments.jsonl>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    failures = validate_entries(path)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"OK: {path} は experiment schema 準拠です")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
