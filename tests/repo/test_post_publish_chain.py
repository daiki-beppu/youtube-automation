"""`/publish` に統合した公開チェーンの契約テスト。"""

from __future__ import annotations

import json
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
PUBLISH_DIR = ROOT / ".claude" / "skills" / "publish"
MANIFEST = PUBLISH_DIR / "references" / "publish-chain-manifest.json"


def test_publish_owns_the_only_publication_chain() -> None:
    assert not (ROOT / ".claude" / "skills" / "post-publish").exists()
    assert MANIFEST.is_file()


def test_manifest_declares_the_complete_ordered_chain_without_metadata_audit() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["chainId"] == "publish"
    assert [step["id"] for step in manifest["steps"]] == ["playlist", "upload", "community", "pinned"]
    assert all(step["skill"] == "publish" for step in manifest["steps"])
    assert all(
        set(step)
        == {
            "id",
            "skill",
            "prerequisiteArtifacts",
            "outputArtifacts",
            "approvalGate",
            "idempotency",
        }
        for step in manifest["steps"]
    )
    assert {step["idempotency"]["script"] for step in manifest["steps"]} == {"references/publish-chain-state.py"}
    assert "metadata-audit" not in MANIFEST.read_text(encoding="utf-8")


def test_publish_state_contract_has_only_skip_run_and_blocked() -> None:
    state = (PUBLISH_DIR / "references" / "publish-chain-state.py").read_text(encoding="utf-8")

    assert "EXIT_SKIP = 0" in state
    assert "EXIT_RUN = 10" in state
    assert "EXIT_BLOCKED = 20" in state
    assert "EXIT_PENDING" not in state


def test_skill_and_docs_do_not_direct_to_removed_entrypoint() -> None:
    matches: list[Path] = []
    for base in (ROOT / ".claude" / "skills", ROOT / "docs"):
        for path in base.rglob("*"):
            is_text = path.is_file() and path.suffix in {".md", ".json", ".py"}
            text = path.read_text(encoding="utf-8") if is_text else ""
            if "/post-publish" in text or ".claude/skills/post-publish" in text:
                matches.append(path.relative_to(ROOT))

    assert matches == []


def test_publish_is_resumable_from_the_first_state_check() -> None:
    skill = (PUBLISH_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "先頭" in skill
    assert "完了済み" in skill
    assert "skip" in skill
    chain = skill.split("## Chain Contract", 1)[1].split("## Instructions", 1)[0]
    assert "metadata-audit" not in chain
