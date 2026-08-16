"""サンドイッチrunner開始前の0円・容量上限判定。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from youtube_automation.core.errors import ValidationError

GIB = 1024**3


@dataclass(frozen=True, slots=True)
class HybridResourcePolicy:
    minimum_free_disk_bytes: int
    maximum_r2_retained_bytes: int
    maximum_generation_cost_usd: Decimal
    maximum_monthly_actions_minutes: int

    @classmethod
    def zero_cost(cls) -> HybridResourcePolicy:
        return cls(
            minimum_free_disk_bytes=int(Decimal("2.5") * GIB),
            maximum_r2_retained_bytes=10 * GIB,
            maximum_generation_cost_usd=Decimal("0"),
            maximum_monthly_actions_minutes=2_000,
        )


@dataclass(frozen=True, slots=True)
class HybridResourceSnapshot:
    disk_free_bytes: int
    r2_retained_bytes: int
    generation_cost_usd: Decimal
    monthly_run_count: int
    estimated_run_minutes: int

    def __post_init__(self) -> None:
        for field in ("disk_free_bytes", "r2_retained_bytes", "monthly_run_count", "estimated_run_minutes"):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValidationError(f"hybrid resource {field} は0以上の整数が必要です")
        cost = Decimal(str(self.generation_cost_usd))
        if not cost.is_finite() or cost < 0:
            raise ValidationError("hybrid resource generation_cost_usd は0以上の有限数が必要です")
        object.__setattr__(self, "generation_cost_usd", cost)


@dataclass(frozen=True, slots=True)
class HybridResourceIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class HybridResourceReport:
    snapshot: HybridResourceSnapshot
    policy: HybridResourcePolicy
    projected_monthly_actions_minutes: int
    issues: tuple[HybridResourceIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def evaluate_hybrid_resources(
    snapshot: HybridResourceSnapshot,
    policy: HybridResourcePolicy,
) -> HybridResourceReport:
    projected_minutes = (snapshot.monthly_run_count + 1) * snapshot.estimated_run_minutes
    issues: list[HybridResourceIssue] = []
    if snapshot.disk_free_bytes < policy.minimum_free_disk_bytes:
        issues.append(
            HybridResourceIssue(
                "disk_free",
                f"disk free {snapshot.disk_free_bytes} < required {policy.minimum_free_disk_bytes} bytes",
            )
        )
    if snapshot.r2_retained_bytes > policy.maximum_r2_retained_bytes:
        issues.append(
            HybridResourceIssue(
                "r2_retained",
                f"R2 retained {snapshot.r2_retained_bytes} > limit {policy.maximum_r2_retained_bytes} bytes",
            )
        )
    if snapshot.generation_cost_usd > policy.maximum_generation_cost_usd:
        issues.append(
            HybridResourceIssue(
                "generation_cost",
                f"generation cost ${snapshot.generation_cost_usd} > limit ${policy.maximum_generation_cost_usd}",
            )
        )
    if projected_minutes > policy.maximum_monthly_actions_minutes:
        issues.append(
            HybridResourceIssue(
                "actions_minutes",
                f"projected Actions minutes {projected_minutes} > limit {policy.maximum_monthly_actions_minutes}",
            )
        )
    return HybridResourceReport(snapshot, policy, projected_minutes, tuple(issues))
