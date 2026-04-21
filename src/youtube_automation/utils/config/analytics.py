"""Analytics・Benchmark の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Benchmark:
    """`benchmark` セクション（optional）."""

    channels: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Analytics:
    """`analytics` セクション + `benchmark` セクションの合成（どちらも optional）."""

    collection_filter_keywords: list[str] = field(default_factory=list)
    benchmark: Benchmark = field(default_factory=Benchmark)
