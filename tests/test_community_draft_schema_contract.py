import json
from pathlib import Path

from youtube_automation.configuration.community_draft import CommunityDraftPost

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = REPO_ROOT / "examples/channel_config.example/community-draft.example.json"
ADR_PATH = REPO_ROOT / "docs/adr/0019-community-helper-extension.md"


def test_community_draft_example_defines_required_post_fields() -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    posts = tuple(CommunityDraftPost(**post) for post in example["community_draft"]["posts"])

    assert posts


def test_community_draft_contract_fixes_sources_and_schedule_semantics() -> None:
    text = ADR_PATH.read_text(encoding="utf-8")

    for required in (
        "workflow-state.json::planning.final_title",
        "workflow-state.json::planning.publish_target_at",
        "community-draft.json::community_draft.variables.custom_message",
        "youtube.json::youtube.default_publish_timezone",
        "schedule_offset_days",
        "schedule_time",
        "ISO 8601 datetime including its UTC offset",
        "missing file is an error",
    ):
        assert required in text
