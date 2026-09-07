"""Truth Eye 訓練記録の封印・検証 CLI。"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.analytics.truth_eye import (
    collect_training_status,
    seal_training_record,
    select_pair_candidates,
    validate_sealed_draft,
    verify_training_record,
)
from youtube_automation.infrastructure.analytics.truth_eye_population import load_truth_eye_population
from youtube_automation.infrastructure.vcs.training_commit import commit_training_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Truth Eye 訓練記録の封印分析を管理します")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal = subparsers.add_parser("seal", help="承認済みペアと下書きから封印分析・訓練記録を生成")
    seal.add_argument("--pair", type=Path, required=True, help="承認済みペア JSON の path")
    seal.add_argument("--sealed-draft", type=Path, required=True, help="封印分析 Markdown 下書きの path")
    seal.add_argument("--channel-dir", type=Path, default=Path.cwd(), help="チャンネルリポジトリの root")
    verify = subparsers.add_parser("verify", help="封印分析の sha256 を訓練記録と照合")
    verify.add_argument("record", type=Path, help="検証する訓練記録 Markdown の path")
    status = subparsers.add_parser("status", help="未完了記録と成長トラッキングを表示")
    status.add_argument("--channel-dir", type=Path, default=Path.cwd(), help="チャンネルリポジトリの root")
    pair = subparsers.add_parser("pair", help="benchmark 走査記録から承認用ペア候補を選定")
    pair.add_argument("--channel-dir", type=Path, default=Path.cwd(), help="チャンネルリポジトリの root")
    pair.add_argument("--rejected", action="append", default=[], help="却下済みの伸びた側 video_id（複数指定可）")
    return parser


def run(args: argparse.Namespace) -> int:
    try:
        if args.command == "seal":
            pair = json.loads(args.pair.read_text(encoding="utf-8"))
            draft_text = args.sealed_draft.read_text(encoding="utf-8")
            missing = validate_sealed_draft(draft_text)
            if missing:
                print(json.dumps({"ok": False, "missing": missing}, ensure_ascii=False))
                return 1
            result = seal_training_record(pair, args.sealed_draft, args.channel_dir)
            stem = result.record.name.removesuffix(".md")
            commit_result = commit_training_files(
                args.channel_dir,
                (result.record, result.sealed),
                f"docs(truth-eye): 訓練記録を封印する {stem}",
            )
            commit_payload = {
                "committed": commit_result.committed,
                "commit": commit_result.commit,
                "reason": commit_result.reason,
                "changed_files": list(commit_result.changed_files),
            }
            print(
                json.dumps(
                    {
                        "ok": True,
                        "record": str(result.record),
                        "sealed": str(result.sealed),
                        "sha256": result.sha256,
                        "sealed_at": result.sealed_at,
                        **commit_payload,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "verify":
            result = verify_training_record(args.record)
            print(json.dumps({"ok": result.ok, "expected": result.expected, "actual": result.actual}))
            return 0 if result.ok else 1
        if args.command == "pair":
            freshness_days = int(load_skill_config("benchmark").get("freshness_days", 3))
            competitors, used_ids, warnings = load_truth_eye_population(args.channel_dir, freshness_days=freshness_days)
            result = select_pair_candidates(competitors, used_ids, tuple(args.rejected), date.today())
            result["warnings"] = warnings
            print(json.dumps(result, ensure_ascii=False))
            return 0
        status = collect_training_status(args.channel_dir)
        print(
            json.dumps(
                {
                    "incomplete": [
                        {
                            "record": str(item.record),
                            "resume_phase": item.resume_phase,
                            "phase2_turns": item.phase2_turns,
                        }
                        for item in status.incomplete
                    ],
                    "last_next_try": status.last_next_try,
                    "recurring_ai_only_viewpoints": list(status.recurring_ai_only_viewpoints),
                    "completed_count": status.completed_count,
                    "incomplete_count": status.incomplete_count,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, json.JSONDecodeError, ConfigError, ValidationError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, handled_errors=())


if __name__ == "__main__":
    raise SystemExit(main())
