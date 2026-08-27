"""changelog fragment のファイル名 type と本文 bullet 体裁の規則。

PR CI の changelog ゲートは nix / uv を持たない軽量 job なので、runner の素の python が
`.github/scripts/validate-changelog-fragments.py` からこの module を import して fragment を
検証する。規則を CI 側へ再実装しないための共有 module であり、**module import 時に
third-party 依存を持ち込んではならない**（`commands._shared.cli_harness` は
`infrastructure.auth` 経由で google SDK を eager import するため、ここからは参照しない）。
この制約は `tests/repo/test_changelog_ci_contract.py` が実行で機械担保する。
"""

from __future__ import annotations

import re
from pathlib import Path

from youtube_automation.core.errors import ConfigError

SECTION_ORDER = (
    "added",
    "changed",
    "deprecated",
    "removed",
    "fixed",
    "security",
    "migration",
)
_FRAGMENT_PATTERN = re.compile(rf"^.+\.(?P<type>{'|'.join(SECTION_ORDER)})\.md$")


def load_fragments(fragments_dir: Path) -> dict[str, list[tuple[Path, str]]]:
    """fragment を type 別に読み込み、ファイル名と bullet 体裁を検証する。"""
    grouped = {section: [] for section in SECTION_ORDER}
    if not fragments_dir.exists():
        return grouped

    for path in sorted(fragments_dir.glob("*.md")):
        if path.name.casefold() == "readme.md":
            continue
        match = _FRAGMENT_PATTERN.fullmatch(path.name)
        if match is None:
            raise ConfigError(f"不正な changelog fragment ファイル名です: {path.name}")
        body = path.read_text(encoding="utf-8").strip()
        lines = [line for line in body.splitlines() if line.strip()]
        if not lines or any(not line.startswith("- ") for line in lines):
            raise ConfigError(f"changelog fragment は '- ' で始まる bullet で記述してください: {path.name}")
        grouped[match.group("type")].append((path, "\n".join(lines)))
    return grouped
