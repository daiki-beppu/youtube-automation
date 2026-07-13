"""GitHub Actions step 並列化の workflow 契約を静的に検証する。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_EXTENSIONS_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "extensions.yml"
_RELEASE_EXTENSIONS_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "release-extensions.yml"

_CI_LINT_PARALLEL_STEPS = {
    "Ruff check": "nix develop --command uv run ruff check .",
    "Ruff format check": "nix develop --command uv run ruff format --check .",
}

_SUNO_FAST_PARALLEL_STEPS = {
    "Lint": "nix develop .#extensions --command pnpm lint",
    "Format check": "nix develop .#extensions --command pnpm format:check",
    "Type check": "nix develop .#extensions --command pnpm compile",
    "Unit tests (Vitest)": "nix develop .#extensions --command pnpm test",
}
_SUNO_BUILD_PARALLEL_STEPS = {
    "Build": "nix develop .#extensions --command pnpm build",
    "Install Playwright browser": (
        "nix develop .#extensions --command pnpm exec playwright install --with-deps chromium"
    ),
}
_DISTROKID_FAST_PARALLEL_STEPS = {
    "Lint": "nix develop .#extensions --command pnpm lint",
    "Format check": "nix develop .#extensions --command pnpm format:check",
    "Typecheck": "nix develop .#extensions --command pnpm compile",
    "Unit tests (Vitest)": "nix develop .#extensions --command pnpm test",
}
_DISTROKID_BUILD_PARALLEL_STEPS = _SUNO_BUILD_PARALLEL_STEPS
_EXTENSIONS_JOB_CONTRACTS = {
    "check": {
        "working_directory": "extensions/suno-helper",
        "e2e_step": "E2E tests (Playwright)",
    },
    "distrokid-helper": {
        "working_directory": "extensions/distrokid-helper",
        "e2e_step": "E2E (Playwright)",
    },
}
_NIX_EXTENSIONS_INSTALL_COMMAND = "nix develop .#extensions --command pnpm install --frozen-lockfile"
_NIX_EXTENSIONS_E2E_COMMAND = "nix develop .#extensions --command pnpm test:e2e"

_RELEASE_BUILD_PARALLEL_STEPS = {
    "Build and zip suno-helper": ("extensions/suno-helper", "pnpm zip"),
    "Build and zip distrokid-helper": ("extensions/distrokid-helper", "pnpm zip"),
}
_RELEASE_NIX_INSTALL_ACTION = "cachix/install-nix-action@v30"
_RELEASE_EXTENSIONS_SHELL_COMMAND = "nix develop ../..#extensions --command bash -euo pipefail"
_SHELL_BACKGROUND_OPERATOR = re.compile(r"(?<!&)&(?!&)")


def _read_text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"必須ファイルが存在しない: {path.relative_to(_REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _load_workflow(path: Path) -> dict[str, object]:
    return yaml.safe_load(_read_text(path))


def _on_section(workflow: dict[str, object]) -> dict[str, object]:
    section = workflow.get("on", workflow.get(True))
    assert isinstance(section, dict), "on トリガーが存在しない"
    return section


def _job_steps(workflow: dict[str, object], job_name: str) -> list[dict[str, object]]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "jobs セクションが存在しない"
    job = jobs.get(job_name)
    assert isinstance(job, dict), f"{job_name} job が存在しない"
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, f"{job_name} job に steps が存在しない"
    return steps


def _parallel_groups(steps: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    groups: list[list[dict[str, object]]] = []
    for step in steps:
        if "parallel" not in step:
            continue
        parallel_steps = step.get("parallel")
        assert isinstance(parallel_steps, list) and parallel_steps, "parallel step が空"
        groups.append(parallel_steps)
    return groups


def _parallel_group_with_names(steps: list[dict[str, object]], expected_names: set[str]) -> list[dict[str, object]]:
    for group in _parallel_groups(steps):
        names = {str(step.get("name", "")) for step in group}
        if names == expected_names:
            return group
    pytest.fail(f"expected parallel group が存在しない: {sorted(expected_names)}")


def _assert_named_parallel_commands(steps: list[dict[str, object]], expected: dict[str, str]) -> None:
    group = _parallel_group_with_names(steps, set(expected))
    commands_by_name = {str(step["name"]): str(step.get("run", "")) for step in group}
    assert commands_by_name == expected


def _top_level_step_index(steps: list[dict[str, object]], name: str) -> int:
    for index, step in enumerate(steps):
        if step.get("name") == name:
            return index
    pytest.fail(f"{name} step が top-level に存在しない")


def _top_level_step(steps: list[dict[str, object]], name: str) -> dict[str, object]:
    return steps[_top_level_step_index(steps, name)]


def _top_level_step_index_with_run(steps: list[dict[str, object]], run: str) -> int:
    for index, step in enumerate(steps):
        if step.get("run") == run:
            return index
    pytest.fail(f"{run} run step が top-level に存在しない")


def _top_level_step_index_with_uses(steps: list[dict[str, object]], uses: str) -> int:
    for index, step in enumerate(steps):
        if step.get("uses") == uses:
            return index
    pytest.fail(f"{uses} uses step が top-level に存在しない")


def _parallel_group_index_containing(steps: list[dict[str, object]], name: str) -> int:
    for index, step in enumerate(steps):
        parallel_steps = step.get("parallel")
        if not isinstance(parallel_steps, list):
            continue
        if any(parallel_step.get("name") == name for parallel_step in parallel_steps):
            return index
    pytest.fail(f"{name} step を含む parallel group が存在しない")


def _assert_run_has_no_shell_backgrounding(run_script: str) -> None:
    for line in run_script.splitlines():
        command = line.strip()
        assert _SHELL_BACKGROUND_OPERATOR.search(command) is None, f"shell backgrounding is not allowed: {command}"
        assert command != "wait" and not command.startswith("wait "), f"shell wait is not allowed: {command}"


def _assert_parallel_runs_do_not_use_shell_backgrounding(steps: list[dict[str, object]]) -> None:
    for group in _parallel_groups(steps):
        for parallel_step in group:
            run_script = parallel_step.get("run")
            assert isinstance(run_script, str), f"{parallel_step.get('name')} parallel step に run が存在しない"
            _assert_run_has_no_shell_backgrounding(run_script)


def test_extensions_pull_request_trigger_allows_stacked_pr_base_branches() -> None:
    """Given stacked PR, When workflow trigger is evaluated, Then base branch allowlist is absent."""
    workflow = _load_workflow(_EXTENSIONS_WORKFLOW_PATH)
    pull_request = _on_section(workflow).get("pull_request")

    assert isinstance(pull_request, dict), "Extensions pull_request トリガーが存在しない"
    assert "branches" not in pull_request


def test_extensions_pull_request_trigger_keeps_path_filter() -> None:
    """Given extension PR, When branch allowlist is removed, Then paths filter remains scoped."""
    workflow = _load_workflow(_EXTENSIONS_WORKFLOW_PATH)
    pull_request = _on_section(workflow).get("pull_request")

    assert isinstance(pull_request, dict), "pull_request トリガーが存在しない"
    expected_paths = ["extensions/**", ".github/workflows/extensions.yml", "flake.nix", "flake.lock"]
    assert pull_request.get("paths") == expected_paths
    assert _on_section(workflow).get("push", {}).get("paths") == expected_paths


@pytest.mark.parametrize("job_name", ["check", "distrokid-helper"])
def test_extensions_jobs_use_only_the_nix_extensions_toolchain(job_name: str) -> None:
    """Given Extensions CI, When commands run, Then both jobs use the Nix extensions shell."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), job_name)

    assert _top_level_step_index_with_uses(steps, "actions/checkout@v4") < _top_level_step_index_with_uses(
        steps, "cachix/install-nix-action@v30"
    )
    uses = {step.get("uses") for step in steps}
    assert "pnpm/action-setup@v4" not in uses
    assert "actions/setup-node@v4" not in uses
    run_steps = [step for step in steps if "run" in step]
    run_steps.extend(child for group in _parallel_groups(steps) for child in group)
    assert run_steps
    assert all(str(step.get("run", "")).startswith("nix develop .#extensions --command ") for step in run_steps)


