"""Deterministic classification and persistence contract for channel-research market mode."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, TypedDict

SECTIONS = (
    "調査問い",
    "比較対象と評価軸",
    "根拠",
    "TTP 入替候補",
    "ニッチ仮説",
    "不確実性",
    "次の検証",
)


class CandidateEvidence(TypedDict, total=False):
    direct_observations: int
    primary_sources: int
    comparable_observations: int
    limitations: int
    demand_sources: int
    differentiation_sources: int
    persona_elements: int
    refuting_sources: int
    reproducible: bool


def classify_candidate(kind: Literal["ttp", "niche"], evidence: CandidateEvidence) -> str:
    """Apply the report contract without allowing unsupported recommendations."""
    if evidence.get("reproducible") is False or evidence.get("refuting_sources", 0) > sum(
        value
        for key, value in evidence.items()
        if key.endswith("_sources") and key != "refuting_sources" and isinstance(value, int)
    ):
        return "非推奨"
    if kind == "ttp":
        supported = (
            evidence.get("direct_observations", 0) >= 2
            and evidence.get("primary_sources", 0) >= 1
            and evidence.get("comparable_observations", 0) >= 1
            and evidence.get("limitations", 0) >= 1
        )
    else:
        supported = (
            evidence.get("demand_sources", 0) >= 1
            and evidence.get("differentiation_sources", 0) >= 1
            and evidence.get("persona_elements", 0) == 5
        )
    return "候補" if supported else "保留（根拠不足）"


def render_report(values: dict[str, str]) -> str:
    """Render exactly the seven ordered report sections."""
    missing = [section for section in SECTIONS if section not in values]
    if missing:
        raise ValueError(f"missing report sections: {', '.join(missing)}")
    return "\n\n".join(f"## {section}\n\n{values[section].rstrip()}" for section in SECTIONS) + "\n"


def deliver_report(
    report: str,
    *,
    channel_dir: Path,
    save: bool = False,
    today: date | None = None,
    overwrite: bool = False,
) -> Path | None:
    """Return in-memory by default and write only after explicit save/overwrite."""
    if not save:
        return None
    target = channel_dir / "docs" / "research" / f"market-{(today or date.today()).isoformat()}.md"
    if target.exists() and not overwrite:
        raise FileExistsError(f"explicit overwrite approval required: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return target


def route_for(intent: Literal["market-comparison", "discover", "analyze-collected"]) -> str:
    """Keep market comparison, discovery, and collected-data analysis distinct."""
    return {
        "market-comparison": "channel-research --market",
        "discover": "channel-research --discover",
        "analyze-collected": "channel-research --market",
    }[intent]
