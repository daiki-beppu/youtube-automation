from tests.helpers.paths import REPO_ROOT


def _read_skill(name: str) -> str:
    return (REPO_ROOT / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


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
