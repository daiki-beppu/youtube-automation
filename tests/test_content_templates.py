"""配布する content.json テンプレートのタグ件数下限を検証する。"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path",
    [
        "examples/channel_config.example/content.json",
        ".claude/skills/channel-new/references/config-template/content.json",
    ],
)
def test_content_templates_use_base_only_tags_min_count(path: str) -> None:
    content = json.loads((ROOT / path).read_text(encoding="utf-8"))

    assert content["tags"]["min_count"] == 26
