"""配布する content.json テンプレートのタグ件数下限を検証する。"""

import json

import pytest

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT


@pytest.mark.parametrize(
    "path",
    [
        "examples/channel_config.example/content.json",
        ".claude/skills/setup/references/config-template/content.json",
    ],
)
def test_content_templates_use_base_only_tags_min_count(path: str) -> None:
    content = json.loads((ROOT / path).read_text(encoding="utf-8"))

    assert content["tags"]["min_count"] == 26
