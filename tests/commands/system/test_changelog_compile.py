from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.commands.system.changelog_compile import compile_fragments
from youtube_automation.core.errors import ConfigError

_BASE_CHANGELOG = """# Changelog

## [Unreleased]

## [1.0.0] - 2026-01-01

### Fixed

- old
"""


def _setup(tmp_path: Path, changelog: str = _BASE_CHANGELOG) -> tuple[Path, Path]:
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(changelog, encoding="utf-8")
    fragments_dir = tmp_path / "changelog.d"
    fragments_dir.mkdir()
    return changelog_path, fragments_dir


def test_compiles_mixed_fragments_in_contract_order_and_deletes_them(tmp_path: Path) -> None:
    changelog, fragments = _setup(tmp_path)
    (fragments / "1-feature.added.md").write_text("- feature\n", encoding="utf-8")
    (fragments / "2-bug.fixed.md").write_text("- bug fix\n", encoding="utf-8")

    compile_fragments(changelog, fragments)

    result = changelog.read_text(encoding="utf-8")
    unreleased = result.split("## [1.0.0]", maxsplit=1)[0]
    assert unreleased.index("### Added") < unreleased.index("### Fixed")
    assert "- feature" in unreleased
    assert "- bug fix" in unreleased
    assert list(fragments.glob("*.md")) == []


def test_appends_to_existing_heading_without_duplicate(tmp_path: Path) -> None:
    source = _BASE_CHANGELOG.replace("## [1.0.0]", "### Fixed\n\n- existing\n\n## [1.0.0]")
    changelog, fragments = _setup(tmp_path, source)
    (fragments / "2-bug.fixed.md").write_text("- new fix\n", encoding="utf-8")

    compile_fragments(changelog, fragments)

    unreleased = changelog.read_text(encoding="utf-8").split("## [1.0.0]", maxsplit=1)[0]
    assert unreleased.count("### Fixed") == 1
    assert "- existing\n\n- new fix" in unreleased


def test_migration_is_added_only_below_summary(tmp_path: Path) -> None:
    source = _BASE_CHANGELOG.replace(
        "## [1.0.0]",
        "### Migration\n\n所要時間の目安: 10 分\n\nサマリ:\n\n- existing\n\n## [1.0.0]",
    )
    changelog, fragments = _setup(tmp_path, source)
    (fragments / "3-move.migration.md").write_text("- move module\n", encoding="utf-8")

    compile_fragments(changelog, fragments)

    unreleased = changelog.read_text(encoding="utf-8").split("## [1.0.0]", maxsplit=1)[0]
    assert unreleased.count("所要時間の目安") == 1
    assert unreleased.index("サマリ:") < unreleased.index("- move module")


def test_no_fragments_is_noop(tmp_path: Path) -> None:
    changelog, fragments = _setup(tmp_path)
    before = changelog.read_bytes()
    assert compile_fragments(changelog, fragments) is None
    assert changelog.read_bytes() == before


def test_invalid_type_raises_domain_error(tmp_path: Path) -> None:
    changelog, fragments = _setup(tmp_path)
    (fragments / "4-task.chore.md").write_text("- task\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="不正な changelog fragment"):
        compile_fragments(changelog, fragments)


def test_dry_run_leaves_changelog_and_fragment_unchanged(tmp_path: Path) -> None:
    changelog, fragments = _setup(tmp_path)
    fragment = fragments / "5-feature.added.md"
    fragment.write_text("- feature\n", encoding="utf-8")
    before = changelog.read_bytes()

    preview = compile_fragments(changelog, fragments, dry_run=True)

    assert preview is not None and "- feature" in preview
    assert changelog.read_bytes() == before
    assert fragment.exists()


def test_second_run_is_idempotent(tmp_path: Path) -> None:
    changelog, fragments = _setup(tmp_path)
    (fragments / "6-feature.added.md").write_text("- feature\n", encoding="utf-8")
    compile_fragments(changelog, fragments)
    once = changelog.read_bytes()
    assert compile_fragments(changelog, fragments) is None
    assert changelog.read_bytes() == once


def test_readme_is_ignored(tmp_path: Path) -> None:
    changelog, fragments = _setup(tmp_path)
    (fragments / "README.md").write_text("guide", encoding="utf-8")
    before = changelog.read_bytes()
    assert compile_fragments(changelog, fragments) is None
    assert changelog.read_bytes() == before
