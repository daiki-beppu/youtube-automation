from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import doctor
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document

_REPO_ROOT = REPO_ROOT
_FRESHNESS_RULES = _REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "freshness-rules.md"
_WF_NEW_SKILL = _REPO_ROOT / ".claude" / "skills" / "wf-new" / "SKILL.md"
_WF_NEW_PHASE2 = _REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "phase2.md"


def _wf_new_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in (_WF_NEW_SKILL, _WF_NEW_PHASE2))


def _freshness_script() -> str:
    text = _FRESHNESS_RULES.read_text(encoding="utf-8")
    section = text.split("## 判定擬似コード", 1)[1].split("\n## ", 1)[0]
    match = re.search(r"```bash\n(?P<script>.*?)\n```", section, flags=re.DOTALL)
    assert match is not None
    return match.group("script")


def _touch(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _analysis_pair(root: Path, report_date: str = "20260702") -> None:
    path = root / f"reports/analysis_{report_date}.json"
    _touch(
        path,
        json.dumps(
            {
                "schema_version": 3,
                "generated_at": "2026-07-02T00:00:00Z",
                "summary": "分析サマリ",
                "inputs": {},
                "cli_outputs": {},
                "vpd_ranking": {},
                "win_pattern": {},
                "strategic_improvements": [],
                "next_collection_candidates": [],
                "action_plan": [],
                "strategic_discussion": [],
            }
        ),
    )
    publish_json_document(path, RepositorySchema.ANALYSIS_REPORT)


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
        _touch(tmp_path / f"reports/analysis_{report_date}.json", "{}")
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
        (("analysis-pair",), "analytics mode"),
        (("data/benchmark_20260701.json",), "benchmark fallback mode"),
        ((), "minimal mode"),
    ],
)
def test_doctor_resolves_representative_wf_new_input_modes(tmp_path: Path, files, expected_mode: str) -> None:
    for relative in files:
        if relative == "analysis-pair":
            _analysis_pair(tmp_path)
        else:
            _touch(tmp_path / relative)

    resolved = doctor._resolve_wf_new_input_mode(tmp_path)

    assert resolved.mode == expected_mode
    assert resolved.stale_report is False


def test_analytics_mode_has_priority_when_benchmark_also_exists(tmp_path: Path) -> None:
    _analysis_pair(tmp_path)
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
        ({"report": True}, "benchmark stale 判定は /channel-research --benchmark"),
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
        ("20260702", "20260622", "/analytics --analyze"),
        ("20260622", "20260622", "/analytics --collect,/analytics --analyze"),
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


def test_wf_new_routes_preview_finalization_before_thumbnail_fallback() -> None:
    skill = _wf_new_text()
    thumbnail_step = skill.split("##### 2c-1. サムネイル候補生成", 1)[1].split(
        "##### 2c-2. サムネイル承認・確定 + 音楽素材生成", 1
    )[0]

    finalizer = "finalize_planning_preview.py <collection-path>"
    assert finalizer in thumbnail_step
    assert "status: FINALIZED" in thumbnail_step
    assert "status: MISSING" in thumbnail_step
    assert thumbnail_step.index(finalizer) < thumbnail_step.index("/thumbnail <theme>")
    assert "FINALIZED" in thumbnail_step and "AI 生成" in thumbnail_step
    assert "MISSING" in thumbnail_step and "既存 `/thumbnail <theme>`" in thumbnail_step


def test_wf_new_preview_path_keeps_quality_state_and_textless_contracts() -> None:
    skill = _wf_new_text()
    approval_step = skill.split("##### 2c-2. サムネイル承認・確定 + 音楽素材生成", 1)[1].split(
        "#### 2e. ループ動画生成", 1
    )[0]

    for contract in (
        "/thumbnail --compare",
        "未設定または `true`",
        "share_thumbnail_as_main.py <collection-path>",
    ):
        assert contract in approval_step
    assert "`planning-preview.png` から確定済み" in approval_step
    assert "再度 AskUserQuestion にかけない" in approval_step


def test_wf_new_records_thumbnail_approval_in_canonical_asset_state_only() -> None:
    skill = _wf_new_text()
    approval_step = skill.split("##### 2c-2. サムネイル承認・確定 + 音楽素材生成", 1)[1].split(
        "#### 2e. ループ動画生成", 1
    )[0]

    state_assignments = re.findall(r"(?:`)?([a-z_]+(?:\.[a-z_]+)+)\s*=\s*true", approval_step)
    thumbnail_state_updates = [line for line in approval_step.splitlines() if "assets.thumbnail = true" in line]

    assert state_assignments.count("assets.thumbnail") == 3
    assert "thumbnail.approved" not in state_assignments
    assert len(thumbnail_state_updates) == 3
    for update in thumbnail_state_updates:
        assert "thumbnail.jpg" in update
        assert "main.png/jpg" in update
