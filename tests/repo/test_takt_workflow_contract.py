"""takt 0.55 系 workflow の利用者向け契約を静的に検証する。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT

TAKT = REPO_ROOT / ".takt"
WORKFLOWS = TAKT / "workflows"
STEPS = TAKT / "steps"
FACETS = TAKT / "facets"

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
    allowed_builtin_calls = {
        "merge-readiness-final-gate",
        "merge-readiness-finding-contract-final-gate",
    }
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


def test_docs_and_config_match_the_public_surface() -> None:
    operations = (REPO_ROOT / "docs" / "takt-operations.md").read_text(encoding="utf-8")
    config = (TAKT / "config.yaml").read_text(encoding="utf-8")
    for name in PUBLIC_WORKFLOWS:
        assert f"`{name}`" in operations
    assert "yt-auto-intake / yt-auto-impl-review" not in operations
    assert "provider_routing:" not in config
