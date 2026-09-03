"""公開リリースノートのコンテンツ契約を検証する。"""

import re
from datetime import date
from itertools import pairwise
from pathlib import Path

import pytest
import yaml

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
NOTES_DIR = ROOT / "docs" / "release-notes"
NOTE_PATHS = tuple(sorted(NOTES_DIR.glob("*.md")))
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


def test_release_notes_directory_is_non_empty_and_uses_release_tag_filenames() -> None:
    assert NOTE_PATHS
    for path in NOTE_PATHS:
        assert re.fullmatch(r"(?:ext-)?v\d+\.\d+\.\d+", path.stem), path


@pytest.mark.parametrize("path", NOTE_PATHS, ids=lambda path: path.name)
def test_release_note_matches_frontmatter_and_body_contract(path: Path) -> None:
    _assert_frontmatter_and_body_contract(path)


def _assert_frontmatter_and_body_contract(path: Path) -> None:
    metadata, body = _read_note(path)

    assert set(metadata) == {"title", "version", "released_at", "kind", "summary", "sidebar"}
    assert isinstance(metadata["title"], str) and metadata["title"].strip()
    assert metadata["version"] == path.stem
    assert isinstance(metadata["released_at"], date)
    assert metadata["kind"] in {"main", "extension"}
    assert isinstance(metadata["summary"], str) and metadata["summary"].strip()
    assert isinstance(metadata["sidebar"], dict)
    assert set(metadata["sidebar"]) == {"order"}
    assert isinstance(metadata["sidebar"]["order"], int)
    assert metadata["sidebar"]["order"] < 0
    assert not body.lstrip().startswith("# "), "ページタイトルは Blume に一度だけ描画させる"
    command = "/automation --update" if metadata["kind"] == "main" else "/ext-install"
    assert f"```text\n{command}\n```" in body

    for heading in REQUIRED_HEADINGS:
        assert heading in body
    assert f"https://github.com/daiki-beppu/youtube-automation/releases/tag/{path.stem}" in body


def _assert_sidebar_order(paths: tuple[Path, ...]) -> None:
    metadatas = [_read_note(path)[0] for path in paths]
    contract_order = sorted(
        metadatas,
        key=lambda metadata: (
            -metadata["released_at"].toordinal(),
            0 if metadata["kind"] == "main" else 1,
        ),
    )
    sidebar_orders = [metadata["sidebar"]["order"] for metadata in contract_order]

    assert all(left < right for left, right in pairwise(sidebar_orders))


def test_release_note_sidebar_order_follows_the_public_contract() -> None:
    _assert_sidebar_order(NOTE_PATHS)


@pytest.mark.parametrize("path", NOTE_PATHS, ids=lambda path: path.name)
def test_release_note_uses_public_web_markdown(path: Path) -> None:
    _assert_public_web_markdown(path)


def _assert_public_web_markdown(path: Path) -> None:
    _, body = _read_note(path)

    assert not {"■", "★", "・"}.intersection(body)
    assert body.count("```text") == 1
    assert body.count("```") == 2
    assert not re.search(r"(?<!\w)#\d+", body), "issue・PR 番号を本文へ出さない"
    assert "/pull/" not in body
    assert "libecity.com" not in body


def _write_fixture_note(
    path: Path,
    *,
    body: str = "",
    order: int = -1,
    released_at: str = "2026-09-01",
    kind: str = "main",
    version: str | None = None,
) -> Path:
    """契約を満たす fixture ノートを書き出す。違反は引数で 1 項目だけ差し替える。"""
    path.write_text(
        "\n".join(
            (
                "---",
                'title: "Fixture"',
                f"version: {version if version is not None else path.stem}",
                f"released_at: {released_at}",
                f"kind: {kind}",
                'summary: "Fixture"',
                "sidebar:",
                f"  order: {order}",
                "---",
                body,
            )
        ),
        encoding="utf-8",
    )
    return path


def _fixture_body(version: str, *, kind: str = "main", omit_heading: str | None = None) -> str:
    command = "/automation --update" if kind == "main" else "/ext-install"
    sections: list[str] = []
    for heading in REQUIRED_HEADINGS:
        if heading == omit_heading:
            continue
        sections.append(heading)
        sections.append(f"```text\n{command}\n```" if heading == "## アップデート方法" else "本文")
    sections.append(f"https://github.com/daiki-beppu/youtube-automation/releases/tag/{version}")
    return "\n\n".join(sections) + "\n"


