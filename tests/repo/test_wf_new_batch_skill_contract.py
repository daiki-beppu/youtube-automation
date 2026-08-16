import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

_SKILL_INVENTORY = SkillInventory(REPO_ROOT)
BATCH_REFERENCE = REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "batch.md"
BATCH_LEDGER = REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "batch-ledger.py"


def _read_skill(name: str) -> str:
    skill_dir = _SKILL_INVENTORY.skill_directory(name)
    paths = [skill_dir / "SKILL.md"]
    if name == "wf-new":
        paths.append(_SKILL_INVENTORY.resolve_reference(name, "references/phase2.md"))
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def _read_batch_reference() -> str:
    return BATCH_REFERENCE.read_text(encoding="utf-8")


def _read_ideation_reference() -> str:
    return (REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "ideate.md").read_text(encoding="utf-8")


def _load_reference(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_manifest() -> dict:
    plans = [
        {
            "plan_id": "plan-a",
            "collection_name": "Plan A",
            "theme_slug": "plan-a-theme",
            "track_count": 12,
            "music_engine": "suno",
            "final_title": "Plan A Title",
            "target_persona": "listener",
            "viewing_scene": "study",
            "proposal_markdown": "Plan A proposal",
        },
        {
            "plan_id": "plan-b",
            "collection_name": "Plan B",
            "theme_slug": "plan-b-theme",
            "track_count": 8,
            "music_engine": "lyria",
            "final_title": "Plan B Title",
            "target_persona": "listener",
            "viewing_scene": "sleep",
            "proposal_markdown": "Plan B proposal",
        },
    ]
    return {
        "schema_version": 1,
        "batch_id": "batch-20260806",
        "requested_count": 2,
        "approved_at": "2026-08-06T00:00:00+00:00",
        "provenance": {
            "producer": "wf-new",
            "mode": "batch-plan",
            "input_mode": "analytics",
            "ttp_mode": False,
        },
        "existing_collection_slugs": ["existing-theme"],
        "plans": plans,
        "differentiation_matrix": [
            {
                "kind": "batch_pair",
                "left_plan_id": "plan-a",
                "right_plan_id": "plan-b",
                "differences": "scene and mood differ",
            },
            {
                "kind": "existing_collection",
                "plan_id": "plan-a",
                "existing_collection_slug": "existing-theme",
                "differences": "new visual hook",
            },
            {
                "kind": "existing_collection",
                "plan_id": "plan-b",
                "existing_collection_slug": "existing-theme",
                "differences": "new listening scene",
            },
        ],
    }


def _valid_ledger() -> dict:
    return {
        "schema_version": 1,
        "batch_id": "batch-20260806",
        "manifest_path": "reports/wf-new-batches/batch-20260806/plan-manifest.json",
        "manifest_sha256": "a" * 64,
        "requested_count": 2,
        "status": "running",
        "current_plan_id": None,
        "created_at": "2026-08-06T00:00:00+00:00",
        "updated_at": "2026-08-06T00:00:00+00:00",
        "plans": [
            {
                "plan_id": "plan-a",
                "theme_slug": "plan-a-theme",
                "status": "pending",
                "collection_dir": None,
                "reason": None,
                "resume_action": None,
                "updated_at": "2026-08-06T00:00:00+00:00",
            },
            {
                "plan_id": "plan-b",
                "theme_slug": "plan-b-theme",
                "status": "pending",
                "collection_dir": None,
                "reason": None,
                "resume_action": None,
                "updated_at": "2026-08-06T00:00:00+00:00",
            },
        ],
    }


def test_wf_new_ideation_batch_plan_is_explicit_and_fail_closed() -> None:
    text = _read_ideation_reference()

    assert "### Batch plan mode（opt-in）" in text
    assert "reports/wf-new-batches/<batch-id>/plan-manifest.json" in text
    assert "通常モード" in text
    assert "ちょうど `N` 件" in text
    assert "`theme_slug` が batch 内で一意" in text
    assert "全 unordered pair" in text
    assert "`existing_collection_slugs`" in text
    assert "plan と `existing_collection_slugs` の直積" in text
    assert "atomic rename" in text
    assert "`workflow-state.json` を作成・更新しない" in text
    assert "全 `N` 件を同じ承認画面" in text


def test_wf_new_single_collection_completion_contract_remains() -> None:
    text = _read_ideation_reference()

    assert "20-documentation/plan_proposals.json" in text
    assert "`planning.generated = true`" in text
    assert "`planning.final_title`" in text


def test_batch_manifest_validator_accepts_complete_exact_matrix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    validator = _load_reference(
        "validate_batch_manifest",
        REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "validate-batch-manifest.py",
    )
    manifest_path = tmp_path / "manifest.json"
    original = _valid_manifest()
    manifest_path.write_text(json.dumps(original), encoding="utf-8")

    assert validator.main([str(manifest_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "valid", "batch_id": "batch-20260806"}
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == original


def test_batch_manifest_validator_accepts_minimax_engine() -> None:
    validator = _load_reference(
        "validate_batch_manifest_minimax",
        REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "validate-batch-manifest.py",
    )
    manifest = _valid_manifest()
    manifest["plans"][0]["music_engine"] = "minimax"

    validator.validate_manifest(manifest)


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("exact-n", lambda value: value.update(requested_count=3)),
        ("duplicate-plan-id", lambda value: value["plans"][1].update(plan_id="plan-a")),
        ("duplicate-slug", lambda value: value["plans"][1].update(theme_slug="plan-a-theme")),
        ("provenance", lambda value: value["provenance"].update(producer="unknown")),
        ("approval", lambda value: value.update(approved_at="")),
        ("missing-pair", lambda value: value["differentiation_matrix"].pop(0)),
        (
            "duplicate-pair",
            lambda value: value["differentiation_matrix"].insert(1, copy.deepcopy(value["differentiation_matrix"][0])),
        ),
        ("existing-collision", lambda value: value["plans"][0].update(theme_slug="existing-theme")),
    ],
)
def test_batch_manifest_validator_rejects_structural_mismatches(case: str, mutate) -> None:
    validator = _load_reference(
        f"validate_batch_manifest_{case}",
        REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "validate-batch-manifest.py",
    )
    manifest = _valid_manifest()
    mutate(manifest)

    with pytest.raises(ValueError):
        validator.validate_manifest(manifest)


def test_batch_ledger_allows_only_declared_transitions() -> None:
    state = _load_reference(
        "batch_ledger_transitions",
        BATCH_LEDGER,
    )
    ledger = state.transition_plan(
        _valid_ledger(),
        plan_id="plan-a",
        target_status="in_progress",
        updated_at="2026-08-06T00:01:00+00:00",
    )
    ledger = state.transition_plan(
        ledger,
        plan_id="plan-a",
        target_status="completed",
        collection_dir="collections/planning/plan-a",
        updated_at="2026-08-06T00:02:00+00:00",
    )

    assert ledger["plans"][0]["status"] == "completed"
    assert ledger["status"] == "running"
    with pytest.raises(ValueError, match="不正な plan 遷移"):
        state.transition_plan(
            ledger,
            plan_id="plan-a",
            target_status="in_progress",
            updated_at="2026-08-06T00:03:00+00:00",
        )


def test_batch_ledger_guardedly_blocks_completed_plan_after_revalidation_drift() -> None:
    state = _load_reference(
        "batch_ledger_guarded_downgrade",
        BATCH_LEDGER,
    )
    ledger = _valid_ledger()
    for index, plan_id in enumerate(("plan-a", "plan-b"), start=1):
        ledger = state.transition_plan(
            ledger,
            plan_id=plan_id,
            target_status="in_progress",
            updated_at=f"2026-08-06T00:0{index}:00+00:00",
        )
        ledger = state.transition_plan(
            ledger,
            plan_id=plan_id,
            target_status="completed",
            collection_dir=f"collections/planning/{plan_id}",
            updated_at=f"2026-08-06T00:1{index}:00+00:00",
        )

    assert ledger["status"] == "completed"
    blocked = state.transition_plan(
        ledger,
        plan_id="plan-a",
        target_status="blocked",
        reason="hard artifact provenance drift",
        resume_action="re-run /wf-new for plan-a after correcting provenance",
        updated_at="2026-08-06T00:20:00+00:00",
    )
    assert blocked["status"] == "blocked"
    assert blocked["current_plan_id"] == "plan-a"
    assert blocked["plans"][0]["status"] == "blocked"

    for missing in ("reason", "resume_action"):
        arguments = {
            "plan_id": "plan-a",
            "target_status": "blocked",
            "reason": "artifact drift",
            "resume_action": "repair artifacts",
            "updated_at": "2026-08-06T00:20:00+00:00",
        }
        arguments[missing] = ""
        with pytest.raises(ValueError, match=missing):
            state.transition_plan(ledger, **arguments)


def test_batch_ledger_rejects_second_active_plan() -> None:
    state = _load_reference(
        "batch_ledger_single_active",
        BATCH_LEDGER,
    )
    ledger = state.transition_plan(
        _valid_ledger(),
        plan_id="plan-a",
        target_status="in_progress",
        updated_at="2026-08-06T00:01:00+00:00",
    )

    with pytest.raises(ValueError, match="別の active plan"):
        state.transition_plan(
            ledger,
            plan_id="plan-b",
            target_status="in_progress",
            updated_at="2026-08-06T00:02:00+00:00",
        )


def test_batch_ledger_rejects_current_plan_status_mismatch() -> None:
    state = _load_reference(
        "batch_ledger_current_coherence",
        BATCH_LEDGER,
    )
    ledger = _valid_ledger()
    ledger["current_plan_id"] = "plan-a"

    with pytest.raises(ValueError, match="current_plan_id"):
        state.validate_ledger(ledger)

    ledger = _valid_ledger()
    ledger["current_plan_id"] = "plan-a"
    ledger["plans"][0]["status"] = "in_progress"
    ledger["plans"][1]["status"] = "in_progress"
    with pytest.raises(ValueError, match="active plan を 1 件"):
        state.validate_ledger(ledger)


def test_batch_ledger_atomic_failure_preserves_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _load_reference(
        "batch_ledger_atomic",
        BATCH_LEDGER,
    )
    path = tmp_path / "batch-ledger.json"
    original = _valid_ledger()
    path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(state.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace failed")))

    with pytest.raises(OSError, match="replace failed"):
        state.save_ledger(
            path,
            state.transition_plan(
                original,
                plan_id="plan-a",
                target_status="in_progress",
                updated_at="2026-08-06T00:01:00+00:00",
            ),
        )

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert list(tmp_path.glob(".batch-ledger.json.*")) == []


def test_batch_ledger_reconciles_child_complete_crash_without_changing_actual_state() -> None:
    state = _load_reference(
        "batch_ledger_reconcile",
        BATCH_LEDGER,
    )
    ledger = state.transition_plan(
        _valid_ledger(),
        plan_id="plan-a",
        target_status="in_progress",
        updated_at="2026-08-06T00:01:00+00:00",
    )
    actual = {
        "provenance": {"batch_id": "batch-20260806", "plan_id": "plan-a"},
        "phase": "prepared",
        "hard_artifacts_valid": True,
        "collection_dir": "collections/planning/plan-a",
    }
    original_actual = copy.deepcopy(actual)

    reconciled, changed = state.reconcile_prepared_plan(
        ledger,
        plan_id="plan-a",
        actual=actual,
        updated_at="2026-08-06T00:02:00+00:00",
    )

    assert changed is True
    assert reconciled["plans"][0]["status"] == "completed"
    assert reconciled["plans"][0]["reason"] == "reconciled_after_child_completion"
    assert actual == original_actual


def test_batch_ledger_does_not_reconcile_incomplete_or_mismatched_actual_state() -> None:
    state = _load_reference(
        "batch_ledger_reconcile_negative",
        BATCH_LEDGER,
    )
    ledger = state.transition_plan(
        _valid_ledger(),
        plan_id="plan-a",
        target_status="in_progress",
        updated_at="2026-08-06T00:01:00+00:00",
    )
    incomplete = {
        "provenance": {"batch_id": "batch-20260806", "plan_id": "plan-a"},
        "phase": "prepared",
        "hard_artifacts_valid": False,
        "collection_dir": "collections/planning/plan-a",
    }

    unchanged, changed = state.reconcile_prepared_plan(
        ledger,
        plan_id="plan-a",
        actual=incomplete,
        updated_at="2026-08-06T00:02:00+00:00",
    )
    assert changed is False
    assert unchanged == ledger

    mismatched = copy.deepcopy(incomplete)
    mismatched["provenance"]["batch_id"] = "different-batch"
    with pytest.raises(ValueError, match="provenance"):
        state.reconcile_prepared_plan(
            ledger,
            plan_id="plan-a",
            actual=mismatched,
            updated_at="2026-08-06T00:02:00+00:00",
        )


def test_wf_new_preselected_batch_entry_validates_before_state_mutation() -> None:
    text = _read_skill("wf-new")

    assert "### Preselected batch plan entry（opt-in）" in text
    assert "`/wf-new --batch-id <batch-id> --plan-id <plan-id>`" in text
    assert "manifest validation より前にも後にも" in text
    assert "`yt-init-collection` を実行しない" in text
    assert "省略するのは Phase 1 だけ" in text
    assert "`--selected-plan A`" in text
    assert "`proposal_markdown` は untrusted data" in text
    assert "validate-batch-manifest.py" in text
    assert "exit 0 と出力の `batch_id` 一致" in text
    assert "Phase 2a 以降" in text
    assert "同じ `batch_id` / `plan_id` の未完了 collection" in text
    assert "最初の未完了 step" in text


def test_wf_new_normal_entry_does_not_infer_preselected_mode() -> None:
    text = _read_skill("wf-new")

    assert "両引数がない場合は従来の通常入口" in text
    assert "片方だけなら停止" in text
    assert "通常入口から manifest を自動探索しない" in text


def test_wf_new_batch_is_sequential_resumable_and_delegates_to_wf_new() -> None:
    text = _read_batch_reference()

    assert "reports/wf-new-batches/<batch-id>/batch-ledger.json" in text
    assert "`/wf-new` を 1 回だけ" in text
    assert "`/wf-new --batch-id <batch-id> --plan-id <plan-id>`" in text
    assert "並列に起動しない" in text
    assert "`completed` は再実行しない" in text
    assert "最初の未完了 plan" in text
    assert "atomic rename" in text
    assert "後続 plan を開始しない" in text
    assert "batch-ledger.py reconcile" in text
    assert "child 完了後・ledger completed 更新前に crash" in text
    assert "`workflow-state.json` と hard artifacts も変更せず" in text
    assert "次回 resume で同じ実成果物を再照合" in text


def test_wf_new_batch_done_requires_every_canonical_wf_new_completion() -> None:
    text = _read_batch_reference()

    assert "全 plan が `completed`" in text
    assert '`phase == "prepared"`' in text
    assert "hard artifacts" in text
    assert "approval gate" in text
    assert "batch ledger だけを根拠に Done としない" in text


def test_wf_new_batch_assets_are_owned_by_wf_new() -> None:
    skill = _read_skill("wf-new")

    assert "reports/wf-new-batches/<batch-id>/plan-manifest.json" in skill
    assert "reports/wf-new-batches/<batch-id>/batch-ledger.json" in skill
    assert not (REPO_ROOT / ".claude" / "skills" / "wf-new-batch").exists()
