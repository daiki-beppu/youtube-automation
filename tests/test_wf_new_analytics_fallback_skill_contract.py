from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import doctor

_REPO_ROOT = REPO_ROOT
_FRESHNESS_RULES = _REPO_ROOT / ".claude" / "skills" / "collection-ideate" / "references" / "freshness-rules.md"


def _freshness_script() -> str:
    text = _FRESHNESS_RULES.read_text(encoding="utf-8")
    section = text.split("## 判定擬似コード", 1)[1].split("\n## ", 1)[0]
    match = re.search(r"```bash\n(?P<script>.*?)\n```", section, flags=re.DOTALL)
    assert match is not None
    return match.group("script")


def _touch(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_mode_fixture(
    tmp_path: Path,
    *,
    report: bool = False,
    benchmark: bool = False,
    data_date: str | None = None,
    report_date: str = "20260702",
    today: str = "20260702",
    freshness_days: int = 7,
) -> subprocess.CompletedProcess[str]:
    if report:
        _touch(tmp_path / f"reports/analysis_{report_date}.md", "# analysis\n")
    if benchmark:
        _touch(tmp_path / "data/benchmark_20260701.json")
    if data_date is not None:
        _touch(tmp_path / f"data/analytics_data_{data_date}.json")
    _touch(tmp_path / "docs/channel/personas/persona-definition.md", "# persona\n")
    _touch(tmp_path / "docs/plans/viewing-scene-matrix.md", "# scene\n")
    script = tmp_path / "mode-check.sh"
    script.write_text(_freshness_script(), encoding="utf-8")
    script.chmod(0o755)
    return subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env={
            **os.environ,
            "TODAY": today,
            "COLLECTION_IDEATE_FRESHNESS_DAYS": str(freshness_days),
            "COLLECTION_IDEATE_TTP_MODE": "false",
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("files", "expected_mode"),
    [
        (("reports/analysis_20260702.md",), "analytics mode"),
        (("data/benchmark_20260701.json",), "benchmark fallback mode"),
        ((), "minimal mode"),
    ],
)
def test_doctor_resolves_representative_wf_new_input_modes(tmp_path: Path, files, expected_mode: str) -> None:
    for relative in files:
        _touch(tmp_path / relative)

    resolved = doctor._resolve_wf_new_input_mode(tmp_path)

    assert resolved.mode == expected_mode
    assert resolved.stale_report is False


def test_analytics_mode_has_priority_when_benchmark_also_exists(tmp_path: Path) -> None:
    _touch(tmp_path / "reports/analysis_20260702.md", "# analysis\n")
    _touch(tmp_path / "data/benchmark_20260701.json")

    analytics = doctor.check_analytics_report(tmp_path)
    benchmark = doctor.check_benchmark_data(tmp_path)

    assert analytics.status == "ok"
    assert "analytics mode" in analytics.message
    assert benchmark.status == "ok"
    assert "analytics mode" in benchmark.message


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"report": True}, "benchmark stale 判定は /benchmark"),
        ({"benchmark": True}, "既存の data/benchmark_*.json"),
        ({}, "ttp_mode=false のため benchmark をスキップ"),
    ],
    ids=["analytics", "benchmark-fallback", "minimal"],
)
def test_freshness_mode_script_executes_each_representative_path(tmp_path: Path, kwargs, expected: str) -> None:
    result = _run_mode_fixture(tmp_path, **kwargs)

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


@pytest.mark.parametrize(
    ("data_date", "report_date", "expected_refresh"),
    [
        ("20260702", "20260622", "/analytics-analyze"),
        ("20260622", "20260622", "/analytics-collect,/analytics-analyze"),
    ],
    ids=["relative-stale", "absolute-stale"],
)
def test_freshness_script_returns_refresh_contract_for_stale_analytics(
    tmp_path: Path, data_date: str, report_date: str, expected_refresh: str
) -> None:
    result = _run_mode_fixture(
        tmp_path,
        report=True,
        data_date=data_date,
        report_date=report_date,
        today="20260702",
    )

    assert result.returncode == 3
    assert f"AUTO_REFRESH_SKILLS={expected_refresh}" in result.stdout
