"""GitHub Actions step 並列化の workflow 契約を静的に検証する。"""

from __future__ import annotations

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
    "Lint": "pnpm lint",
    "Format check": "pnpm format:check",
    "Type check": "pnpm compile",
    "Unit tests (Vitest)": "pnpm test",
}
_SUNO_BUILD_PARALLEL_STEPS = {
    "Build": "pnpm build",
    "Install Playwright browser": "pnpm exec playwright install --with-deps chromium",
}
_DISTROKID_FAST_PARALLEL_STEPS = {
    "Lint": "pnpm lint",
    "Format check": "pnpm format:check",
    "Typecheck": "pnpm compile",
    "Unit tests (Vitest)": "pnpm test",
}
_DISTROKID_BUILD_PARALLEL_STEPS = _SUNO_BUILD_PARALLEL_STEPS

_RELEASE_BUILD_PARALLEL_STEPS = {
    "Build and zip suno-helper": ("extensions/suno-helper", "pnpm zip"),
    "Build and zip distrokid-helper": ("extensions/distrokid-helper", "pnpm zip"),
}


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
    assert pull_request.get("paths") == ["extensions/**", ".github/workflows/extensions.yml"]


def test_ci_lint_runs_ruff_checks_in_a_single_parallel_group() -> None:
    """Given CI lint job, When dependencies are installed, Then independent ruff checks run in parallel."""
    steps = _job_steps(_load_workflow(_CI_WORKFLOW_PATH), "lint")

    _assert_named_parallel_commands(steps, _CI_LINT_PARALLEL_STEPS)
    assert _top_level_step_index_with_run(
        steps, "nix develop --command uv sync --extra dev"
    ) < _parallel_group_index_containing(steps, "Ruff check")


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


def test_distrokid_helper_checks_use_dependency_safe_parallel_groups() -> None:
    """Given distrokid-helper CI, When install completes, Then independent checks run in parallel batches."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), "distrokid-helper")

    _assert_named_parallel_commands(steps, _DISTROKID_FAST_PARALLEL_STEPS)
    _assert_named_parallel_commands(steps, _DISTROKID_BUILD_PARALLEL_STEPS)
    install_index = _top_level_step_index(steps, "Install dependencies")
    fast_parallel_index = _parallel_group_index_containing(steps, "Lint")
    build_parallel_index = _parallel_group_index_containing(steps, "Build")

    assert install_index < fast_parallel_index < build_parallel_index
    assert _parallel_group_index_containing(steps, "Install Playwright browser") < _top_level_step_index(
        steps, "E2E (Playwright)"
    )


def test_release_extensions_builds_both_zips_before_release_attachment() -> None:
    """Given extension release, When zips are built, Then both builds share one parallel group before attach."""
    steps = _job_steps(_load_workflow(_RELEASE_EXTENSIONS_WORKFLOW_PATH), "release")
    group = _parallel_group_with_names(steps, set(_RELEASE_BUILD_PARALLEL_STEPS))
    build_parallel_index = _parallel_group_index_containing(steps, "Build and zip suno-helper")

    for step in group:
        working_directory, required_command = _RELEASE_BUILD_PARALLEL_STEPS[str(step["name"])]
        assert step.get("working-directory") == working_directory
        assert required_command in str(step.get("run", ""))
        assert "pnpm install --frozen-lockfile --ignore-workspace" in str(step.get("run", ""))
    assert _top_level_step_index_with_uses(steps, "actions/checkout@v4") < build_parallel_index
    assert _top_level_step_index_with_uses(steps, "pnpm/action-setup@v4") < build_parallel_index
    assert _top_level_step_index_with_uses(steps, "actions/setup-node@v4") < build_parallel_index
    assert build_parallel_index < _top_level_step_index(steps, "Attach zips to Release")
