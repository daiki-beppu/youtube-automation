"""takt 0.60 系 workflow の利用者向け契約を静的に検証する。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT

TAKT = REPO_ROOT / ".takt"
WORKFLOWS = TAKT / "workflows"
STEPS = TAKT / "steps"
FACETS = TAKT / "facets"
LOCAL_TEST_GATE = REPO_ROOT / ".github/scripts/run-affected-tests.py"

PUBLIC_WORKFLOWS = {
    "audit-unit-split",
    "yt-auto-audit",
    "yt-auto-audit-runs",
    "yt-auto-docs",
    "yt-auto-feature",
    "yt-auto-fix",
    "yt-auto-maintenance",
}

LANE_STEPS = {
    "yt-auto-feature": (
        "intake",
        "plan",
        "test_design",
        "design_review",
        "design_gate",
        "write_tests",
        "implement",
        "reviewers",
        "review_gate",
        "ci_verify",
        "final_gate",
        "spillover",
    ),
    "yt-auto-fix": (
        "intake",
        "diagnose",
        "diagnosis_review",
        "diagnosis_gate",
        "reproduce",
        "repair",
        "reviewers",
        "review_gate",
        "ci_verify",
        "final_gate",
        "spillover",
    ),
    "yt-auto-docs": (
        "intake",
        "plan",
        "implement",
        "docs_review",
        "docs_gate",
        "ci_verify",
        "final_gate",
        "spillover",
    ),
    "yt-auto-maintenance": (
        "intake",
        "plan",
        "plan_review",
        "plan_gate",
        "safety_net",
        "refactor",
        "reviewers",
        "review_gate",
        "ci_verify",
        "final_gate",
        "spillover",
    ),
    "yt-auto-audit": ("plan", "audit", "supervise", "review", "publish"),
    "yt-auto-audit-runs": ("plan", "audit", "supervise", "review", "publish"),
    "audit-unit-split": ("plan", "audit", "supervise", "review"),
}

EDITABLE_STEPS = {
    "yt-auto-feature": {"write_tests", "implement", "fix"},
    "yt-auto-fix": {"reproduce", "repair", "fix"},
    "yt-auto-docs": {"implement", "docs_fix"},
    "yt-auto-maintenance": {"safety_net", "refactor", "fix"},
    "yt-auto-audit": {"publish"},
    "yt-auto-audit-runs": {"publish"},
    "audit-unit-split": set(),
}


def _load(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), path
    return loaded


def _workflow(name: str) -> dict[str, object]:
    return _load(WORKFLOWS / f"{name}.yaml")


def _steps(workflow: dict[str, object]) -> list[dict[str, object]]:
    steps = workflow.get("steps")
    assert isinstance(steps, list) and steps
    return steps


def _step(workflow: dict[str, object], name: str) -> dict[str, object]:
    return next(step for step in _steps(workflow) if step.get("name") == name)


def _expanded_step(step: dict[str, object]) -> dict[str, object]:
    uses = step.get("uses")
    if not isinstance(uses, str):
        return step
    return {**_load(STEPS / f"{uses}.yaml"), **step}


def _walk(value: object) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _capabilities(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    assert isinstance(value, list)
    return [str(item) for item in value]


def _next_targets(workflow: dict[str, object]) -> set[str]:
    return {value for key, value in _walk(workflow) if key == "next" and isinstance(value, str)}


def _rule_targets(workflow: dict[str, object], step_name: str) -> dict[str, str]:
    rules = _step(workflow, step_name).get("rules")
    assert isinstance(rules, list)
    return {str(rule["condition"]): str(rule["next"]) for rule in rules}


def test_public_workflow_surface_is_exact_and_named_consistently() -> None:
    paths = sorted(WORKFLOWS.glob("*.yaml"))
    assert {path.stem for path in paths} == PUBLIC_WORKFLOWS
    assert {_load(path)["name"] for path in paths} == PUBLIC_WORKFLOWS


def test_all_local_references_exist_and_builtin_calls_are_explicit() -> None:
    documents = [*WORKFLOWS.glob("*.yaml"), *STEPS.glob("*.yaml")]
    allowed_builtin_calls = {"final-gate"}
    allowed_builtin_formats = {"unit-audit-plan"}

    for path in documents:
        for key, value in _walk(_load(path)):
            if key == "uses" and isinstance(value, str):
                assert (STEPS / f"{value}.yaml").is_file(), (path, value)
            if key == "call" and isinstance(value, str):
                assert value in allowed_builtin_calls, (path, value)
            if key == "instruction" and isinstance(value, str):
                if value.startswith(("yt-auto-", "unit-audit-")):
                    assert (FACETS / "instructions" / f"{value}.md").is_file(), (path, value)
            if key == "format" and isinstance(value, str):
                if value.startswith(("yt-auto-", "unit-audit-")) and value not in allowed_builtin_formats:
                    assert (FACETS / "output-contracts" / f"{value}.md").is_file(), (path, value)
            if key == "schema_ref" and isinstance(value, str):
                assert (TAKT / "schemas" / f"{value}.json").is_file(), (path, value)


def test_every_local_step_facet_and_schema_is_referenced() -> None:
    documents = [*WORKFLOWS.glob("*.yaml"), *STEPS.glob("*.yaml")]
    references = list(_walk([_load(path) for path in documents]))
    used_steps = {value for key, value in references if key == "uses" and isinstance(value, str)}
    used_instructions = {
        value
        for key, value in references
        if key == "instruction" and isinstance(value, str) and value.startswith(("yt-auto-", "unit-audit-"))
    }
    used_formats = {
        value
        for key, value in references
        if key == "format" and isinstance(value, str) and value.startswith(("yt-auto-", "unit-audit-"))
    }
    used_schemas = {value for key, value in references if key == "schema_ref" and isinstance(value, str)}

    assert used_steps == {path.stem for path in STEPS.glob("*.yaml")}
    assert used_instructions == {path.stem for path in (FACETS / "instructions").glob("*.md")}
    assert used_formats - {"unit-audit-plan"} == {path.stem for path in (FACETS / "output-contracts").glob("*.md")}
    assert used_schemas == {path.stem for path in (TAKT / "schemas").glob("*.json")}


def test_each_lane_preserves_its_user_facing_stage_contract() -> None:
    for name, expected in LANE_STEPS.items():
        actual = [str(step["name"]) for step in _steps(_workflow(name))]
        positions = [actual.index(step_name) for step_name in expected]
        assert positions == sorted(positions), (name, actual)


def test_every_public_lane_has_bounded_loops_and_both_terminal_classes() -> None:
    for name in PUBLIC_WORKFLOWS:
        workflow = _workflow(name)
        max_steps = workflow.get("max_steps")
        monitors = workflow.get("loop_monitors")
        assert isinstance(max_steps, int) and 1 <= max_steps <= 50, name
        assert isinstance(monitors, list) and monitors, name
        for monitor in monitors:
            assert isinstance(monitor.get("cycle"), list) and len(monitor["cycle"]) >= 2
            assert isinstance(monitor.get("threshold"), int) and monitor["threshold"] >= 1
            assert "ABORT" in {value for key, value in _walk(monitor) if key == "next"}, name
        targets = _next_targets(workflow)
        assert {"COMPLETE", "ABORT"} <= targets, (name, targets)


def test_delivery_lanes_put_ci_before_final_gate_and_spillover() -> None:
    for name in ("yt-auto-feature", "yt-auto-fix", "yt-auto-docs", "yt-auto-maintenance"):
        names = [str(step["name"]) for step in _steps(_workflow(name))]
        assert names.index("ci_verify") < names.index("final_gate") < names.index("spillover")
        assert _step(_workflow(name), "ci_verify").get("uses") == "ci-verify"


def test_ci_verify_uses_affected_test_gate_without_weakening_other_baselines() -> None:
    instruction = (FACETS / "instructions" / "yt-auto-ci-verify.md").read_text(encoding="utf-8")

    assert "python .github/scripts/run-affected-tests.py" in instruction
    assert "nix develop --command uv run pytest -n auto\n" not in instruction
    for command in (
        "nix develop --command uv run ruff check .",
        "nix develop --command uv run ruff format --check .",
        "bash .github/scripts/any-usage-gate.sh",
        "git diff --check",
    ):
        assert command in instruction
    assert "skip" in instruction
    assert "scope" in instruction
    assert "main" in instruction


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=os.environ
        | {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "local-test-gate",
            "GIT_AUTHOR_EMAIL": "local-test-gate@example.invalid",
            "GIT_COMMITTER_NAME": "local-test-gate",
            "GIT_COMMITTER_EMAIL": "local-test-gate@example.invalid",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _local_gate_repository(tmp_path: Path) -> tuple[Path, str, Path]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "work")
    for relative in (
        ".github/scripts/select-affected-tests.py",
        ".github/scripts/run-affected-tests.py",
    ):
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    source = repository / "src/youtube_automation/core/leaf.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    test = repository / "tests/core/test_leaf.py"
    test.parent.mkdir(parents=True)
    test.write_text(
        "from youtube_automation.core.leaf import VALUE\n\ndef test_leaf(): assert VALUE == 1\n",
        encoding="utf-8",
    )
    conftest = repository / "tests/conftest.py"
    conftest.write_text("", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "base")
    base = _git(repository, "rev-parse", "HEAD")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    nix = fake_bin / "nix"
    nix.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$NIX_ARGS_LOG"\n',
        encoding="utf-8",
    )
    nix.chmod(0o755)
    return repository, base, fake_bin


def _run_local_gate(repository: Path, base: str, fake_bin: Path, args_log: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repository / ".github/scripts/run-affected-tests.py")],
        cwd=repository,
        env=os.environ
        | {
            "PRE_PUSH_DIFF_BASE": base,
            "NIX_ARGS_LOG": str(args_log),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_local_ci_gate_runs_selected_target_and_reports_count(tmp_path: Path) -> None:
    repository, base, fake_bin = _local_gate_repository(tmp_path)
    source = repository / "src/youtube_automation/core/leaf.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    args_log = tmp_path / "selected-args.txt"

    result = _run_local_gate(repository, base, fake_bin, args_log)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Selected pytest targets: 1/1" in result.stdout
    assert args_log.read_text(encoding="utf-8").splitlines() == [
        "develop",
        "--command",
        "uv",
        "run",
        "pytest",
        "-n",
        "auto",
        "--",
        "tests/core/test_leaf.py",
    ]


def test_local_ci_gate_runs_full_suite_for_fail_safe_change(tmp_path: Path) -> None:
    repository, base, fake_bin = _local_gate_repository(tmp_path)
    (repository / "tests/conftest.py").write_text("VALUE = 1\n", encoding="utf-8")
    args_log = tmp_path / "all-args.txt"

    result = _run_local_gate(repository, base, fake_bin, args_log)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Full pytest suite: 1/1 targets" in result.stdout
    assert args_log.read_text(encoding="utf-8").splitlines() == [
        "develop",
        "--command",
        "uv",
        "run",
        "pytest",
        "-n",
        "auto",
    ]


def test_local_ci_gate_runs_full_suite_when_diff_base_cannot_be_resolved(tmp_path: Path) -> None:
    repository, _, fake_bin = _local_gate_repository(tmp_path)
    source = repository / "src/youtube_automation/core/leaf.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    args_log = tmp_path / "missing-base-args.txt"

    result = _run_local_gate(repository, "missing-base", fake_bin, args_log)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Full pytest suite: 1/1 targets" in result.stdout
    assert args_log.read_text(encoding="utf-8").splitlines() == [
        "develop",
        "--command",
        "uv",
        "run",
        "pytest",
        "-n",
        "auto",
    ]


def test_no_planning_step_can_bypass_required_delivery_gates() -> None:
    for name in PUBLIC_WORKFLOWS:
        workflow = _workflow(name)
        for step in _steps(workflow):
            if step.get("name") in {"plan", "intake", "diagnose"}:
                assert "COMPLETE" not in set(_rule_targets(workflow, str(step["name"])).values()), (
                    name,
                    step["name"],
                )


def test_review_and_final_gates_fail_closed() -> None:
    review_steps = {
        "yt-auto-feature": "review_gate",
        "yt-auto-fix": "review_gate",
        "yt-auto-docs": "docs_gate",
        "yt-auto-maintenance": "review_gate",
    }
    for name, review_name in review_steps.items():
        workflow = _workflow(name)
        review = _step(workflow, review_name)
        final_gate = _step(workflow, "final_gate")
        assert "ABORT" in {value for key, value in _walk(review.get("rules")) if key == "next"}
        assert "ABORT" in {value for key, value in _walk(final_gate.get("rules")) if key == "next"}
        assert any(key == "condition" and value == "when(true)" for key, value in _walk(review.get("rules")))


def test_delivery_lanes_define_complete_fix_replan_and_abort_paths() -> None:
    expected = {
        "yt-auto-feature": ("review_gate", "fix", "replan"),
        "yt-auto-fix": ("review_gate", "fix", "diagnose"),
        "yt-auto-docs": ("docs_gate", "docs_fix", "plan"),
        "yt-auto-maintenance": ("review_gate", "fix", "plan"),
    }
    for name, (review_name, fix_target, replan_target) in expected.items():
        workflow = _workflow(name)
        review_targets = set(_rule_targets(workflow, review_name).values())
        assert {"ci_verify", fix_target, replan_target, "ABORT"} <= review_targets
        assert _rule_targets(workflow, "final_gate") == {
            "COMPLETE": "spillover",
            "needs_fix": fix_target,
            "need_replan": replan_target,
            "ABORT": "ABORT",
        }
        assert {"COMPLETE", "ABORT"} <= set(_rule_targets(workflow, "spillover").values())


def test_fix_lane_keeps_competing_hypotheses_and_pre_repair_red() -> None:
    workflow = _workflow("yt-auto-fix")
    diagnosis = (FACETS / "instructions" / "yt-auto-diagnose.md").read_text(encoding="utf-8")
    reproduce = (FACETS / "instructions" / "yt-auto-reproduce.md").read_text(encoding="utf-8")
    assert "competing hypothesis" in diagnosis
    assert "Before changing production code" in reproduce
    assert "red_confirmed" in reproduce
    assert _rule_targets(workflow, "reproduce") == {
        'when(structured.reproduce.verdict == "red_confirmed")': "repair",
        'when(structured.reproduce.verdict == "red_mismatch")': "diagnose",
        "when(true)": "ABORT",
    }


def test_lane_edit_boundaries_are_explicit_and_minimal() -> None:
    for name, expected in EDITABLE_STEPS.items():
        editable = {str(step["name"]) for step in _steps(_workflow(name)) if _expanded_step(step).get("edit") is True}
        assert editable == expected, name


def test_edit_boundaries_are_pinned_by_explicit_capability_sets() -> None:
    # step の capabilities は workflow 既定を継承ではなく置換する。edit step が宣言を落とすと
    # readonly を継承して実行時に書き込めなくなるため、宣言の有無を静的に固定する。
    for name in PUBLIC_WORKFLOWS:
        workflow = _workflow(name)
        assert _capabilities(workflow.get("capabilities"))[:1] == ["readonly"], name
        for step in _steps(workflow):
            expanded = _expanded_step(step)
            capabilities = _capabilities(expanded.get("capabilities"))
            if expanded.get("edit") is True:
                assert capabilities[:1] == ["edit"], (name, step["name"])
            else:
                assert "edit" not in capabilities, (name, step["name"])

    for path in STEPS.glob("*.yaml"):
        fragment = _load(path)
        capabilities = _capabilities(fragment.get("capabilities"))
        if fragment.get("edit") is True:
            assert capabilities[:1] == ["edit"], path

    for path in (*WORKFLOWS.glob("*.yaml"), *STEPS.glob("*.yaml")):
        for key, value in _walk(_load(path)):
            if key == "capabilities":
                assert set(_capabilities(value)) <= {"readonly", "edit", "enable-skills"}, (path, value)


def test_report_consumers_receive_concrete_artifacts_or_report_directory() -> None:
    consumers = {
        "yt-auto-design-fix": ("plan.md", "requirements-design-review.md", "test-design-review.md"),
        "yt-auto-diagnosis-fix": ("causal-review.md", "competing-hypothesis-review.md"),
        "yt-auto-review-design-gate": ("requirements-design-review.md", "architecture-design-review.md"),
        "yt-auto-review-diagnosis-gate": ("causal-review.md", "competing-hypothesis-review.md"),
        "yt-auto-review-docs-gate": ("docs-correctness-review.md", "docs-consistency-review.md"),
        "yt-auto-review-gate": ("architecture-review.md", "robustness-review.md"),
        "yt-auto-audit-supervise": ("audit-plan.md", "audit-ledger.md"),
        "yt-auto-audit-review": ("audit-plan.md", "audit-ledger.md"),
        "yt-auto-audit-publish": ("audit-ledger.md",),
    }
    instructions = FACETS / "instructions"
    for name, reports in consumers.items():
        content = (instructions / f"{name}.md").read_text(encoding="utf-8")
        for report in reports:
            assert f"{{report:{report}}}" in content, (name, report)
    for name in ("yt-auto-fix-findings", "yt-auto-spillover"):
        content = (instructions / f"{name}.md").read_text(encoding="utf-8")
        assert "{report_dir}" in content, name


def test_loop_monitors_ignore_intervening_gate_steps() -> None:
    expected = {
        "yt-auto-feature": (("design_fix", "design_review"), "design_gate"),
        "yt-auto-fix": (("diagnosis_fix", "diagnosis_review"), "diagnosis_gate"),
        "audit-unit-split": (("audit", "supervise"), "review"),
    }
    for name, (cycle, ignored) in expected.items():
        monitors = _workflow(name)["loop_monitors"]
        monitor = next(item for item in monitors if tuple(item["cycle"]) == cycle)
        assert ignored in monitor.get("ignore_steps", []), name


def test_audit_lanes_keep_append_only_ledger_and_finite_reinspection() -> None:
    audit_contract = (FACETS / "output-contracts" / "yt-auto-audit-ledger.md").read_text(encoding="utf-8")
    audit_instruction = (FACETS / "instructions" / "yt-auto-audit-run.md").read_text(encoding="utf-8")
    assert "append-only" in audit_contract
    assert "never replace" in audit_instruction
    for name in ("yt-auto-audit", "yt-auto-audit-runs"):
        workflow = _workflow(name)
        assert _step(workflow, "audit")["rules"][0]["next"] == "supervise"
        assert _step(workflow, "audit")["rules"][1]["next"] == "supervise"
        assert _step(workflow, "publish").get("edit") is True


def test_removed_legacy_internal_assets_do_not_return() -> None:
    assert not (WORKFLOWS / "yt-auto-intake.yaml").exists()
    assert not (WORKFLOWS / "yt-auto-impl-review.yaml").exists()
    assert {path.name for path in (TAKT / "schemas").glob("*.json")} == {"yt-auto-decision.json"}
    for relative in ("scripts", "facets/partials", "facets/personas", "facets/policies"):
        path = TAKT / relative
        assert not path.exists() or not any(candidate.is_file() for candidate in path.rglob("*"))
    # takt 0.60 で撤去された綴り。復活すると workflow が load 段階で落ちるか、
    # 存在しない facet を静かに参照する。
    for path in (*WORKFLOWS.glob("*.yaml"), *STEPS.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        for removed in ("provider_options", "review-readonly", "merge-readiness"):
            assert removed not in text, (path, removed)


def test_docs_and_config_match_the_public_surface() -> None:
    operations = (REPO_ROOT / "docs" / "takt-operations.md").read_text(encoding="utf-8")
    config = (TAKT / "config.yaml").read_text(encoding="utf-8")
    for name in PUBLIC_WORKFLOWS:
        assert f"`{name}`" in operations
    assert "yt-auto-intake / yt-auto-impl-review" not in operations
    assert "provider_routing:" not in config
