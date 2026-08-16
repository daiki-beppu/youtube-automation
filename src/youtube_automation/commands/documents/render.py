"""Registered JSON document を自己完結 HTML へ変換する CLI。"""

from __future__ import annotations

import argparse
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import DocumentRenderError, DocumentValidationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema, repository_schema_names
from youtube_automation.infrastructure.documents import publish_json_document
from youtube_automation.infrastructure.documents.publishing import read_published_json_document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-document-render",
        description="検証済み JSON と同 basename の HTML を生成",
    )
    parser.add_argument("json_path", type=Path, help="registry 所有 schema に対応する JSON file")
    parser.add_argument("--schema", required=True, choices=repository_schema_names(), help="固定 registry の schema 名")
    parser.add_argument("--check", action="store_true", help="JSON+HTML pair を変更せず検証")
    return parser


def run(args: argparse.Namespace) -> int:
    schema = RepositorySchema(args.schema)
    if args.check:
        read_published_json_document(args.json_path, schema)
        destination = args.json_path.with_suffix(".html")
    else:
        destination = publish_json_document(args.json_path, schema)
    print(destination.resolve())
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        build_parser,
        run,
        argv,
        failure_message="error",
        handled_errors=(DocumentRenderError, DocumentValidationError, OSError, UnicodeError),
    )


if __name__ == "__main__":
    raise SystemExit(main())
