"""Skill 契約テストが inventory domain を迂回して走査を再実装しないための gate。"""

from __future__ import annotations

import ast

from tests.helpers.paths import REPO_ROOT

_REPO_TESTS = REPO_ROOT / "tests" / "repo"
_GATE_RELATIVE_PATH = "test_skill_inventory_gate.py"

# #3903 時点の既存実装を凍結する ratchet。解消されたファイルは削除できるが、
# 新しいファイルを追加して inventory への移行を先送りしてはならない。
_LEGACY_SKILL_SCAN_ALLOWLIST = frozenset(
    {
        "test_analytics_consolidation.py",
        "test_analytics_run_state.py",
        "test_flop_analysis_skill_contract.py",
        "test_lifecycle_skills_no_tayk.py",
        "test_live_chat_reply_skill_contract.py",
        "test_production_quality_setup_redirect_contract.py",
        "test_release_notes_contract.py",
        "test_research_persona_setup_handoff_contract.py",
        "test_scripts_layout.py",
        "test_setup_channel_disclosure_contract.py",
        "test_shadcn_skill_contract.py",
        "test_skill_cost_documentation.py",
        "test_skill_page_generation_contract.py",
        "test_skill_shell_reference_runtime.py",
        "test_skills_rename.py",
        "test_unattended_approval_skip_contract.py",
        "test_workflow_upload_setup_redirect_contract.py",
    }
)


def _string_path_parts(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return (*_string_path_parts(node.left), *_string_path_parts(node.right))
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return tuple(part for part in node.value.replace("\\", "/").split("/") if part)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Path"
        and len(node.args) == 1
    ):
        return _string_path_parts(node.args[0])
    return ()


def _defines_skills_root(node: ast.AST) -> bool:
    if isinstance(node, ast.Assign):
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        value = node.value
    else:
        return False
    return _string_path_parts(value)[-2:] == (".claude", "skills")


def _manually_splits_frontmatter(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "split":
        return False
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return False
    delimiter = node.args[0].value
    return isinstance(delimiter, str) and delimiter.rstrip("\r\n") == "---"


def _manually_parses_frontmatter(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or "frontmatter" not in node.name:
        return False
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr in {"load", "safe_load"}
        for child in ast.walk(node)
    )


def _walks_skills_dir(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "rglob"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_SKILLS_DIR"
    )


def _reimplements_skill_inventory(source: str, *, filename: str) -> bool:
    tree = ast.parse(source, filename=filename)
    mentions_skill_document = "SKILL.md" in source
    return any(
        _defines_skills_root(node)
        or _walks_skills_dir(node)
        or (mentions_skill_document and _manually_splits_frontmatter(node))
        or _manually_parses_frontmatter(node)
        for node in ast.walk(tree)
    )


def test_gate_detects_each_forbidden_inventory_reimplementation() -> None:
    examples = (
        'SKILLS = ROOT / ".claude" / "skills"',
        'SKILLS = Path(".claude/skills")',
        'frontmatter = skill_text.split("---", 2)[1]  # SKILL.md',
        '_SKILLS_DIR.rglob("*")',
    )

    for source in examples:
        assert _reimplements_skill_inventory(source, filename="test_new_contract.py")


def test_gate_accepts_the_shared_skill_inventory() -> None:
    source = (
        "from youtube_automation.domains.skills.inventory import SkillInventory\n"
        "inventory = SkillInventory(REPO_ROOT)\n"
        "skills = inventory.skill_directories()\n"
    )

    assert not _reimplements_skill_inventory(source, filename="test_new_contract.py")


def test_repo_contracts_do_not_add_skill_inventory_reimplementations() -> None:
    offenders = {
        path.relative_to(_REPO_TESTS).as_posix()
        for path in _REPO_TESTS.rglob("*.py")
        if path.relative_to(_REPO_TESTS).as_posix() != _GATE_RELATIVE_PATH
        and _reimplements_skill_inventory(path.read_text(encoding="utf-8"), filename=str(path))
    }

    assert offenders <= _LEGACY_SKILL_SCAN_ALLOWLIST, (
        "tests/repo に skill inventory の再実装が追加された。"
        "SkillInventory / parse_frontmatter を利用すること:\n  "
        + "\n  ".join(sorted(offenders - _LEGACY_SKILL_SCAN_ALLOWLIST))
    )