@pytest.mark.parametrize("job_name", ["check", "distrokid-helper"])
def test_extensions_jobs_preserve_working_directory_install_and_e2e_contract(job_name: str) -> None:
    """Given Extensions CI, When Nix supplies its tools, Then each job keeps its check contract."""
    workflow = _load_workflow(_EXTENSIONS_WORKFLOW_PATH)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "jobs セクションが存在しない"
    job = jobs.get(job_name)
    assert isinstance(job, dict), f"{job_name} job が存在しない"
    contract = _EXTENSIONS_JOB_CONTRACTS[job_name]

    assert job.get("defaults") == {"run": {"working-directory": contract["working_directory"]}}
    steps = _job_steps(workflow, job_name)
    assert _top_level_step(steps, "Install dependencies").get("run") == _NIX_EXTENSIONS_INSTALL_COMMAND
    assert _top_level_step(steps, contract["e2e_step"]).get("run") == _NIX_EXTENSIONS_E2E_COMMAND


def test_ci_lint_runs_ruff_checks_in_a_single_parallel_group() -> None:
    """Given CI lint job, When dependencies are installed, Then independent ruff checks run in parallel."""
    steps = _job_steps(_load_workflow(_CI_WORKFLOW_PATH), "lint")

    _assert_named_parallel_commands(steps, _CI_LINT_PARALLEL_STEPS)
    assert _top_level_step_index_with_run(steps, "nix develop --command uv sync") < _parallel_group_index_containing(
        steps, "Ruff check"
    )
    _assert_parallel_runs_do_not_use_shell_backgrounding(steps)


