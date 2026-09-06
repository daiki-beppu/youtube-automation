"""Truth Eye 訓練記録の封印・検証 CLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.analytics.truth_eye import (
    seal_training_record,
    validate_sealed_draft,
    verify_training_record,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Truth Eye 訓練記録の封印分析を管理します")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal = subparsers.add_parser("seal", help="承認済みペアと下書きから封印分析・訓練記録を生成")
    seal.add_argument("--pair", type=Path, required=True, help="承認済みペア JSON の path")
    seal.add_argument("--sealed-draft", type=Path, required=True, help="封印分析 Markdown 下書きの path")
    seal.add_argument("--channel-dir", type=Path, default=Path.cwd(), help="チャンネルリポジトリの root")
    verify = subparsers.add_parser("verify", help="封印分析の sha256 を訓練記録と照合")
    verify.add_argument("record", type=Path, help="検証する訓練記録 Markdown の path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "seal":
            pair = json.loads(args.pair.read_text(encoding="utf-8"))
            draft_text = args.sealed_draft.read_text(encoding="utf-8")
            missing = validate_sealed_draft(draft_text)
            if missing:
                print(json.dumps({"ok": False, "missing": missing}, ensure_ascii=False))
                return 1
            result = seal_training_record(pair, args.sealed_draft, args.channel_dir)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "record": str(result.record),
                        "sealed": str(result.sealed),
                        "sha256": result.sha256,
                        "sealed_at": result.sealed_at,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        result = verify_training_record(args.record)
        print(json.dumps({"ok": result.ok, "expected": result.expected, "actual": result.actual}))
        return 0 if result.ok else 1
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
