"""Shared parser and diagnostics for generated ``descriptions.md`` files."""

from __future__ import annotations

import re
from collections.abc import Sequence

DESCRIPTIONS_MD_EXPECTED_HEADINGS = (
    "タイトル案",
    "Complete Collection 概要欄",
    "タグ（YouTube タグ欄）",
)

DESCRIPTIONS_MD_RECREATE_GUIDE = (
    "→ 手書きファイルを直接直すのではなく、正規フローで作り直してください:\n"
    "  1. /video-description を再実行する\n"
    "  2. 生成された 20-documentation/descriptions.md を確認する\n"
    "  3. 必要なら生成後の本文だけを調整してから再アップロードする\n"
    "  必須セクション: `## タイトル案` / `## Complete Collection 概要欄` / `## タグ（YouTube タグ欄）`"
)


def extract_level2_headings(text: str) -> list[str]:
    """Return level-2 Markdown headings from ``descriptions.md`` in file order."""
    return [match.group(1).strip() for match in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE)]


def extract_descriptions_md_section(text: str, heading: str) -> str | None:
    """Extract the fenced body immediately below an exact level-2 heading."""
    pattern = rf"^##[ \t]+{re.escape(heading)}[ \t]*\n+```\n(.*?)```"
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else None


def missing_descriptions_md_headings(text: str) -> list[str]:
    """Return expected headings that cannot be parsed from ``descriptions.md``."""
    return [
        heading
        for heading in DESCRIPTIONS_MD_EXPECTED_HEADINGS
        if extract_descriptions_md_section(text, heading) is None
    ]


def format_heading_list(headings: Sequence[str]) -> str:
    if not headings:
        return "  - (なし)"
    return "\n".join(f"  - ## {heading}" for heading in headings)


def build_descriptions_md_parse_diagnostics(text: str, missing_headings: Sequence[str] | None = None) -> str:
    """Explain a ``descriptions.md`` heading mismatch in a user-actionable form."""
    found_headings = extract_level2_headings(text)
    missing_source = missing_headings if missing_headings is not None else missing_descriptions_md_headings(text)
    missing = list(dict.fromkeys(missing_source))
    return "\n".join(
        [
            "期待する見出し（完全一致）:",
            format_heading_list(DESCRIPTIONS_MD_EXPECTED_HEADINGS),
            "不足/不一致の見出し:",
            format_heading_list(missing),
            "検出した ## 見出し:",
            format_heading_list(found_headings),
            "修正例:",
            "  ## タイトル案",
            "  ```",
            "  公開タイトル",
            "  ```",
            "  ## Complete Collection 概要欄",
            "  ```",
            "  概要欄本文",
            "  ```",
            "  ## タグ（YouTube タグ欄）",
            "  ```",
            "  tag one, tag two",
            "  ```",
            DESCRIPTIONS_MD_RECREATE_GUIDE,
        ]
    )
