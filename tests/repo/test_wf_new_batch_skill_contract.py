import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT


def _read_skill(name: str) -> str:
    return (REPO_ROOT / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


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
            "producer": "collection-ideate",
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


def test_collection_ideate_batch_plan_is_explicit_and_fail_closed() -> None:
    text = _read_skill("collection-ideate")

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


def test_collection_ideate_single_collection_completion_contract_remains() -> None:
    text = _read_skill("collection-ideate")

    assert "20-documentation/plan_proposals.md" in text
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
