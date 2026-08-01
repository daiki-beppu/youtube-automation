"""公開リリースノートのコンテンツ契約を検証する。"""

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
NOTES_DIR = ROOT / "docs" / "release-notes"
EXPECTED_NOTES = {
    "v5.5.17.md": ("v5.5.17", date(2026, 7, 10), "main"),
    "v5.6.0.md": ("v5.6.0", date(2026, 7, 31), "main"),
    "ext-v0.2.5.md": ("ext-v0.2.5", date(2026, 7, 10), "extension"),
    "ext-v0.3.0.md": ("ext-v0.3.0", date(2026, 7, 31), "extension"),
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

    for key in ("version", "released_at", "kind", "summary"):
        assert f"`{key}`" in contract
    for heading in REQUIRED_HEADINGS:
        assert f"`{heading.removeprefix('## ')}`" in contract
    assert "`main`" in contract
    assert "`extension`" in contract


def test_release_notes_have_the_expected_initial_entries() -> None:
    assert {path.name for path in NOTES_DIR.glob("*.md")} == set(EXPECTED_NOTES)


@pytest.mark.parametrize("filename", EXPECTED_NOTES)
def test_release_note_matches_frontmatter_and_body_contract(filename: str) -> None:
    expected_version, expected_date, expected_kind = EXPECTED_NOTES[filename]
    metadata, body = _read_note(NOTES_DIR / filename)

    assert set(metadata) == {"version", "released_at", "kind", "summary"}
    assert metadata["version"] == expected_version
    assert metadata["released_at"] == expected_date
    assert metadata["kind"] == expected_kind
    assert isinstance(metadata["summary"], str) and metadata["summary"].strip()
    assert Path(filename).stem == expected_version

    for heading in REQUIRED_HEADINGS:
        assert heading in body
    assert f"https://github.com/daiki-beppu/youtube-automation/releases/tag/{expected_version}" in body


@pytest.mark.parametrize("filename", EXPECTED_NOTES)
def test_release_note_uses_public_web_markdown(filename: str) -> None:
    _, body = _read_note(NOTES_DIR / filename)

    assert not {"■", "★", "・"}.intersection(body)
    assert "```" not in body
    assert not re.search(r"(?<!\w)#\d+", body), "issue・PR 番号を本文へ出さない"
    assert "/pull/" not in body
    assert "libecity.com" not in body
