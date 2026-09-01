"""Registered JSON document を自己完結 HTML へ変換する CLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import DocumentRenderError, DocumentValidationError
from youtube_automation.domains.documents.schema_registry import (
    RepositorySchema,
    repository_schema_names,
    validate_repository_document,
)
from youtube_automation.infrastructure.documents import publish_json_document
from youtube_automation.infrastructure.documents.publishing import read_published_json_document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-document-render",
        description="検証済み JSON と同 basename の HTML を生成",
    )
    parser.add_argument("json_path", type=Path, nargs="?", help="registry 所有 schema に対応する JSON file")
    parser.add_argument("--schema", choices=repository_schema_names(), help="固定 registry の schema 名")
    parser.add_argument("--check", action="store_true", help="JSON+HTML pair を変更せず検証")
    parser.add_argument(
        "--all",
        dest="scan_root",
        type=Path,
        nargs="?",
        const=Path("."),
        help="directory 以下の registry 所有 JSON を全 schema 横断で走査",
    )
    parser.add_argument("--fix", action="store_true", help="--all で検出した stale / 欠損 HTML を一括再発行")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.scan_root is not None:
        if args.json_path is not None or args.schema is not None:
            raise DocumentRenderError("--all は json_path / --schema と同時に指定できません")
        if args.check == args.fix:
            raise DocumentRenderError("--all には --check または --fix のどちらか一方を指定してください")
        return _scan_all_pairs(args.scan_root, fix=args.fix)
    if args.json_path is None or args.schema is None:
        raise DocumentRenderError("単一文書には json_path と --schema が必要です")
    if args.fix:
        raise DocumentRenderError("--fix は --all と一緒に指定してください")
    schema = RepositorySchema(args.schema)
    if args.check:
        read_published_json_document(args.json_path, schema)
        destination = args.json_path.with_suffix(".html")
    else:
        destination = publish_json_document(args.json_path, schema)
    print(destination.resolve())
    return 0


def _scan_all_pairs(root: Path, *, fix: bool) -> int:
    stale: list[tuple[Path, RepositorySchema]] = []
    for source in sorted(root.rglob("*.json")):
        schema = _infer_registered_schema(source)
        if schema is None:
            continue
        try:
            read_published_json_document(source, schema)
        except DocumentRenderError:
            stale.append((source, schema))

    if fix:
        for source, schema in stale:
            publish_json_document(source, schema)
            print(f"refreshed: {source.resolve()} ({schema.value})")
        print(f"refreshed {len(stale)} document pair(s)")
        return 0

    for source, schema in stale:
        print(f"stale: {source.resolve()} ({schema.value})")
    print(f"stale {len(stale)} document pair(s)")
    return 1 if stale else 0


def _infer_registered_schema(source: Path) -> RepositorySchema | None:
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    matches: list[RepositorySchema] = []
    for schema in RepositorySchema:
        try:
            validate_repository_document(schema, document)
        except DocumentValidationError:
            continue
        matches.append(schema)
    if len(matches) == 1:
        return matches[0]
    return None


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
