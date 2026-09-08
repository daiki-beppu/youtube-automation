"""Canonical command argument helpers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def add_optional_collection_argument(parser: argparse.ArgumentParser) -> None:
    """Accept an optional collection path, defaulting to the caller's current directory."""
    parser.add_argument(
        "collection",
        nargs="?",
        help="コレクションディレクトリ (省略時は CWD)",
    )


def add_stock_filter_arguments(parser: argparse.ArgumentParser, source_roles: Sequence[str]) -> None:
    """Register the shared theme and source-role filters for stock browsing."""
    parser.add_argument("--theme", help="特定テーマ slug でフィルタ")
    parser.add_argument("--source-role", choices=source_roles, help="source_role でフィルタ")


class CompetitorArgumentParser(argparse.ArgumentParser):
    """Reject the removed benchmark ``--channel`` flag with migration guidance."""

    def parse_known_args(
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> tuple[argparse.Namespace, list[str]]:
        tokens = list(sys.argv[1:] if args is None else args)
        if any(token == "--channel" or token.startswith("--channel=") for token in tokens):
            self.error("--channel は --competitor に変わりました。--competitor を使用してください")
        return super().parse_known_args(tokens, namespace)
