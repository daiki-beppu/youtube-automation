"""Gemini CLI の subprocess 起動経路が再導入されないことを検証する。"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

SRC_ROOT = REPO_ROOT / "src"


def _python_sources() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def _is_gemini_string(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "gemini"


def _command_starts_with_gemini(node: ast.AST) -> bool:
    return isinstance(node, (ast.List, ast.Tuple)) and bool(node.elts) and _is_gemini_string(node.elts[0])


def test_src_does_not_invoke_gemini_cli() -> None:
    violations: list[str] = []

    for path in _python_sources():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if "@google/gemini-cli" in source:
            violations.append(f"{path}: @google/gemini-cli")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "which" and _is_gemini_string(node.args[0]):
                violations.append(f"{path}:{node.lineno}: gemini executable lookup")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"run", "Popen", "check_call", "check_output"}
                and _command_starts_with_gemini(node.args[0])
            ):
                violations.append(f"{path}:{node.lineno}: gemini subprocess invocation")

    assert not violations, "\n".join(violations)
