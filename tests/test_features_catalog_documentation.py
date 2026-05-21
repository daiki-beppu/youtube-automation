"""Skill カタログ文書と README 導線の契約テスト."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
FEATURES_DOC_PATH = REPO_ROOT / "docs" / "features.md"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
README_FEATURES_LINK = "[`docs/features.md`](docs/features.md)"
CATALOG_ROW_PATTERN = re.compile(r"^\| /([a-z0-9-]+) \| .+ \|$", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _skill_names() -> list[str]:
    return sorted(path.name for path in SKILLS_DIR.iterdir() if path.is_dir())


def _catalog_skill_names() -> list[str]:
    return CATALOG_ROW_PATTERN.findall(_read(FEATURES_DOC_PATH))


def _features_section(text: str) -> str:
    match = re.search(
        r"^## Features\b.*?(?=^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("README.md に `## Features` セクションが見つかりません")
    return match.group(0)


def test_features_doc_exists() -> None:
    assert FEATURES_DOC_PATH.exists(), f"{FEATURES_DOC_PATH} が存在しません"


def test_readme_has_features_section_link_to_catalog() -> None:
    features_section = _features_section(_read(README_PATH))
    assert README_FEATURES_LINK in features_section, (
        "README.md の `## Features` セクションに "
        f"{README_FEATURES_LINK} へのリンクがありません"
    )


def test_features_doc_lists_every_skill_directory_once() -> None:
    expected = _skill_names()
    actual = sorted(_catalog_skill_names())
    assert actual == expected, (
        "docs/features.md の skill 行が `.claude/skills/` と一致しません\n"
        f"expected={expected}\nactual={actual}"
    )


def test_features_doc_rows_use_strict_skill_row_format() -> None:
    rows = [line for line in _read(FEATURES_DOC_PATH).splitlines() if line.startswith("| /")]
    assert rows, "docs/features.md に `| /skill | ... |` 形式の行がありません"
    for row in rows:
        assert CATALOG_ROW_PATTERN.match(row), f"format violation: {row}"
