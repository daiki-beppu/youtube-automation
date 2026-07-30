import json
from pathlib import Path

from youtube_automation.configuration.community_draft import CommunityDraftPost

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = REPO_ROOT / "examples/channel_config.example/community-draft.example.json"


def test_community_draft_example_defines_required_post_fields() -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    posts = tuple(CommunityDraftPost(**post) for post in example["community_draft"]["posts"])

    assert posts