@pytest.mark.parametrize(
    "run_script",
    [
        "pnpm zip & echo ok",
        "pnpm zip & # background",
        "pnpm zip &\nwait",
    ],
)
def test_parallel_run_contract_rejects_shell_backgrounding(run_script: str) -> None:
    """Given parallel child run, When shell backgrounding is used, Then contract test rejects it."""
    with pytest.raises(AssertionError):
        _assert_run_has_no_shell_backgrounding(run_script)


def test_parallel_run_contract_allows_shell_and_operator() -> None:
    """Given parallel child run, When commands use shell AND, Then it is not treated as backgrounding."""
    _assert_run_has_no_shell_backgrounding("pnpm install && pnpm zip")


def test_suno_helper_checks_use_dependency_safe_parallel_groups() -> None:
    """Given suno-helper CI, When install completes, Then independent checks run in parallel batches."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), "check")

    _assert_named_parallel_commands(steps, _SUNO_FAST_PARALLEL_STEPS)
    _assert_named_parallel_commands(steps, _SUNO_BUILD_PARALLEL_STEPS)
    install_index = _top_level_step_index(steps, "Install dependencies")
    fast_parallel_index = _parallel_group_index_containing(steps, "Lint")
    build_parallel_index = _parallel_group_index_containing(steps, "Build")

    assert install_index < fast_parallel_index < build_parallel_index
    assert _parallel_group_index_containing(steps, "Build") < _top_level_step_index(
        steps, "Verify generated manifest permissions (least-privilege)"
    )
    assert _parallel_group_index_containing(steps, "Install Playwright browser") < _top_level_step_index(
        steps, "E2E tests (Playwright)"
    )
    _assert_parallel_runs_do_not_use_shell_backgrounding(steps)


def test_suno_helper_manifest_permission_check_preserves_least_privilege_contract() -> None:
    """Given suno-helper CI, When manifest is built, Then permission verification remains meaningful."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), "check")
    manifest_step = _top_level_step(steps, "Verify generated manifest permissions (least-privilege)")
    run_script = str(manifest_step.get("run", ""))

    assert ".output/chrome-mv3/manifest.json" in run_script
    assert 'const expected = ["storage", "activeTab", "downloads", "debugger", "scripting"];' in run_script
    assert "const actual = manifest.permissions ?? [];" in run_script
    assert "expected.every((p) => actual.includes(p))" in run_script
    assert "process.exit(1);" in run_script


