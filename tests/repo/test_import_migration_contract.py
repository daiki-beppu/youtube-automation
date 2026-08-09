"""Migration の import path 対応表フォーマットを検証する。"""

from __future__ import annotations

import re
import subprocess
import sys

from tests.helpers.paths import REPO_ROOT

_CONTRACT_PATH = REPO_ROOT / "docs" / "changelog-contract.md"
_CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
_SECTION_HEADING = "## Migration の import path 対応表"
_MOVE_MARKER = "Python module 移動: あり"
_NO_MOVE_MARKER = "Python module 移動: なし"
_FACADE_MARKER = "互換 facade: なし"
_TABLE_HEADER = "| 旧 import path | 新 import path |"
_MODULE_PATH_PATTERN = re.compile(r"youtube_automation(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
_ROW_PATTERN = re.compile(r"\| `([^`]+)` \| `([^`]+)` \|")
_LEGACY_UTILS_PREFIX = "youtube_automation." + "utils"
_V560_IMPORT_MAPPINGS = [
    (
        "youtube_automation.auth.oauth_handler",
        "youtube_automation.infrastructure.auth.youtube",
    ),
    (f"{_LEGACY_UTILS_PREFIX}.config", "youtube_automation.configuration"),
    (
        f"{_LEGACY_UTILS_PREFIX}.descriptions_md",
        "youtube_automation.domains.metadata.descriptions",
    ),
    (
        f"{_LEGACY_UTILS_PREFIX}.preflight_checks",
        "youtube_automation.domains.uploads.preflight",
    ),
]


def _contract_section() -> str:
    text = _CONTRACT_PATH.read_text(encoding="utf-8")
    start = text.index(_SECTION_HEADING)
    next_section = text.find("\n## ", start + len(_SECTION_HEADING))
    return text[start:] if next_section == -1 else text[start:next_section]


def _markdown_examples() -> list[str]:
    return re.findall(r"```markdown\n(.*?)\n```", _contract_section(), flags=re.DOTALL)


def _v560_migration_section() -> str:
    text = _CHANGELOG_PATH.read_text(encoding="utf-8")
    release_start = text.index("## [5.6.0]")
    release_end = text.index("\n## [", release_start + 1)
    release = text[release_start:release_end]
    migration_start = release.index("### Migration")
    return release[migration_start:]


def test_facade_less_move_example_uses_exact_markers_and_columns() -> None:
    examples = _markdown_examples()
    move_example = next(example for example in examples if example.startswith(_MOVE_MARKER))
    lines = move_example.splitlines()

    assert lines[:2] == [_MOVE_MARKER, _FACADE_MARKER]
    assert _TABLE_HEADER in lines
    assert "|---|---|" in lines


def test_facade_less_move_example_uses_fully_qualified_module_paths() -> None:
    examples = _markdown_examples()
    move_example = next(example for example in examples if example.startswith(_MOVE_MARKER))
    rows = [_ROW_PATTERN.fullmatch(line) for line in move_example.splitlines()]
    mappings = [match.groups() for match in rows if match is not None]

    assert mappings
    for old_path, new_path in mappings:
        assert _MODULE_PATH_PATTERN.fullmatch(old_path)
        assert _MODULE_PATH_PATTERN.fullmatch(new_path)
        assert old_path != new_path


def test_no_move_example_is_a_distinct_table_free_state() -> None:
    examples = _markdown_examples()
    no_move_example = next(example for example in examples if example.startswith(_NO_MOVE_MARKER))

    assert no_move_example == _NO_MOVE_MARKER
    assert _TABLE_HEADER not in no_move_example
    assert _FACADE_MARKER not in no_move_example


def test_v560_migration_lists_the_facade_less_import_mappings() -> None:
    migration = _v560_migration_section()
    rows = [_ROW_PATTERN.fullmatch(line) for line in migration.splitlines()]
    mappings = [match.groups() for match in rows if match is not None]

    assert _MOVE_MARKER in migration
    assert _FACADE_MARKER in migration
    assert mappings == _V560_IMPORT_MAPPINGS


def test_v560_canonical_import_paths_are_importable_in_subprocess() -> None:
    canonical_paths = [new_path for _, new_path in _V560_IMPORT_MAPPINGS]
    script = "\n".join(["import importlib", *(f'importlib.import_module("{path}")' for path in canonical_paths)])

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
