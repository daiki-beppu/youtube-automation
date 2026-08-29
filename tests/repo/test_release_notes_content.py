"""公開リリースノートのコンテンツ契約を検証する。"""

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
NOTES_DIR = ROOT / "docs" / "release-notes"
EXPECTED_NOTES = {
    "v5.5.17.md": (
        "v5.5.17",
        date(2026, 7, 10),
        "main",
        "youtube-automation v5.5.17",
        -2026071002,
        "/automation --update",
    ),
    "v5.6.0.md": (
        "v5.6.0",
        date(2026, 7, 31),
        "main",
        "youtube-automation v5.6.0",
        -2026073102,
        "/automation --update",
    ),
    "v5.7.0.md": (
        "v5.7.0",
        date(2026, 8, 29),
        "main",
        "youtube-automation v5.7.0",
        -2026082902,
        "/automation --update",
    ),
    "ext-v0.2.5.md": (
        "ext-v0.2.5",
        date(2026, 7, 10),
        "extension",
        "Chrome 拡張 ext-v0.2.5",
        -2026071001,
        "/ext-install",
    ),
    "ext-v0.3.0.md": (
        "ext-v0.3.0",
        date(2026, 7, 31),
        "extension",
        "Chrome 拡張 ext-v0.3.0",
        -2026073101,
        "/ext-install",
    ),
}
REQUIRED_HEADINGS = (
    "## 30 秒サマリー",
    "## アップデート方法",
    "## 新機能",
    "## 改善",
    "## 直った不具合",
    "## 詳しい変更内容",
)


def _read_note(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: YAML frontmatter がありません"
    _, frontmatter, body = text.split("---\n", 2)
    metadata = yaml.safe_load(frontmatter)
    assert isinstance(metadata, dict), f"{path}: frontmatter は mapping が必要です"
    return metadata, body


def test_release_notes_define_the_public_content_contract() -> None:
    contract = (ROOT / "docs" / "release-notes.md").read_text(encoding="utf-8")

    for key in ("title", "version", "released_at", "kind", "summary", "sidebar.order"):
        assert f"`{key}`" in contract
    for heading in REQUIRED_HEADINGS:
        assert f"`{heading.removeprefix('## ')}`" in contract
    assert "`main`" in contract
    assert "`extension`" in contract


def test_release_notes_have_the_expected_initial_entries() -> None:
    assert {path.name for path in NOTES_DIR.glob("*.md")} == set(EXPECTED_NOTES)


@pytest.mark.parametrize("filename", EXPECTED_NOTES)
def test_release_note_matches_frontmatter_and_body_contract(filename: str) -> None:
    expected_version, expected_date, expected_kind, expected_title, expected_order, command = EXPECTED_NOTES[filename]
    metadata, body = _read_note(NOTES_DIR / filename)

    assert set(metadata) == {"title", "version", "released_at", "kind", "summary", "sidebar"}
    assert metadata["title"] == expected_title
    assert metadata["version"] == expected_version
    assert metadata["released_at"] == expected_date
    assert metadata["kind"] == expected_kind
    assert isinstance(metadata["summary"], str) and metadata["summary"].strip()
    assert metadata["sidebar"] == {"order": expected_order}
    assert Path(filename).stem == expected_version
    assert not body.lstrip().startswith("# "), "ページタイトルは Blume に一度だけ描画させる"
    assert f"```text\n{command}\n```" in body

    for heading in REQUIRED_HEADINGS:
        assert heading in body
    assert f"https://github.com/daiki-beppu/youtube-automation/releases/tag/{expected_version}" in body


@pytest.mark.parametrize("filename", EXPECTED_NOTES)
def test_release_note_uses_public_web_markdown(filename: str) -> None:
    _, body = _read_note(NOTES_DIR / filename)

    assert not {"■", "★", "・"}.intersection(body)
    assert body.count("```text") == 1
    assert body.count("```") == 2
    assert not re.search(r"(?<!\w)#\d+", body), "issue・PR 番号を本文へ出さない"
    assert "/pull/" not in body
    assert "libecity.com" not in body