def test_distrokid_helper_checks_use_dependency_safe_parallel_groups() -> None:
    """Given distrokid-helper CI, When install completes, Then independent checks run in parallel batches."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), "distrokid-helper")

    _assert_named_parallel_commands(steps, _DISTROKID_FAST_PARALLEL_STEPS)
    _assert_named_parallel_commands(steps, _DISTROKID_BUILD_PARALLEL_STEPS)
    install_index = _top_level_step_index(steps, "Install dependencies")
    fast_parallel_index = _parallel_group_index_containing(steps, "Lint")
    build_parallel_index = _parallel_group_index_containing(steps, "Build")

    assert install_index < fast_parallel_index < build_parallel_index
    assert _parallel_group_index_containing(steps, "Build") < _top_level_step_index(
        steps, "Verify generated manifest permissions (least-privilege)"
    )
    manifest_check_index = _top_level_step_index(steps, "Verify generated manifest permissions (least-privilege)")
    assert manifest_check_index < _top_level_step_index(steps, "E2E (Playwright)")
    assert _parallel_group_index_containing(steps, "Install Playwright browser") < _top_level_step_index(
        steps, "E2E (Playwright)"
    )
    _assert_parallel_runs_do_not_use_shell_backgrounding(steps)


def test_distrokid_helper_manifest_permission_check_preserves_least_privilege_contract() -> None:
    """Given distrokid-helper CI, When manifest is built, Then permission verification remains meaningful."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), "distrokid-helper")
    manifest_step = _top_level_step(steps, "Verify generated manifest permissions (least-privilege)")
    run_script = str(manifest_step.get("run", ""))

    assert ".output/chrome-mv3/manifest.json" in run_script
    assert 'const expected = ["storage", "activeTab"];' in run_script
    assert "const actual = manifest.permissions ?? [];" in run_script
    assert "expected.every((p) => actual.includes(p))" in run_script
    assert '"*://*.distrokid.com/*"' in run_script
    assert '"http://*.localhost/*"' in run_script
    assert '"http://localhost/*"' in run_script
    assert '"http://127.0.0.1/*"' in run_script
    assert "const actualHosts = manifest.host_permissions ?? [];" in run_script
    assert "expectedHosts.every((p) => actualHosts.includes(p))" in run_script
    assert 'const expectedContentScriptMatches = ["*://*.distrokid.com/new*"];' in run_script
    assert "const contentScripts = manifest.content_scripts ?? [];" in run_script
    assert "const actualContentScriptMatches = contentScripts.flatMap(" in run_script
    assert "expectedContentScriptMatches.every((p) => actualContentScriptMatches.includes(p))" in run_script
    assert "process.exit(1);" in run_script


def test_release_extensions_builds_both_zips_before_release_attachment() -> None:
    """Given extension release, When zips are built, Then both builds share one parallel group before attach."""
    steps = _job_steps(_load_workflow(_RELEASE_EXTENSIONS_WORKFLOW_PATH), "release")
    group = _parallel_group_with_names(steps, set(_RELEASE_BUILD_PARALLEL_STEPS))
    build_parallel_index = _parallel_group_index_containing(steps, "Build and zip suno-helper")

    for step in group:
        working_directory, required_command = _RELEASE_BUILD_PARALLEL_STEPS[str(step["name"])]
        assert step.get("working-directory") == working_directory
        assert required_command in str(step.get("run", ""))
        assert _RELEASE_EXTENSIONS_SHELL_COMMAND in str(step.get("run", ""))
        assert "pnpm install --frozen-lockfile" in str(step.get("run", ""))
    assert _top_level_step_index_with_uses(steps, "actions/checkout@v4") < build_parallel_index
    assert _top_level_step_index_with_uses(steps, _RELEASE_NIX_INSTALL_ACTION) < build_parallel_index
    assert build_parallel_index < _top_level_step_index(steps, "Attach zips to Release")
    _assert_parallel_runs_do_not_use_shell_backgrounding(steps)
