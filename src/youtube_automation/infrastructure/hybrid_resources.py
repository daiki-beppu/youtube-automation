"""runner開始前のホスト・MediaStore容量観測。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from youtube_automation.core.errors import ResourceLimitError
from youtube_automation.domains.hybrid_resource_guard import HybridResourceSnapshot


class RetainedCapacityProbe(Protocol):
    def retained_bytes(self) -> int: ...


@dataclass(frozen=True, slots=True)
class SystemHybridResourceProbe:
    channel_dir: Path
    store: RetainedCapacityProbe
    generation_cost_usd: Decimal
    monthly_run_count: int
    estimated_run_minutes: int

    def inspect(self) -> HybridResourceSnapshot:
        try:
            disk_free_bytes = shutil.disk_usage(self.channel_dir).free
            r2_retained_bytes = self.store.retained_bytes()
        except OSError as error:
            raise ResourceLimitError(f"hybrid resource probe failed: {error}") from error
        return HybridResourceSnapshot(
            disk_free_bytes=disk_free_bytes,
            r2_retained_bytes=r2_retained_bytes,
            generation_cost_usd=self.generation_cost_usd,
            monthly_run_count=self.monthly_run_count,
            estimated_run_minutes=self.estimated_run_minutes,
        )
