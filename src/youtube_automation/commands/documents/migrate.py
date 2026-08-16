"""Skill-generated operational document migration CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from youtube_automation.application.documents import (
    MarkdownMigrationDecision,
    require_recorded_machine_verification,
    write_channel_strategy_document,
    write_collection_plan_document,
    write_music_prompt_document,
    write_operational_document,
    write_video_description_document,
)
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema, repository_schema_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-document-migrate",
        description="skill が生成した candidate JSON を検証済み JSON + HTML pair として公開",
    )
    parser.add_argument("candidate", type=Path, nargs="?", help="承認後に skill writer が生成した未公開 JSON")
    parser.add_argument("--target", type=Path, required=True, help="公開先 .json path")
    parser.add_argument("--schema", required=True, choices=repository_schema_names(), help="固定 registry の schema 名")
    parser.add_argument("--workflow-state", type=Path, help="collection 文書公開後に更新する workflow-state.json")
    parser.add_argument(
        "--migration-decision",
        choices=(MarkdownMigrationDecision.YES.value, MarkdownMigrationDecision.NO.value),
        help="Markdown-only 更新で利用者が明示した yes/no",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    decision = (
        MarkdownMigrationDecision.NOT_REQUIRED
        if args.migration_decision is None
        else MarkdownMigrationDecision(args.migration_decision)
    )

    def load_candidate() -> object:
        if args.candidate is None:
            raise ValidationError("公開を続けるには承認後に生成した candidate JSON が必要です")
        if args.candidate.resolve() == args.target.resolve():
            raise ValidationError("candidate と公開先 JSON は別 path にしてください")
        return json.loads(args.candidate.read_text(encoding="utf-8"))

    schema = RepositorySchema(args.schema)
    if schema is RepositorySchema.CHANNEL_STRATEGY:
        result = write_channel_strategy_document(args.target, load_candidate, decision)
    elif schema is RepositorySchema.COLLECTION_PLAN:
        if args.workflow_state is None:
            raise ValidationError("collection plan の公開には --workflow-state が必要です")
        result = write_collection_plan_document(args.target, args.workflow_state, load_candidate, decision)
    elif schema is RepositorySchema.MUSIC_PROMPT:
        if args.workflow_state is None:
            raise ValidationError("music prompt の公開には --workflow-state が必要です")
        result = write_music_prompt_document(
            args.target,
            args.workflow_state,
            load_candidate,
            decision,
            machine_verify=require_recorded_machine_verification,
        )
    elif schema is RepositorySchema.VIDEO_DESCRIPTION:
        if args.workflow_state is None:
            raise ValidationError("video description の公開には --workflow-state が必要です")
        result = write_video_description_document(args.target, args.workflow_state, load_candidate, decision)
    else:
        if args.workflow_state is not None:
            raise ValidationError("--workflow-state は collection plan / music prompt / video description 専用です")
        result = write_operational_document(args.target, schema, load_candidate, decision)
    print(f"{result.value}: {args.target.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        build_parser,
        run,
        argv,
        failure_message="error",
        handled_errors=(ValidationError, OSError, UnicodeError, json.JSONDecodeError),
    )


if __name__ == "__main__":
    raise SystemExit(main())
