from __future__ import annotations

import json

from tests.helpers.paths import REPO_ROOT

REFERENCE = REPO_ROOT / ".claude/skills/wf-new/references/collection-plan-documents.md"
SCHEMA = REPO_ROOT / ".claude/skills/wf-new/references/collection-plan.schema.json"


def test_direct_and_wf_paths_share_plan_selection_owner_and_explicit_fallbacks() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")
    skill = (REPO_ROOT / ".claude/skills/wf-new/SKILL.md").read_text(encoding="utf-8")

    for text in (reference, skill):
        assert "yt-collection-plan-select" in text
    for contract in (
        "--transport terminal",
        "--candidate-id <proposal_id>",
        "--automatic",
        "selection_source: web",
        "JSON/preview digest",
        "state を更新せず",
    ):
        assert contract in reference
    assert "通常入口・統合modeとも" in skill


def test_plan_schema_uses_candidate_cards_with_required_comparison_fields_and_preview() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    candidates = schema["properties"]["candidates"]
    candidate = schema["definitions"]["candidate"]

    assert candidates["x-view"]["presentation"] == "card"
    required = set(candidate["required"])
    assert {
        "final_title",
        "target_persona",
        "viewing_scene",
        "music_direction",
        "video_direction",
        "thumbnail_direction",
        "evidence",
        "constraint_compliance",
        "preview_assets",
    } <= required
    assert candidate["properties"]["preview_assets"]["x-view"] == {
        "order": 9,
        "presentation": "media",
        "mediaType": "image",
        "pathPrefix": "../",
    }
    assert candidate["properties"]["selection_source"]["enum"] == ["web", "terminal", "automatic"]
