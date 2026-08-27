#!/usr/bin/env python3
"""changelog.d/ の fragment を release prepare と同じ実装で検証する。

PR CI の changelog job は nix / uv を持たない軽量 job なので、runner の素の python から
`youtube_automation.commands.system.changelog_fragments.load_fragments` を呼ぶ。これにより
fragment ファイル名の type 文字列と本文の bullet 体裁が、リリース時ではなく PR 時点で fail する。

規則を再実装せず同 module を直接 import するため、`changelog_fragments` は third-party 依存
なしで import できる必要がある（`tests/repo/test_changelog_ci_contract.py` で機械担保）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from youtube_automation.commands.system.changelog_fragments import load_fragments  # noqa: E402
from youtube_automation.core.errors import ConfigError  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fragments-dir",
        type=Path,
        default=_REPO_ROOT / "changelog.d",
        help="検証する fragment ディレクトリ",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        load_fragments(args.fragments_dir)
    except ConfigError as error:
        # load_fragments は最初の違反で停止するため、複数違反があれば修正のたびに再検出される。
        print(f"::error::{error}")
        print("書き方は changelog.d/README.md を参照してください。", file=sys.stderr)
        return 1
    print("changelog fragments are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
