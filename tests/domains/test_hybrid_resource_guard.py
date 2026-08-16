from __future__ import annotations

from decimal import Decimal

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.hybrid_resource_guard import (
    GIB,
    HybridResourcePolicy,
    HybridResourceSnapshot,
    evaluate_hybrid_resources,
)


def _snapshot(**overrides: object) -> HybridResourceSnapshot:
    values: dict[str, object] = {
        "disk_free_bytes": 3 * GIB,
        "r2_retained_bytes": 2 * GIB,
        "generation_cost_usd": Decimal("0"),
        "monthly_run_count": 10,
        "estimated_run_minutes": 45,
    }
    values.update(overrides)
    return HybridResourceSnapshot(**values)  # type: ignore[arg-type]


def test_evaluation_accepts_zero_cost_with_capacity_and_minutes_below_limits() -> None:
    report = evaluate_hybrid_resources(_snapshot(), HybridResourcePolicy.zero_cost())

    assert report.passed is True
    assert report.projected_monthly_actions_minutes == 495
    assert report.issues == ()


def test_evaluation_accepts_values_exactly_at_each_limit() -> None:
    report = evaluate_hybrid_resources(
        _snapshot(
            disk_free_bytes=int(Decimal("2.5") * GIB),
            r2_retained_bytes=10 * GIB,
            monthly_run_count=39,
            estimated_run_minutes=50,
        ),
        HybridResourcePolicy.zero_cost(),
    )

    assert report.passed is True
    assert report.projected_monthly_actions_minutes == 2_000


@pytest.mark.parametrize(
    ("overrides", "issue_code"),
    [
        ({"disk_free_bytes": int(2.5 * GIB) - 1}, "disk_free"),
        ({"r2_retained_bytes": 10 * GIB + 1}, "r2_retained"),
        ({"generation_cost_usd": Decimal("0.01")}, "generation_cost"),
        ({"monthly_run_count": 44, "estimated_run_minutes": 45}, "actions_minutes"),
    ],
)
def test_evaluation_rejects_each_limit_before_execution(overrides: dict[str, object], issue_code: str) -> None:
    report = evaluate_hybrid_resources(_snapshot(**overrides), HybridResourcePolicy.zero_cost())

    assert report.passed is False
    assert tuple(issue.code for issue in report.issues) == (issue_code,)


def test_snapshot_rejects_negative_self_reported_usage() -> None:
    with pytest.raises(ValidationError, match="monthly_run_count"):
        _snapshot(monthly_run_count=-1)
