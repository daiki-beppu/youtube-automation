"""Executable /market-research classification and persistence contracts."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".claude" / "skills" / "market-research" / "references" / "market_research_contract.py"


def _load_contract():
    spec = importlib.util.spec_from_file_location("market_research_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _load_contract()


def _report() -> str:
    return contract.render_report({section: f"{section} body" for section in contract.SECTIONS})


def test_market_research_hard_gates_are_near_the_top() -> None:
    assert (
        contract.classify_candidate(
            "ttp",
            {
                "direct_observations": 2,
                "primary_sources": 1,
                "comparable_observations": 1,
                "limitations": 1,
            },
        )
        == "候補"
    )
    assert (
        contract.classify_candidate(
            "ttp",
            {
                "direct_observations": 2,
                "primary_sources": 1,
                "comparable_observations": 1,
                "limitations": 1,
                "reproducible": False,
            },
        )
        == "非推奨"
    )


def test_market_research_reference_exists_and_defines_all_report_sections() -> None:
    report = _report()
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [f"## {section}" for section in contract.SECTIONS]
    with pytest.raises(ValueError, match="missing report sections"):
        contract.render_report({"調査問い": "only one"})


def test_dry_run_without_save_request_creates_no_artifact(tmp_path: Path) -> None:
    assert contract.deliver_report(_report(), channel_dir=tmp_path) is None
    assert list(tmp_path.rglob("*")) == []


def test_dry_run_with_save_request_uses_dated_path_only(tmp_path: Path) -> None:
    target = contract.deliver_report(
        _report(),
        channel_dir=tmp_path,
        save=True,
        today=date(2026, 7, 31),
    )
    assert target == tmp_path / "docs" / "research" / "market-2026-07-31.md"
    assert target.read_text(encoding="utf-8") == _report()
    with pytest.raises(FileExistsError, match="overwrite approval"):
        contract.deliver_report(
            "replacement",
            channel_dir=tmp_path,
            save=True,
            today=date(2026, 7, 31),
        )
    assert target.read_text(encoding="utf-8") == _report()


def test_dry_run_with_insufficient_evidence_is_fail_closed() -> None:
    assert (
        contract.classify_candidate(
            "ttp",
            {
                "direct_observations": 1,
                "primary_sources": 1,
                "comparable_observations": 1,
                "limitations": 1,
            },
        )
        == "保留（根拠不足）"
    )
    assert (
        contract.classify_candidate(
            "niche",
            {"demand_sources": 1, "differentiation_sources": 0, "persona_elements": 5},
        )
        == "保留（根拠不足）"
    )
    assert (
        contract.classify_candidate(
            "niche",
            {"demand_sources": 1, "differentiation_sources": 1, "persona_elements": 5},
        )
        == "候補"
    )


def test_channel_new_and_discovery_keep_distinct_routes() -> None:
    assert contract.route_for("market-comparison") == "market-research"
    assert contract.route_for("discover") == "discover-competitors"
    assert contract.route_for("analyze-collected") == "channel-new"
