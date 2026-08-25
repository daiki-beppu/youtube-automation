"""GitHub Actions step 並列化の workflow 契約を静的に検証する。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.helpers.paths import REPO_ROOT

_REPO_ROOT = REPO_ROOT
_CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_EXTENSIONS_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "extensions.yml"
_RELEASE_EXTENSIONS_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "release-extensions.yml"
_CI_PATH_CLASSIFIER = _REPO_ROOT / ".github" / "scripts" / "classify-ci-paths.sh"

_CI_LINT_PARALLEL_STEPS = {
    "Ruff check": "nix develop --command uv run ruff check .",
    "Ruff format check": "nix develop --command uv run ruff format --check .",
    "pyscn check": "nix develop --command uv run pyscn check src/youtube_automation",
}

_SUNO_FAST_PARALLEL_STEPS = {
    "Check (Oxlint + Oxfmt)": "nix develop .#extensions --command pnpm check",
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
    "Check (Oxlint + Oxfmt)": "nix develop .#extensions --command pnpm check",
    "Typecheck": "nix develop .#extensions --command pnpm compile",
    "Unit tests (Vitest)": "nix develop .#extensions --command pnpm test",
}
_DISTROKID_BUILD_PARALLEL_STEPS = _SUNO_BUILD_PARALLEL_STEPS
_COMMUNITY_FAST_PARALLEL_STEPS = {
    "Check (Oxlint + Oxfmt)": "nix develop .#extensions --command pnpm check",
    "Typecheck": "nix develop .#extensions --command pnpm compile",
    "Unit tests (Vitest)": "nix develop .#extensions --command pnpm test",
}
_EXTENSIONS_JOB_CONTRACTS = {
    "check": {
        "working_directory": "extensions/suno-helper",
        "e2e_step": "E2E tests (Playwright)",
        "check_script": "cd .. && ultracite check suno-helper shared shared-ui",
    },
    "distrokid-helper": {
        "working_directory": "extensions/distrokid-helper",
        "e2e_step": "E2E (Playwright)",
        "check_script": "cd .. && ultracite check distrokid-helper",
    },
    "community-helper": {
        "working_directory": "extensions/community-helper",
        "e2e_step": "E2E (Playwright)",
        "check_script": "cd .. && ultracite check community-helper",
    },
}
_NIX_EXTENSIONS_INSTALL_COMMAND = "nix develop .#extensions --command pnpm install --frozen-lockfile"
_NIX_EXTENSIONS_E2E_COMMAND = "nix develop .#extensions --command xvfb-run -a pnpm test:e2e"
_NIX_EXTENSIONS_AUDIT_COMMAND = "nix develop .#extensions --command pnpm run audit"

_RELEASE_BUILD_PARALLEL_STEPS = {
    "Build and zip suno-helper": ("extensions/suno-helper", "verify-extensions.sh suno-helper"),
    "Build and zip distrokid-helper": ("extensions/distrokid-helper", "verify-extensions.sh distrokid-helper"),
    "Build and zip community-helper": ("extensions/community-helper", "verify-extensions.sh community-helper"),
}
_RELEASE_NIX_INSTALL_ACTION = "DeterminateSystems/nix-installer-action@ef8a148080ab6020fd15196c2084a2eea5ff2d25"
_SHELL_BACKGROUND_OPERATOR = re.compile(r"(?<!&)&(?!&)")


def _read_text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"必須ファイルが存在しない: {path.relative_to(_REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _load_workflow(path: Path) -> dict[str, object]:
    return yaml.safe_load(_read_text(path))


def _classify_paths(tmp_path: Path, paths: list[str]) -> dict[str, bool]:
    changed = tmp_path / "changed-paths.txt"
    changed.write_text("".join(f"{path}\n" for path in paths), encoding="utf-8")
    result = subprocess.run(
        ["bash", str(_CI_PATH_CLASSIFIER), str(changed)],
        check=True,
        capture_output=True,
        text=True,
    )
    return {key: value == "true" for line in result.stdout.splitlines() for key, value in [line.split("=", maxsplit=1)]}


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
    expected_paths = [
        "extensions/**",
        ".github/workflows/extensions.yml",
        ".github/scripts/classify-ci-paths.sh",
        "tests/repo/test_actions_parallel_workflows.py",
        "flake.nix",
        "flake.lock",
    ]
    assert pull_request.get("paths") == expected_paths
    assert _on_section(workflow).get("push", {}).get("paths") == expected_paths


@pytest.mark.parametrize(
    ("paths", "expected_true"),
    [
        (["extensions/suno-helper/components/App.tsx"], {"suno"}),
        (["dashboard/src/App.tsx"], {"python", "packaging"}),
        (
            ["extensions/shared-ui/src/button.tsx"],
            {"suno", "distrokid", "community"},
        ),
        (
            ["src/youtube_automation/commands/collections/collection_serve.py"],
            {"python", "packaging", "windows"},
        ),
        (
            ["src/youtube_automation/infrastructure/file_lock.py"],
            {"python", "packaging", "windows"},
        ),
        (
            ["src/youtube_automation/infrastructure/cost_tracker.py"],
            {"python", "packaging", "windows"},
        ),
        (["docs/adr/0024-example.md"], {"python", "adr"}),
        ([".github/scripts/select-affected-tests.py"], {"python"}),
        (
            [],
            {"python", "packaging", "windows", "adr", "suno", "distrokid", "community"},
        ),
    ],
)
def test_ci_path_classifier_selects_only_responsible_gates(
    tmp_path: Path, paths: list[str], expected_true: set[str]
) -> None:
    """Changed path ごとの gate 対応と空 diff の fail-safe を固定する。"""
    classified = _classify_paths(tmp_path, paths)

    assert {key for key, enabled in classified.items() if enabled} == expected_true


def test_ci_required_jobs_always_report_but_gate_heavy_python_steps() -> None:
    """Required lint/test job は常時存在し、extension-only 時は重い step だけを省略する。"""
    workflow = _load_workflow(_CI_WORKFLOW_PATH)
    jobs = workflow["jobs"]

    for trigger_name in ("push", "pull_request"):
        trigger = _on_section(workflow)[trigger_name]
        assert "paths" not in trigger and "paths-ignore" not in trigger

    for job_name in ("lint", "test"):
        job = jobs[job_name]
        assert job.get("needs") == "changes"
        assert "if" not in job
        steps = job["steps"]
        assert any(step.get("if") == "needs.changes.outputs.python != 'true'" for step in steps)
        heavy_steps = [step for step in steps if step.get("uses") or "nix develop" in str(step.get("run", ""))]
        assert heavy_steps
        assert all(step.get("if") == "needs.changes.outputs.python == 'true'" for step in heavy_steps)
        for group in _parallel_groups(steps):
            assert all(step.get("if") == "needs.changes.outputs.python == 'true'" for step in group)

    assert jobs["build-smoke"]["if"] == "needs.changes.outputs.packaging == 'true'"
    assert jobs["windows-cost-tracker"]["if"] == "needs.changes.outputs.windows == 'true'"
    windows_steps = jobs["windows-cost-tracker"]["steps"]
    collection_serve_import_test = (
        "uv run pytest tests/commands/collections/test_collection_serve.py"
        "::test_module_import_succeeds_without_fcntl -q"
    )
    assert any(step.get("run") == collection_serve_import_test for step in windows_steps)
    assert jobs["adr-numbering"]["if"] == "needs.changes.outputs.adr == 'true'"


def test_ci_passes_selector_plan_as_job_output_without_shell_interpolation() -> None:
    workflow = _load_workflow(_CI_WORKFLOW_PATH)
    changes = workflow["jobs"]["changes"]
    test_job = workflow["jobs"]["test"]

    assert changes["outputs"]["test_plan"] == "${{ steps.test-plan.outputs.plan }}"
    plan_step = _top_level_step(changes["steps"], "Build affected-test plan")
    assert plan_step["id"] == "test-plan"
    assert "select-affected-tests.py --format json" in plan_step["run"]
    assert "changed-paths.txt" in plan_step["run"]
    assert "GITHUB_OUTPUT" in plan_step["run"]

    test_step = _top_level_step(test_job["steps"], "Test")
    assert test_step["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "TEST_PLAN_JSON": "${{ needs.changes.outputs.test_plan }}",
    }
    run = test_step["run"]
    assert "${{" not in run
    assert "eval " not in run
    assert "xargs" not in run


def test_ci_pr_selected_plan_uses_safe_array_while_main_and_all_run_exact_full_suite() -> None:
    workflow = _load_workflow(_CI_WORKFLOW_PATH)
    jobs = workflow["jobs"]
    assert "test" in jobs
    assert "if" not in jobs["test"]

    run = _top_level_step(jobs["test"]["steps"], "Test")["run"]
    assert '[ "$EVENT_NAME" = "pull_request" ]' in run
    assert '[ "$plan_mode" = "selected" ]' in run
    assert 'targets=("${plan_lines[@]:1}")' in run
    assert 'pytest -n auto -- "${targets[@]}"' in run
    assert "Selected pytest targets: ${#targets[@]}/${total_count}" in run
    assert "nix develop --command uv run pytest -n auto\n" in run
    assert "-m repo_contract" not in run
    assert "not repo_contract and not slow" not in run


def _run_ci_test_step(
    tmp_path: Path, *, event_name: str, payload: dict[str, object]
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    run = _top_level_step(_load_workflow(_CI_WORKFLOW_PATH)["jobs"]["test"]["steps"], "Test")["run"]
    repository = tmp_path / "repository"
    (repository / "tests").mkdir(parents=True)
    (repository / "tests/test_selected.py").write_text("", encoding="utf-8")
    (repository / "tests/test_other.py").write_text("", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    nix = fake_bin / "nix"
    nix.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$NIX_ARGS_LOG"\n', encoding="utf-8")
    nix.chmod(0o755)
    args_log = tmp_path / "nix-args.txt"
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()

    result = subprocess.run(
        ["bash", "-c", run],
        cwd=repository,
        env=os.environ
        | {
            "EVENT_NAME": event_name,
            "TEST_PLAN_JSON": json.dumps(payload),
            "RUNNER_TEMP": str(runner_temp),
            "NIX_ARGS_LOG": str(args_log),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    arguments = args_log.read_text(encoding="utf-8").splitlines() if args_log.exists() else []
    return result, arguments


def test_ci_pr_executes_only_selected_targets_and_logs_selected_over_total(tmp_path: Path) -> None:
    result, arguments = _run_ci_test_step(
        tmp_path,
        event_name="pull_request",
        payload={"mode": "selected", "targets": ["tests/test_selected.py"]},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Selected pytest targets: 1/2" in result.stdout
    assert arguments == [
        "develop",
        "--command",
        "uv",
        "run",
        "pytest",
        "-n",
        "auto",
        "--",
        "tests/test_selected.py",
    ]


@pytest.mark.parametrize(
    ("event_name", "payload"),
    [
        ("push", {"mode": "selected", "targets": ["tests/test_selected.py"]}),
        ("pull_request", {"mode": "all", "targets": []}),
    ],
)
def test_ci_main_push_and_pr_fail_safe_execute_exact_full_suite(
    tmp_path: Path, event_name: str, payload: dict[str, object]
) -> None:
    result, arguments = _run_ci_test_step(tmp_path, event_name=event_name, payload=payload)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Full pytest suite: 2/2 targets" in result.stdout
    assert arguments == ["develop", "--command", "uv", "run", "pytest", "-n", "auto"]


def test_extensions_jobs_are_gated_by_their_changed_path_outputs() -> None:
    """各 helper job は shared classifier の対応 output だけで起動する。"""
    jobs = _load_workflow(_EXTENSIONS_WORKFLOW_PATH)["jobs"]
    assert jobs["check"]["needs"] == "changes"
    assert jobs["check"]["if"] == "needs.changes.outputs.suno == 'true'"
    assert jobs["distrokid-helper"]["if"] == "needs.changes.outputs.distrokid == 'true'"
    assert jobs["community-helper"]["if"] == "needs.changes.outputs.community == 'true'"


def test_issue_lint_workflow_and_script_are_removed() -> None:
    """issue edit/label ごとの non-blocking Actions run を復活させない。"""
    assert not (_REPO_ROOT / ".github" / "workflows" / "issue-lint.yml").exists()
    assert not (_REPO_ROOT / ".github" / "scripts" / "issue-lint.sh").exists()


@pytest.mark.parametrize("job_name", ["check", "distrokid-helper", "community-helper"])
def test_extensions_jobs_use_only_the_nix_extensions_toolchain(job_name: str) -> None:
    """Given Extensions CI, When commands run, Then all jobs use the Nix extensions shell."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), job_name)

    assert _top_level_step_index_with_uses(
        steps, "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    ) < _top_level_step_index_with_uses(steps, "cachix/install-nix-action@630ae543ea3a38a9a4166f03376c02c50f408342")
    uses = {step.get("uses") for step in steps}
    assert "pnpm/action-setup@v4" not in uses
    assert "actions/setup-node@v4" not in uses
    run_steps = [step for step in steps if "run" in step]
    run_steps.extend(child for group in _parallel_groups(steps) for child in group)
    assert run_steps
    assert all(str(step.get("run", "")).startswith("nix develop .#extensions --command ") for step in run_steps)


@pytest.mark.parametrize("job_name", ["check", "distrokid-helper", "community-helper"])
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
    # 共有 config の ultracite import を extensions/node_modules で解決するための install（#2154）。
    toolchain_install = _top_level_step(steps, "Install shared lint toolchain")
    assert toolchain_install.get("run") == _NIX_EXTENSIONS_INSTALL_COMMAND
    assert toolchain_install.get("working-directory") == "extensions"
    assert (
        _top_level_step_index(steps, "Install dependencies")
        < _top_level_step_index(steps, "Install shared lint toolchain")
        < _parallel_group_index_containing(steps, "Check (Oxlint + Oxfmt)")
    )
    assert _top_level_step(steps, contract["e2e_step"]).get("run") == _NIX_EXTENSIONS_E2E_COMMAND


@pytest.mark.parametrize("job_name", ["check", "distrokid-helper", "community-helper"])
def test_extensions_jobs_run_ultracite_through_the_package_check_entrypoint(job_name: str) -> None:
    """Given Extensions CI, When check runs, Then each package's pnpm check entrypoint invokes ultracite."""
    workflow = _load_workflow(_EXTENSIONS_WORKFLOW_PATH)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "jobs セクションが存在しない"
    job = jobs.get(job_name)
    assert isinstance(job, dict), f"{job_name} job が存在しない"
    contract = _EXTENSIONS_JOB_CONTRACTS[job_name]

    expected_steps = _SUNO_FAST_PARALLEL_STEPS if job_name == "check" else _DISTROKID_FAST_PARALLEL_STEPS
    check_group = _parallel_group_with_names(_job_steps(workflow, job_name), set(expected_steps))
    check_step = next(step for step in check_group if step.get("name") == "Check (Oxlint + Oxfmt)")
    assert check_step.get("run") == "nix develop .#extensions --command pnpm check"

    package = json.loads(_read_text(_REPO_ROOT / str(contract["working_directory"]) / "package.json"))
    assert package["scripts"]["check"] == contract["check_script"]


def test_extensions_pull_request_runs_one_fallow_audit_for_the_extensions_root() -> None:
    """Given an extension PR, When CI runs, Then one audit checks the entire extensions tree."""
    workflow = _load_workflow(_EXTENSIONS_WORKFLOW_PATH)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "jobs セクションが存在しない"

    audit_steps: list[tuple[str, dict[str, object]]] = []
    for job_name in jobs:
        for step in _job_steps(workflow, str(job_name)):
            if step.get("run") == _NIX_EXTENSIONS_AUDIT_COMMAND:
                audit_steps.append((str(job_name), step))
            parallel_steps = step.get("parallel")
            if isinstance(parallel_steps, list):
                audit_steps.extend(
                    (str(job_name), child)
                    for child in parallel_steps
                    if child.get("run") == _NIX_EXTENSIONS_AUDIT_COMMAND
                )

    assert audit_steps == [
        (
            "check",
            {
                "name": "Fallow audit",
                "if": "github.event_name == 'pull_request'",
                "env": {"FALLOW_AUDIT_BASE": "${{ github.event.pull_request.base.sha }}"},
                "run": _NIX_EXTENSIONS_AUDIT_COMMAND,
            },
        )
    ]

    steps = _job_steps(workflow, "check")
    checkout = steps[
        _top_level_step_index_with_uses(steps, "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
    ]
    assert checkout.get("with") == {"fetch-depth": 0}

    jobs_check = jobs.get("check")
    assert isinstance(jobs_check, dict)
    working_directory = jobs_check.get("defaults", {}).get("run", {}).get("working-directory")
    assert working_directory == "extensions/suno-helper"
    package_json = json.loads(_read_text(_REPO_ROOT / working_directory / "package.json"))
    assert package_json["scripts"]["audit"] == "fallow audit --root .."
    assert (_REPO_ROOT / working_directory / "..").resolve() == (_REPO_ROOT / "extensions").resolve()

    assert (
        _top_level_step_index(steps, "Install dependencies")
        < _top_level_step_index(steps, "Fallow audit")
        < _parallel_group_index_containing(steps, "Check (Oxlint + Oxfmt)")
    )


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
    fast_parallel_index = _parallel_group_index_containing(steps, "Check (Oxlint + Oxfmt)")
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
    assert (
        'const expected = ["storage", "activeTab", "downloads", "debugger", "scripting", "notifications"];'
        in run_script
    )
    assert "const actual = manifest.permissions ?? [];" in run_script
    assert "expected.every((p) => actual.includes(p))" in run_script
    assert "process.exit(1);" in run_script


def test_distrokid_helper_checks_use_dependency_safe_parallel_groups() -> None:
    """Given distrokid-helper CI, When install completes, Then independent checks run in parallel batches."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), "distrokid-helper")

    _assert_named_parallel_commands(steps, _DISTROKID_FAST_PARALLEL_STEPS)
    _assert_named_parallel_commands(steps, _DISTROKID_BUILD_PARALLEL_STEPS)
    install_index = _top_level_step_index(steps, "Install dependencies")
    fast_parallel_index = _parallel_group_index_containing(steps, "Check (Oxlint + Oxfmt)")
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


def test_community_helper_runs_required_ci_gates_after_install() -> None:
    """Given community-helper CI, When dependencies install, Then all UI gates run."""
    workflow = _load_workflow(_EXTENSIONS_WORKFLOW_PATH)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    job = jobs.get("community-helper")
    assert isinstance(job, dict), "community-helper job が存在しない"
    assert job.get("defaults") == {"run": {"working-directory": "extensions/community-helper"}}

    steps = _job_steps(workflow, "community-helper")
    assert _top_level_step(steps, "Install dependencies").get("run") == _NIX_EXTENSIONS_INSTALL_COMMAND
    toolchain_install = _top_level_step(steps, "Install shared lint toolchain")
    assert toolchain_install.get("working-directory") == "extensions"
    assert toolchain_install.get("run") == _NIX_EXTENSIONS_INSTALL_COMMAND
    _assert_named_parallel_commands(steps, _COMMUNITY_FAST_PARALLEL_STEPS)
    _assert_named_parallel_commands(steps, _SUNO_BUILD_PARALLEL_STEPS)
    assert _parallel_group_index_containing(steps, "Check (Oxlint + Oxfmt)") < _parallel_group_index_containing(
        steps, "Build"
    )
    assert _top_level_step(steps, "E2E (Playwright)").get("run") == _NIX_EXTENSIONS_E2E_COMMAND
    _assert_parallel_runs_do_not_use_shell_backgrounding(steps)


def test_community_helper_generated_manifest_preserves_least_privilege_contract() -> None:
    """Given community build, When CI inspects output, Then runtime permissions remain exact."""
    steps = _job_steps(_load_workflow(_EXTENSIONS_WORKFLOW_PATH), "community-helper")
    manifest_step = _top_level_step(steps, "Verify generated manifest permissions (least-privilege)")
    run_script = str(manifest_step.get("run", ""))

    assert ".output/chrome-mv3/manifest.json" in run_script
    assert 'const expected = ["storage", "activeTab"];' in run_script
    assert '"http://*.localhost/*"' in run_script
    assert '"http://localhost/*"' in run_script
    assert '"http://127.0.0.1/*"' in run_script
    assert 'const expectedContentScriptMatches = ["https://www.youtube.com/channel/*/posts*"];' in run_script
    assert "actual.length === expected.length" in run_script
    assert "actualHosts.length === expectedHosts.length" in run_script
    assert "actualContentScriptMatches.length === expectedContentScriptMatches.length" in run_script
    assert "process.exit(1);" in run_script


def test_release_extensions_builds_all_zips_before_release_attachment() -> None:
    """Given extension release, When zips are built, Then all builds share one parallel group before attach."""
    steps = _job_steps(_load_workflow(_RELEASE_EXTENSIONS_WORKFLOW_PATH), "release")
    group = _parallel_group_with_names(steps, set(_RELEASE_BUILD_PARALLEL_STEPS))
    build_parallel_index = _parallel_group_index_containing(steps, "Build and zip suno-helper")

    for step in group:
        working_directory, required_command = _RELEASE_BUILD_PARALLEL_STEPS[str(step["name"])]
        assert step.get("working-directory") == working_directory
        assert required_command in str(step.get("run", ""))
        assert str(step.get("run", "")).startswith("cd ../.. && bash ")
    assert (
        _top_level_step_index_with_uses(steps, "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
        < build_parallel_index
    )
    assert _top_level_step_index_with_uses(steps, _RELEASE_NIX_INSTALL_ACTION) < build_parallel_index
    assert build_parallel_index < _top_level_step_index(steps, "Attach zips to Release")
    _assert_parallel_runs_do_not_use_shell_backgrounding(steps)
