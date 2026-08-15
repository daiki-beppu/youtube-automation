"""feedback-log.jsonl を共通 schema registry で検証する。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from youtube_automation.core.errors import DocumentValidationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema, validate_repository_document


def validate_entry(entry: object) -> None:
    """1 entry を検証し、値を含まない domain error を送出する。"""
    validate_repository_document(RepositorySchema.FEEDBACK_ENTRY, entry)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <path/to/feedback-log.jsonl>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.exists():
        print(f"OK: {path} は存在しません（エントリ 0 件として扱います）")
        return 0

    failed = False
    count = 0
    with path.open(encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            if not raw_line.strip():
                continue
            count += 1
            try:
                entry = json.loads(raw_line)
                validate_entry(entry)
            except json.JSONDecodeError as error:
                print(f"line {line_number}: JSONDecodeError line={error.lineno} column={error.colno}", file=sys.stderr)
                failed = True
            except DocumentValidationError as error:
                print(f"line {line_number}: {error}", file=sys.stderr)
                failed = True
    if failed:
        return 1
    print(f"OK: {path}（{count} エントリ）は schema 準拠です")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
