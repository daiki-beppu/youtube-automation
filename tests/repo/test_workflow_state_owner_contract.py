"""workflow-state.json の owner 外 direct I/O を削減方向へ固定する。"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

OWNER = "src/youtube_automation/domains/collections/workflow_state.py"
DIRECT_IO_ALLOWLIST = frozenset(
    {
        "src/youtube_automation/commands/analytics/experiment_judge.py",
        "src/youtube_automation/commands/distrokid/distrokid_prepare.py",
        "src/youtube_automation/commands/system/progress_hook/workflow_state.py",
        "src/youtube_automation/commands/youtube/pinned_comment.py",
        "src/youtube_automation/domains/distrokid/release.py",
        "src/youtube_automation/domains/suno/prompt_resolution.py",
        "src/youtube_automation/infrastructure/analytics/workflow_timing.py",
    }
)

_PATH_NAME = re.compile(r"(?:workflow_state|workflow|ws)_(?:file|path)$")
_CONTEXTUAL_PATH_NAME = re.compile(r"state_(?:file|path)$")
_PATH_METHODS = frozenset({"open", "read_bytes", "read_text", "unlink", "write_bytes", "write_text"})
_FILE_HELPERS = frozenset({"read_file_text", "read_json", "replace_file", "write_file_text", "write_json"})


@dataclass(frozen=True, order=True)
class DirectWorkflowStateIO:
    path: str = ""
    line: int = 0
    operation: str = ""

    def diagnostic(self) -> str:
        return f"{self.path}:{self.line}: {self.operation} bypasses domains.collections.workflow_state"


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.List, ast.Tuple)):
        return {name for item in target.elts for name in _target_names(item)}
    return set()


def _references_workflow_state(node: ast.AST, tainted: set[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if "workflow-state.json" in child.value:
                return True
        elif isinstance(child, ast.Name) and (child.id in tainted or _PATH_NAME.fullmatch(child.id)):
            return True
        elif isinstance(child, ast.Attribute) and child.attr == "workflow_state_path":
            return True
    return False


_SCOPE_NODES = (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef, ast.Lambda)


def _nodes_in_scope(scope: ast.AST) -> tuple[ast.AST, ...]:
    nodes: list[ast.AST] = []

    class ScopeVisitor(ast.NodeVisitor):
        def visit(self, node: ast.AST) -> None:
            if node is not scope and isinstance(node, _SCOPE_NODES):
                return
            nodes.append(node)
            super().visit(node)

    ScopeVisitor().visit(scope)
    return tuple(nodes)


def _is_path_expression(node: ast.AST, tainted: set[str]) -> bool:
    if not _references_workflow_state(node, tainted):
        return False
    return not any(
        isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr in _PATH_METHODS
        for child in ast.walk(node)
    )


def _tainted_path_names(nodes: tuple[ast.AST, ...], seeds: set[str] | None = None) -> set[str]:
    tainted = set() if seeds is None else set(seeds)
    assignments: list[tuple[set[str], ast.AST]] = []
    for node in nodes:
        if isinstance(node, ast.Assign):
            names = {name for target in node.targets for name in _target_names(target)}
            assignments.append((names, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assignments.append((_target_names(node.target), node.value))

    changed = True
    while changed:
        changed = False
        for names, value in assignments:
            if names - tainted and _is_path_expression(value, tainted):
                tainted.update(names)
                changed = True
    return tainted


def _call_operation(call: ast.Call, tainted: set[str]) -> str | None:
    function = call.func
    if isinstance(function, ast.Attribute):
        if function.attr in _PATH_METHODS and _references_workflow_state(function.value, tainted):
            return function.attr
        if isinstance(function.value, ast.Name) and function.value.id == "os" and function.attr == "replace":
            if any(_references_workflow_state(argument, tainted) for argument in call.args):
                return "os.replace"
    elif isinstance(function, ast.Name):
        if function.id == "open" and call.args and _references_workflow_state(call.args[0], tainted):
            return "open"
        if function.id in _FILE_HELPERS and any(
            _references_workflow_state(argument, tainted) for argument in call.args
        ):
            return function.id
    return None


def _function_parameter_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    arguments = function.args
    return tuple(argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs))


def _scope_taints(tree: ast.Module) -> dict[ast.AST, set[str]]:
    scopes = (tree, *(node for node in ast.walk(tree) if isinstance(node, _SCOPE_NODES)))
    nodes_by_scope = {scope: _nodes_in_scope(scope) for scope in scopes}
    has_workflow_locator = any(
        (isinstance(node, ast.Attribute) and node.attr == "workflow_state_path")
        or (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith("workflow-state.json")
        )
        for node in ast.walk(tree)
    )
    taints = {
        scope: _tainted_path_names(
            nodes,
            {
                node.id
                for node in nodes
                if has_workflow_locator and isinstance(node, ast.Name) and _CONTEXTUAL_PATH_NAME.fullmatch(node.id)
            },
        )
        for scope, nodes in nodes_by_scope.items()
    }
    functions = {
        function.name: function for function in scopes if isinstance(function, (ast.AsyncFunctionDef, ast.FunctionDef))
    }

    changed = True
    while changed:
        changed = False
        for scope, nodes in nodes_by_scope.items():
            for node in nodes:
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                callee = functions.get(node.func.id)
                if callee is None:
                    continue
                parameters = _function_parameter_names(callee)
                newly_tainted = {
                    parameter
                    for parameter, argument in zip(parameters, node.args, strict=False)
                    if _references_workflow_state(argument, taints[scope])
                }
                keyword_arguments = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
                newly_tainted.update(
                    parameter
                    for parameter in parameters
                    if parameter in keyword_arguments
                    and _references_workflow_state(keyword_arguments[parameter], taints[scope])
                )
                if newly_tainted - taints[callee]:
                    taints[callee] = _tainted_path_names(
                        nodes_by_scope[callee],
                        taints[callee] | newly_tainted,
                    )
                    changed = True
    return taints


def _direct_workflow_state_io(repo_root: Path) -> tuple[DirectWorkflowStateIO, ...]:
    source_root = repo_root / "src" / "youtube_automation"
    findings: list[DirectWorkflowStateIO] = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(repo_root).as_posix()
        if relative == OWNER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        taints = _scope_taints(tree)
        for scope, tainted in taints.items():
            nodes = _nodes_in_scope(scope)
            for node in nodes:
                if not isinstance(node, ast.Call):
                    continue
                operation = _call_operation(node, tainted)
                if operation is not None:
                    findings.append(DirectWorkflowStateIO(relative, node.lineno, operation))
    return tuple(sorted(findings))


def _ratchet_diagnostics(
    findings: tuple[DirectWorkflowStateIO, ...],
    allowlist: frozenset[str],
) -> list[str]:
    actual_paths = {finding.path for finding in findings}
    diagnostics = [
        f"new direct workflow-state I/O: {finding.diagnostic()}"
        for finding in findings
        if finding.path not in allowlist
    ]
    diagnostics.extend(
        f"stale workflow-state allowlist entry: {path} (remove this entry)" for path in sorted(allowlist - actual_paths)
    )
    return diagnostics


def test_owner_outside_direct_io_matches_shrinking_allowlist() -> None:
    findings = _direct_workflow_state_io(REPO_ROOT)

    assert _ratchet_diagnostics(findings, DIRECT_IO_ALLOWLIST) == []


def test_new_direct_parse_reports_file_line_and_operation(tmp_path: Path) -> None:
    source = tmp_path / "src" / "youtube_automation" / "commands" / "new_direct_parse.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from pathlib import Path\n"
        "import json\n\n"
        "def load(root: Path):\n"
        "    path = root / 'workflow-state.json'\n"
        "    return json.loads(path.read_text())\n",
        encoding="utf-8",
    )

    findings = _direct_workflow_state_io(tmp_path)

    diagnostics = _ratchet_diagnostics(findings, frozenset())
    assert diagnostics == [
        "new direct workflow-state I/O: "
        "src/youtube_automation/commands/new_direct_parse.py:6: read_text "
        "bypasses domains.collections.workflow_state",
    ]


def test_removed_direct_io_requires_allowlist_entry_removal(tmp_path: Path) -> None:
    source = tmp_path / "src" / "youtube_automation" / "commands" / "migrated.py"
    source.parent.mkdir(parents=True)
    source.write_text("from youtube_automation.domains.collections.workflow_state import read\n", encoding="utf-8")

    findings = _direct_workflow_state_io(tmp_path)

    assert _ratchet_diagnostics(findings, frozenset({"src/youtube_automation/commands/migrated.py"})) == [
        "stale workflow-state allowlist entry: src/youtube_automation/commands/migrated.py (remove this entry)"
    ]
