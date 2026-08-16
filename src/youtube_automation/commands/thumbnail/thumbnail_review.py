"""Review thumbnail candidates in one safe HTML page and finalize one ID."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from youtube_automation.application.thumbnail_review import (
    ThumbnailReviewResult,
    finalize_thumbnail_review_selection,
    run_thumbnail_review,
)
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration import channel_dir
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="thumbnail/main候補と固定QAを安全な比較HTMLで確認し、候補IDだけを確定する"
    )
    parser.add_argument("--collection", type=Path, required=True, help="対象collection directory")
    parser.add_argument("--artifact", choices=("thumbnail", "main"), required=True)
    parser.add_argument("--pattern", help="AB thumbnailのpattern。mainには指定不可")
    parser.add_argument("--transport", choices=("web", "terminal"), default="web")
    parser.add_argument("--candidate-id", help="terminal fallbackで会話確認済みの候補ID")
    parser.add_argument(
        "--automatic",
        action="store_true",
        help="HTML/brokerを生成せず既存yt-thumbnail-auto-select ownerへ委譲する",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    collection = args.collection.resolve()
    if args.automatic:
        if (
            args.transport != "web"
            or args.candidate_id is not None
            or args.pattern is not None
            or args.artifact != "thumbnail"
        ):
            raise ValidationError("--automaticは通常thumbnailのweb既定値とだけ併用できます")
        run_thumbnail_review(collection, "thumbnail", automatic=True)
        print(json.dumps({"status": "skipped", "owner": "yt-thumbnail-auto-select"}, sort_keys=True))
        return 0
    if args.transport == "web" and args.candidate_id is not None:
        raise ValidationError("--candidate-idは--transport terminal専用です")

    artifact = args.artifact
    pattern = args.pattern
    if args.transport == "web":
        result = run_thumbnail_review(collection, artifact, pattern=pattern, transport="web")
        candidate_id, digest = _selected_result(result)
        source = "web"
    else:
        result = run_thumbnail_review(collection, artifact, pattern=pattern, transport="terminal")
        digest = _required_digest(result)
        if args.candidate_id is None:
            print(
                json.dumps(
                    {
                        "status": "terminal_required",
                        "artifact": artifact,
                        "pattern": pattern,
                        "candidates": list(result.candidates),
                        "artifact_digest": digest,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            print("候補を会話で確認後、--candidate-id <ID>を明示して再実行してください", file=sys.stderr)
            return 2
        candidate_id = args.candidate_id
        if candidate_id not in result.candidates:
            raise ValidationError(f"候補IDがreview manifest allowlistにありません: {candidate_id}")
        source = "terminal"

    root = channel_dir()
    config = load_skill_config("thumbnail", channel_dir=root)
    archive = config.get("archive", {})
    if not isinstance(archive, dict):
        raise ValidationError("thumbnail.archiveはmappingである必要があります")
    target = finalize_thumbnail_review_selection(
        collection,
        artifact=artifact,
        pattern=pattern,
        candidate_id=candidate_id,
        source=source,
        expected_artifact_digest=digest,
        archive_config=archive,
        channel_root=root,
    )
    print(
        json.dumps(
            {"status": "selected", "candidate_id": candidate_id, "source": source, "target": str(target)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _selected_result(result: ThumbnailReviewResult) -> tuple[str, str]:
    if result.status != "selected" or result.candidate_id is None:
        raise ValidationError("Web reviewからthumbnail候補IDを取得できません")
    return result.candidate_id, _required_digest(result)


def _required_digest(result: ThumbnailReviewResult) -> str:
    if result.artifact_digest is None:
        raise ValidationError("review manifestにartifact digestがありません")
    return result.artifact_digest


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="thumbnail reviewに失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
