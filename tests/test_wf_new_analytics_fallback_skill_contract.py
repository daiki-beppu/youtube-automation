from __future__ import annotations

import json
import os
import re
import subprocess
from contextlib import chdir
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.application.documents import MarkdownMigrationDecision, write_channel_strategy_document
from youtube_automation.commands.system import doctor
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document

_REPO_ROOT = REPO_ROOT
_FRESHNESS_RULES = _REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "freshness-rules.md"
_WF_NEW_SKILL = _REPO_ROOT / ".claude" / "skills" / "wf-new" / "SKILL.md"
_WF_NEW_PHASE2 = _REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "phase2.md"
_PERSONA_CHAIN_VALIDATOR = _REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "validate_persona_chain.py"


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


def _persona_chain(root: Path) -> None:
    persona = {
        "schema_version": 1,
        "document_type": "persona",
        "updated_at": "2026-07-02T00:00:00Z",
        "status": "confirmed",
        "persona": {"id": "persona-primary", "name": "primary", "desires": ["focus"]},
        "scene_ids": [],
        "evidence": [{"id": "ev-1", "source_path": "input.json", "observation": "fact"}],
    }
    scene = {
        "schema_version": 1,
        "document_type": "scene",
        "updated_at": "2026-07-02T00:00:00Z",
        "status": "confirmed",
        "persona_id": "persona-primary",
        "scenes": [{"id": "scene-1", "situation": "work", "desires": ["focus"], "evidence_ids": ["ev-1"]}],
        "evidence": [{"id": "ev-1", "source_path": "input.json", "observation": "fact"}],
    }
    with chdir(root):
        for relative, document in (
            ("docs/channel/personas/persona-definition.json", persona),
            ("docs/plans/viewing-scene-matrix.json", scene),
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            write_channel_strategy_document(
                target, lambda document=document: document, MarkdownMigrationDecision.NOT_REQUIRED
            )
        persona["scene_ids"] = ["scene-1"]
        target = root / "docs/channel/personas/persona-definition.json"
        target.write_text(json.dumps(persona), encoding="utf-8")
        publish_json_document(target, RepositorySchema.CHANNEL_STRATEGY)


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
    _persona_chain(tmp_path)
    validator = tmp_path / ".claude/skills/wf-new/references/validate_persona_chain.py"
    validator.parent.mkdir(parents=True, exist_ok=True)
    validator.write_bytes(_PERSONA_CHAIN_VALIDATOR.read_bytes())
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
            "UV_PROJECT": str(_REPO_ROOT),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _run_freshness_gate(root: Path, *, ttp_mode: bool) -> subprocess.CompletedProcess[str]:
    validator = root / ".claude/skills/wf-new/references/validate_persona_chain.py"
    validator.parent.mkdir(parents=True, exist_ok=True)
    validator.write_bytes(_PERSONA_CHAIN_VALIDATOR.read_bytes())
    script = root / "mode-check.sh"
    script.write_text(_freshness_script(), encoding="utf-8")
    return subprocess.run(
        ["bash", str(script)],
        cwd=root,
        env={
            **os.environ,
            "TODAY": "20260702",
            "COLLECTION_IDEATE_FRESHNESS_DAYS": "7",
            "COLLECTION_IDEATE_TTP_MODE": str(ttp_mode).lower(),
            "UV_PROJECT": str(_REPO_ROOT),
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


def test_analytics_mode_accepts_verified_structured_persona_chain_without_legacy_markdown(tmp_path: Path) -> None:
    result = _run_mode_fixture(tmp_path, report=True)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "docs/channel/personas/persona-definition.md").exists()
    assert not (tmp_path / "docs/plans/viewing-scene-matrix.md").exists()


@pytest.mark.parametrize(
    ("ttp_mode", "expected_returncode", "expected_output"),
    [
        (True, 0, "視聴シーンを仮説化して続行"),
        (False, 1, "persona 未定義"),
    ],
)
def test_analytics_mode_persona_only_intermediate_state_uses_existing_fallback(
    tmp_path: Path, ttp_mode: bool, expected_returncode: int, expected_output: str
) -> None:
    _analysis_pair(tmp_path)
    _persona_chain(tmp_path)
    (tmp_path / "docs/plans/viewing-scene-matrix.json").unlink()
    (tmp_path / "docs/plans/viewing-scene-matrix.html").unlink()

    result = _run_freshness_gate(tmp_path, ttp_mode=ttp_mode)

    assert result.returncode == expected_returncode, result.stderr
    assert "検証済み暫定 persona pair・scene 未生成" in result.stdout
    assert expected_output in result.stdout


@pytest.mark.parametrize("input_mode", ["benchmark-fallback", "minimal"])
@pytest.mark.parametrize("broken_state", ["partial-pair", "invalid-pair"])
def test_non_analytics_modes_warn_and_continue_for_unusable_persona_chain(
    tmp_path: Path, input_mode: str, broken_state: str
) -> None:
    if input_mode == "benchmark-fallback":
        _touch(tmp_path / "data/benchmark_20260701.json")
    _persona_chain(tmp_path)
    if broken_state == "partial-pair":
        (tmp_path / "docs/plans/viewing-scene-matrix.html").unlink()
    else:
        with (tmp_path / "docs/plans/viewing-scene-matrix.html").open("a", encoding="utf-8") as stream:
            stream.write("tampered")

    result = _run_freshness_gate(tmp_path, ttp_mode=False)

    assert result.returncode == 0, result.stderr
    assert "persona chain 警告" in result.stdout
    assert "初回仮説 fallback へ委譲" in result.stdout
    assert "初回仮説の視聴者像から視聴シーンを仮説化" in result.stdout


@pytest.mark.parametrize("missing_suffix", [".json", ".html"])
def test_analytics_mode_incomplete_scene_pair_fails_closed_without_mutation(
    tmp_path: Path, missing_suffix: str
) -> None:
    _analysis_pair(tmp_path)
    _persona_chain(tmp_path)
    missing = tmp_path / f"docs/plans/viewing-scene-matrix{missing_suffix}"
    missing.unlink()
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    result = _run_freshness_gate(tmp_path, ttp_mode=True)

    assert result.returncode == 1
    assert "pair 状態が不完全" in result.stdout
    for path, content in before.items():
        assert path.read_bytes() == content


@pytest.mark.parametrize(
    "broken_part",
    [
        "missing-html",
        "invalid-schema",
        "digest-mismatch",
        "persona-id-mismatch",
        "empty-references",
        "persona-missing-scene",
    ],
)
def test_analytics_mode_rejects_invalid_structured_persona_chain(tmp_path: Path, broken_part: str) -> None:
    _analysis_pair(tmp_path)
    _persona_chain(tmp_path)
    if broken_part == "missing-html":
        (tmp_path / "docs/plans/viewing-scene-matrix.html").unlink()
    elif broken_part == "invalid-schema":
        _touch(tmp_path / "docs/channel/personas/persona-definition.json", "{}")
    elif broken_part == "digest-mismatch":
        with (tmp_path / "docs/plans/viewing-scene-matrix.html").open("a", encoding="utf-8") as stream:
            stream.write("tampered")
    elif broken_part == "persona-id-mismatch":
        scene_path = tmp_path / "docs/plans/viewing-scene-matrix.json"
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
        scene["persona_id"] = "persona-other"
        scene_path.write_text(json.dumps(scene), encoding="utf-8")
        publish_json_document(scene_path, RepositorySchema.CHANNEL_STRATEGY)
    elif broken_part in {"empty-references", "persona-missing-scene"}:
        persona_path = tmp_path / "docs/channel/personas/persona-definition.json"
        persona = json.loads(persona_path.read_text(encoding="utf-8"))
        persona["scene_ids"] = [] if broken_part == "empty-references" else ["scene-other"]
        persona_path.write_text(json.dumps(persona), encoding="utf-8")
        publish_json_document(persona_path, RepositorySchema.CHANNEL_STRATEGY)
    script = tmp_path / "mode-check.sh"
    script.write_text(_freshness_script(), encoding="utf-8")
    validator = tmp_path / ".claude/skills/wf-new/references/validate_persona_chain.py"
    validator.parent.mkdir(parents=True, exist_ok=True)
    validator.write_bytes(_PERSONA_CHAIN_VALIDATOR.read_bytes())
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env={
            **os.environ,
            "TODAY": "20260702",
            "COLLECTION_IDEATE_FRESHNESS_DAYS": "7",
            "COLLECTION_IDEATE_TTP_MODE": "false",
            "UV_PROJECT": str(_REPO_ROOT),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "persona chain 検証失敗" in result.stdout
    for path, content in before.items():
        assert path.read_bytes() == content


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
    thumbnail_state_updates = [line for line in approval_step.splitlines() if "set-asset thumbnail true" in line]

    assert "assets.thumbnail" not in state_assignments
    assert "thumbnail.approved" not in state_assignments
    assert len(thumbnail_state_updates) == 3
    for update in thumbnail_state_updates:
        assert "thumbnail.jpg" in update
        assert "main.png/jpg" in update
