"""公開リリースノートの authoring・tag・CI 契約を検証する。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
NOTES_DIR = ROOT / "docs" / "release-notes"
AUTHORING_REFERENCE = ROOT / ".claude" / "skills" / "automation-release" / "references" / "release-notes-authoring.md"
REQUIRED_FRONTMATTER_KEYS = {"title", "version", "released_at", "kind", "summary", "sidebar"}
REQUIRED_HEADINGS = (
    "## 30 秒サマリー",
    "## アップデート方法",
    "## 新機能",
    "## 改善",
    "## 直った不具合",
    "## 詳しい変更内容",
)
RELEASE_URL_PREFIX = "https://github.com/daiki-beppu/youtube-automation/releases/tag/"


def _read_note(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: YAML frontmatter がありません"
    _, frontmatter, body = text.split("---\n", 2)
    metadata = yaml.safe_load(frontmatter)
    assert isinstance(metadata, dict), f"{path}: frontmatter は mapping が必要です"
    return metadata, body


def _repository_tags() -> frozenset[str]:
    result = subprocess.run(
        ["git", "tag", "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(result.stdout.splitlines())


def _validate_release_note(path: Path, repository_tags: frozenset[str]) -> None:
    metadata, body = _read_note(path)
    version = metadata.get("version")

    assert set(metadata) == REQUIRED_FRONTMATTER_KEYS
    assert isinstance(version, str) and version
    assert isinstance(metadata["sidebar"], dict) and set(metadata["sidebar"]) == {"order"}
    assert path.stem == version, f"{path}: filename と frontmatter version が一致しません"
    assert version in repository_tags, f"{path}: version は実在する git tag が必要です: {version}"
    release_tags = re.findall(rf"{re.escape(RELEASE_URL_PREFIX)}([^\s)]+)", body)
    assert release_tags == [version], f"{path}: GitHub Release link は同一 tag を1件だけ指す必要があります"
    assert not body.lstrip().startswith("# ")

    heading_positions = [body.index(heading) for heading in REQUIRED_HEADINGS]
    assert heading_positions == sorted(heading_positions), f"{path}: 必須見出しの順序が不正です"
    assert all(body.count(heading) == 1 for heading in REQUIRED_HEADINGS)
    assert not re.search(r"(?<!\w)#\d+", body), f"{path}: issue・PR 番号を本文へ出してはいけません"
    assert "/pull/" not in body


def test_release_notes_authoring_reference_is_self_contained() -> None:
    reference = AUTHORING_REFERENCE.read_text(encoding="utf-8")

    for required in (
        "対象 version の `CHANGELOG.md` section",
        "同一 tag の GitHub Release body",
        "filename / frontmatter `version` / GitHub Release link",
        "`title` / `version` / `released_at` / `kind` / `summary` / `sidebar`",
        "運営者への影響がある項目を全件保持",
        "内部実装・issue・PR 番号",
        "専用 branch",
        "pull request",
        "preview",
        "`lint` / `test`",
        "main へ直接 push しない",
        "publish flow は接続しない",
    ):
        assert required in reference

    heading_positions = [reference.index(heading) for heading in REQUIRED_HEADINGS]
    assert heading_positions == sorted(heading_positions)


def test_existing_release_notes_match_real_tags_and_public_contract() -> None:
    tags = _repository_tags()
    notes = sorted(NOTES_DIR.glob("*.md"))

    assert len(notes) == 4
    for note in notes:
        _validate_release_note(note, tags)


def test_release_note_rejects_nonexistent_tag(tmp_path: Path) -> None:
    version = "v999.999.999"
    note = tmp_path / f"{version}.md"
    note.write_text(
        "---\n"
        'title: "nonexistent release"\n'
        f"version: {version}\n"
        "released_at: 2099-01-01\n"
        "kind: main\n"
        'summary: "tag validation fixture"\n'
        "sidebar:\n"
        "  order: -2099010102\n"
        "---\n\n" + "\n\n".join(REQUIRED_HEADINGS) + f"\n\n[GitHub Release]({RELEASE_URL_PREFIX}{version})\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="実在する git tag"):
        _validate_release_note(note, _repository_tags())


def test_ci_python_test_checkout_fetches_full_tag_history() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    test_job = workflow["jobs"]["test"]
    checkout = next(step for step in test_job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@"))

    assert checkout["with"]["fetch-depth"] == 0
