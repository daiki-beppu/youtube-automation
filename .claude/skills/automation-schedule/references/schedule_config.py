#!/usr/bin/env python3
"""`workflow.scheduled_automation` の表示・生成・差分更新（/automation-schedule 用）（#1892）.

チャンネルリポジトリ直下で実行する:

    uv run python .claude/skills/automation-schedule/references/schedule_config.py show
    uv run python .claude/skills/automation-schedule/references/schedule_config.py generate --dry-run
    uv run python .claude/skills/automation-schedule/references/schedule_config.py generate \
        --enable --run-time 09:00 --cadence mon,wed,fri

- `show`: 現在の effective 設定（loader 検証済み）を JSON で表示する。
- `generate`: `config/channel/workflow.json` に `scheduled_automation` を merge する。
  `--dry-run` では差分表示のみで書き込まない。書き込み前に loader の検証を通し、
  invalid な設定は一切書き込まない。
- `--allow-external-publish` は明示フラグがある場合のみ true を書ける
  （SKILL.md の承認ゲートを通過した後にのみ付与すること）。
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from youtube_automation.utils.config import channel_dir, load_config

# loader と同一ロジックで書き込み前検証するため、private builder を意図的に共有する
from youtube_automation.utils.config.loader import _build_workflow
from youtube_automation.utils.config.workflow import (
    SCHEDULED_AUTOMATION_CADENCE_DAYS,
    SCHEDULED_AUTOMATION_NOTIFICATIONS,
    ScheduledAutomation,
)
from youtube_automation.utils.exceptions import ConfigError

_WORKFLOW_JSON = "config/channel/workflow.json"


def _workflow_path() -> Path:
    return channel_dir() / "config" / "channel" / "workflow.json"


def _load_workflow_raw(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{_WORKFLOW_JSON} は object でなければなりません")
    return data


def _scheduled_to_dict(sa: ScheduledAutomation) -> dict:
    return {
        "enabled": sa.enabled,
        "timezone": sa.timezone,
        "run_time": sa.run_time,
        "cadence": list(sa.cadence),
        "target_workflow": sa.target_workflow,
        "max_retries": sa.max_retries,
        "retry_delay_seconds": sa.retry_delay_seconds,
        "prevent_concurrent_runs": sa.prevent_concurrent_runs,
        "notification": sa.notification,
        "allow_external_publish": sa.allow_external_publish,
    }


def cmd_show(_args: argparse.Namespace) -> int:
    config = load_config()
    print(json.dumps(_scheduled_to_dict(config.workflow.scheduled_automation), ensure_ascii=False, indent=2))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    path = _workflow_path()
    raw = _load_workflow_raw(path)
    wf = raw.setdefault("workflow", {})
    if not isinstance(wf, dict):
        raise ConfigError(f"{_WORKFLOW_JSON} の workflow セクションは object でなければなりません")

    # 既存設定 → 安全な既定値の順で下敷きにし、指定されたフラグだけ上書きする
    current = wf.get("scheduled_automation")
    merged = _scheduled_to_dict(ScheduledAutomation())
    if isinstance(current, dict):
        merged.update(current)

    if args.enable:
        merged["enabled"] = True
    if args.disable:
        merged["enabled"] = False
    if args.timezone is not None:
        merged["timezone"] = args.timezone
    if args.run_time is not None:
        merged["run_time"] = args.run_time
    if args.cadence is not None:
        merged["cadence"] = [d.strip() for d in args.cadence.split(",") if d.strip()]
    if args.target_workflow is not None:
        merged["target_workflow"] = args.target_workflow
    if args.max_retries is not None:
        merged["max_retries"] = args.max_retries
    if args.retry_delay_seconds is not None:
        merged["retry_delay_seconds"] = args.retry_delay_seconds
    if args.notification is not None:
        merged["notification"] = args.notification
    # 外部公開許可は明示フラグでのみ有効化できる（承認ゲート後にのみ付与する）
    merged["allow_external_publish"] = bool(args.allow_external_publish)

    # 書き込み前検証: loader と同一ロジック（単一ソース）で invalid を弾く
    candidate = dict(raw)
    candidate["workflow"] = dict(wf)
    candidate["workflow"]["scheduled_automation"] = merged
    _build_workflow(candidate)

    before = json.dumps(raw if path.exists() else {}, ensure_ascii=False, indent=2, sort_keys=False)
    if path.exists():
        before = path.read_text(encoding="utf-8")
    wf["scheduled_automation"] = merged
    after = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"

    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{_WORKFLOW_JSON}",
            tofile=f"b/{_WORKFLOW_JSON}",
        )
    )
    print(diff if diff else "(差分なし)")

    if args.dry_run:
        print("--dry-run のため書き込みは行いません", file=sys.stderr)
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(after, encoding="utf-8")
    print(f"{_WORKFLOW_JSON} を更新しました", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", help="現在の effective 設定を JSON 表示")

    gen = sub.add_parser("generate", help="workflow.json へ scheduled_automation を merge")
    gen.add_argument("--dry-run", action="store_true", help="差分表示のみで書き込まない")
    gen.add_argument("--enable", action="store_true", help="定期実行を有効化")
    gen.add_argument("--disable", action="store_true", help="定期実行を無効化")
    gen.add_argument("--timezone")
    gen.add_argument("--run-time", dest="run_time", help="HH:MM（24 時間表記）")
    gen.add_argument("--cadence", help=f"カンマ区切りの曜日（{','.join(SCHEDULED_AUTOMATION_CADENCE_DAYS)}）")
    gen.add_argument("--target-workflow", dest="target_workflow")
    gen.add_argument("--max-retries", dest="max_retries", type=int)
    gen.add_argument("--retry-delay-seconds", dest="retry_delay_seconds", type=int)
    gen.add_argument("--notification", choices=SCHEDULED_AUTOMATION_NOTIFICATIONS)
    gen.add_argument(
        "--allow-external-publish",
        action="store_true",
        help="YouTube への書き込みを許可（SKILL.md の明示承認ゲート通過後にのみ付与）",
    )

    args = parser.parse_args(argv)
    if args.command == "show":
        return cmd_show(args)
    if getattr(args, "enable", False) and getattr(args, "disable", False):
        parser.error("--enable と --disable は同時指定できません")
    try:
        return cmd_generate(args)
    except ConfigError as exc:
        print(f"ConfigError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