def test_release_note_fixture_baseline_satisfies_the_contract(tmp_path: Path) -> None:
    """違反 fixture の対照群。ここが緑でないと「1 項目の違反で落ちた」と言えない。"""
    baseline = _write_fixture_note(tmp_path / "v1.0.0.md", body=_fixture_body("v1.0.0"))

    _assert_frontmatter_and_body_contract(baseline)
    _assert_public_web_markdown(baseline)

    extension = _write_fixture_note(
        tmp_path / "ext-v1.0.0.md",
        body=_fixture_body("ext-v1.0.0", kind="extension"),
        kind="extension",
    )
    _assert_frontmatter_and_body_contract(extension)
    _assert_public_web_markdown(extension)


def test_release_note_contract_rejects_version_mismatch(tmp_path: Path) -> None:
    note = _write_fixture_note(tmp_path / "v1.0.0.md", body=_fixture_body("v1.0.0"), version="v1.0.1")

    with pytest.raises(AssertionError):
        _assert_frontmatter_and_body_contract(note)


def test_release_note_contract_rejects_non_date_released_at(tmp_path: Path) -> None:
    note = _write_fixture_note(tmp_path / "v1.0.0.md", body=_fixture_body("v1.0.0"), released_at='"invalid"')

    with pytest.raises(AssertionError):
        _assert_frontmatter_and_body_contract(note)


def test_release_note_contract_rejects_missing_heading(tmp_path: Path) -> None:
    note = _write_fixture_note(tmp_path / "v1.0.0.md", body=_fixture_body("v1.0.0", omit_heading="## 改善"))

    with pytest.raises(AssertionError):
        _assert_frontmatter_and_body_contract(note)


def test_release_note_contract_rejects_internal_notation(tmp_path: Path) -> None:
    note = _write_fixture_note(tmp_path / "v1.0.0.md", body=_fixture_body("v1.0.0") + "\n・内部表記\n")

    with pytest.raises(AssertionError):
        _assert_public_web_markdown(note)


def test_release_note_sidebar_order_accepts_contract_conforming_fixtures(tmp_path: Path) -> None:
    newer = _write_fixture_note(tmp_path / "v1.1.0.md", released_at="2026-09-02", order=-3)
    same_day_main = _write_fixture_note(tmp_path / "v1.0.0.md", released_at="2026-09-01", order=-2)
    same_day_extension = _write_fixture_note(
        tmp_path / "ext-v1.0.0.md", released_at="2026-09-01", kind="extension", order=-1
    )

    _assert_sidebar_order((same_day_extension, newer, same_day_main))


def test_release_note_contract_rejects_reversed_released_at_order(tmp_path: Path) -> None:
    """公開日が新しいノートに大きい order を与えると落ちる（日付方向の逆転）。"""
    newer = _write_fixture_note(tmp_path / "v1.1.0.md", released_at="2026-09-02", order=-1)
    older = _write_fixture_note(tmp_path / "v1.0.0.md", released_at="2026-09-01", order=-2)

    # 日付キーを落とした退行では入力順のまま昇順になり、この raises が失敗して退行を検出する
    with pytest.raises(AssertionError):
        _assert_sidebar_order((older, newer))


def test_release_note_contract_rejects_reversed_same_day_kind_order(tmp_path: Path) -> None:
    """同じ公開日で拡張が本体より小さい order を持つと落ちる（kind タイブレークの逆転）。"""
    newer = _write_fixture_note(tmp_path / "v1.1.0.md", released_at="2026-09-02", order=-3)
    same_day_main = _write_fixture_note(tmp_path / "v1.0.0.md", released_at="2026-09-01", order=-1)
    same_day_extension = _write_fixture_note(
        tmp_path / "ext-v1.0.0.md", released_at="2026-09-01", kind="extension", order=-2
    )

    # kind キーを落とした退行では入力順のまま昇順になり、この raises が失敗して退行を検出する
    with pytest.raises(AssertionError):
        _assert_sidebar_order((newer, same_day_extension, same_day_main))
