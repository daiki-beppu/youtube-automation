#!/usr/bin/env python3
"""CLI wrapper for playlist × suno-prompts.json consistency gate before masterup."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from youtube_automation.utils.collection_paths import resolve_collection_dir
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.suno_playlist_verification import (
    format_verification_report,
    load_entry_names,
    verify_playlist_titles,
)


def _read_titles(args: argparse.Namespace) -> list[str]:
    explicit_sources = [name for name in ("titles", "titles_file") if getattr(args, name)]
    if len(explicit_sources) > 1:
        raise ValidationError("playlist 曲名の入力元は --titles / --titles-file / stdin のいずれか 1 つにしてください")

    if args.titles is not None:
        titles = [t for t in args.titles if t.strip()]
        if not titles:
            raise ValidationError("--titles には 1 件以上の曲名を指定してください")
        return titles
    if args.titles_file:
        path = Path(args.titles_file)
        if not path.is_file():
            raise ValidationError(f"--titles-file が見つかりません: {path}")
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
            if not isinstance(data, list) or not all(isinstance(t, str) for t in data):
                raise ValidationError("--titles-file (JSON) は文字列の配列にしてください")
            return [t for t in data if t.strip()]
        return [line for line in raw.splitlines() if line.strip()]
    if not sys.stdin.isatty():
        titles = [line for line in sys.stdin.read().splitlines() if line.strip()]
        if titles:
            return titles
    raise ValidationError("playlist 曲名を --titles / --titles-file / stdin のいずれかで渡してください")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Suno playlist の曲名一覧を suno-prompts.json の entry title/name と突合し、"
            "混入（unknown）と未生成（missing）を fail-loud で検出する"
        )
    )
    parser.add_argument("collection", nargs="?", help="コレクションディレクトリ (省略時は CWD)")
    parser.add_argument("--titles", nargs="*", help="playlist の曲名（複数指定）")
    parser.add_argument("--titles-file", help="曲名リストのファイル（1行1曲、または JSON 配列）")
    parser.add_argument(
        "--expected-clips-per-entry",
        type=int,
        default=2,
        help="entry あたりの期待 clip 数（既定 2、0 で不足チェック無効）",
    )
    parser.add_argument("--json", action="store_true", help="結果を JSON で出力する")
    args = parser.parse_args()

    try:
        if args.expected_clips_per_entry < 0:
            raise ValidationError("--expected-clips-per-entry は 0 以上にしてください")
        collection_dir = resolve_collection_dir(args.collection)
        entry_names = load_entry_names(collection_dir)
        titles = _read_titles(args)
        result = verify_playlist_titles(
            entry_names,
            titles,
            expected_clips_per_entry=args.expected_clips_per_entry,
        )
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "matched": dict(result.matched),
                    "unknown_titles": list(result.unknown_titles),
                    "missing_entries": list(result.missing_entries),
                    "underfilled_entries": list(result.underfilled_entries),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_verification_report(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
