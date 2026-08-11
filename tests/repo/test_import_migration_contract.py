"""Migration の import path 対応表フォーマットを検証する。"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

_CONTRACT_PATH = REPO_ROOT / "docs" / "changelog-contract.md"
_CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
_RELEASE_SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "automation-release" / "SKILL.md"
_PREPARE_CHECKLIST_PATH = (
    REPO_ROOT / ".claude" / "skills" / "automation-release" / "references" / "prepare-checklist.md"
)
_AUDIT_CONTRACT_START = "<!-- import-migration-audit-contract:start -->"
_AUDIT_CONTRACT_END = "<!-- import-migration-audit-contract:end -->"
_SECTION_HEADING = "## Migration の import path 対応表"
_MOVE_MARKER = "Python module 移動: あり"
_NO_MOVE_MARKER = "Python module 移動: なし"
_FACADE_MARKER = "互換 facade: なし"
_TABLE_HEADER = "| 旧 import path | 新 import path |"
_REDESIGN_MARKER = "Python module 再設計: あり"
_REDESIGN_TABLE_HEADER = "| 削除された import path | 移行区分 | 参考 module（置換先ではない） |"
_REDESIGN_CLASSIFICATION = "1 対 1 代替なし（再設計）"
_MODULE_PATH_PATTERN = re.compile(r"youtube_automation(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
_ROW_PATTERN = re.compile(r"\| `([^`]+)` \| `([^`]+)` \|")
_REDESIGN_ROW_PATTERN = re.compile(rf"\| `([^`]+)` \| {_REDESIGN_CLASSIFICATION} \| `([^`]+)` \|")
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
_V560_REDESIGN_MAPPINGS = [
    (
        f"{_LEGACY_UTILS_PREFIX}.upload_core",
        "youtube_automation.infrastructure.google.upload",
        "create_media_upload",
    ),
    (
        f"{_LEGACY_UTILS_PREFIX}.youtube_service",
        "youtube_automation.infrastructure.google.youtube",
        "create_authenticated_youtube_clients",
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


def _import_audit_contract(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(_AUDIT_CONTRACT_START)
    end = text.index(_AUDIT_CONTRACT_END, start)
    return text[start + len(_AUDIT_CONTRACT_START) : end].strip()


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


def test_redesign_example_has_a_distinct_non_replacement_row_format() -> None:
    examples = _markdown_examples()
    redesign_example = next(example for example in examples if example.startswith(_REDESIGN_MARKER))
    lines = redesign_example.splitlines()
    rows = [_REDESIGN_ROW_PATTERN.fullmatch(line) for line in lines]
    mappings = [match.groups() for match in rows if match is not None]

    assert _REDESIGN_TABLE_HEADER in lines
    assert "|---|---|---|" in lines
    assert mappings
    for removed_path, reference_path in mappings:
        assert _MODULE_PATH_PATTERN.fullmatch(removed_path)
        assert _MODULE_PATH_PATTERN.fullmatch(reference_path)
        assert removed_path != reference_path


def test_redesign_contract_does_not_represent_a_reference_as_a_replacement() -> None:
    section = _contract_section()

    assert "1 対 1 移動の対応表とは分けて" in section
    assert "参考 module は置換先ではない" in section
    assert "class ベースから関数ベース" in section


def test_v560_migration_lists_the_facade_less_import_mappings() -> None:
    migration = _v560_migration_section()
    rows = [_ROW_PATTERN.fullmatch(line) for line in migration.splitlines()]
    mappings = [match.groups() for match in rows if match is not None]

    assert _MOVE_MARKER in migration
    assert _FACADE_MARKER in migration
    assert mappings == _V560_IMPORT_MAPPINGS


def test_v560_migration_lists_the_modules_removed_by_redesign() -> None:
    migration = _v560_migration_section()
    rows = [_REDESIGN_ROW_PATTERN.fullmatch(line) for line in migration.splitlines()]
    mappings = [match.groups() for match in rows if match is not None]
    expected = [(removed_path, reference_path) for removed_path, reference_path, _ in _V560_REDESIGN_MAPPINGS]

    assert _REDESIGN_MARKER in migration
    assert mappings == expected
    assert "class ベースから関数ベース" in migration
    assert "1 対 1 の置き換えではない" in migration


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


def test_v560_removed_modules_are_unimportable_and_reference_apis_are_importable() -> None:
    legacy_paths = [old_path for old_path, _, _ in _V560_REDESIGN_MAPPINGS]
    reference_apis = [(module_path, symbol) for _, module_path, symbol in _V560_REDESIGN_MAPPINGS]
    script = "\n".join(
        [
            "import importlib",
            f"legacy_paths = {legacy_paths!r}",
            "for path in legacy_paths:",
            "    try:",
            "        importlib.import_module(path)",
            "    except ModuleNotFoundError as exc:",
            "        assert exc.name == path, (path, exc.name)",
            "    else:",
            "        raise AssertionError(f'{path} must not be importable')",
            f"reference_apis = {reference_apis!r}",
            "for module_path, symbol in reference_apis:",
            "    module = importlib.import_module(module_path)",
            "    assert callable(getattr(module, symbol))",
        ]
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_release_prepare_distributes_the_import_migration_audit_contract() -> None:
    skill_contract = _import_audit_contract(_RELEASE_SKILL_PATH)
    checklist_contract = _import_audit_contract(_PREPARE_CHECKLIST_PATH)

    assert skill_contract == checklist_contract
    for required_contract in (
        'git diff --find-renames --name-status "${previous_tag}..HEAD" -- src/youtube_automation',
        "手動 D/A pairing",
        "documented / exported / known-downstream-use",
        "fully-qualified",
        _MOVE_MARKER,
        _FACADE_MARKER,
        _NO_MOVE_MARKER,
        "未記載なら release prepare を停止",
    ):
        assert required_contract in skill_contract


def test_release_prepare_audits_unreleased_before_changelog_promotion() -> None:
    skill = _RELEASE_SKILL_PATH.read_text(encoding="utf-8")
    audit_position = skill.index(_AUDIT_CONTRACT_START)
    promotion_position = skill.index("#### 1-4. CHANGELOG.md の昇格")

    assert "`[Unreleased]` の `### Migration`" in _import_audit_contract(_RELEASE_SKILL_PATH)
    assert audit_position < promotion_position
