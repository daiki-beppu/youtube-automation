"""GitHub Actions の supply-chain pinning 契約。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_USES_LINE = re.compile(
    r"^\s*-?\s*uses:\s+([^\s@]+/[^\s@]+)@([0-9a-f]{40})\s+#\s+(\S+)\s*$",
    re.MULTILINE,
)

_EXPECTED_ACTIONS = {
    "actions/cache": ("55cc8345863c7cc4c66a329aec7e433d2d1c52a9", "v6.1.0"),
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    "astral-sh/setup-uv": ("c771a70e6277c0a99b617c7a806ffedaca235ff9", "v9.0.0"),
    "cachix/install-nix-action": ("630ae543ea3a38a9a4166f03376c02c50f408342", "v31.11.0"),
    "DeterminateSystems/nix-installer-action": ("ef8a148080ab6020fd15196c2084a2eea5ff2d25", "v22"),
    "softprops/action-gh-release": ("3d0d9888cb7fd7b750713d6e236d1fcb99157228", "v3.0.2"),
}


@pytest.mark.parametrize("workflow", sorted(_WORKFLOWS_DIR.glob("*.yml")), ids=lambda path: path.name)
def test_third_party_actions_are_pinned_to_documented_commit_sha(workflow: Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    uses_lines = [line for line in text.splitlines() if re.match(r"^\s*-?\s*uses:\s+", line)]
    matches = list(_USES_LINE.finditer(text))

    assert len(matches) == len(uses_lines), f"{workflow.name}: mutable または version comment のない uses がある"
    for match in matches:
        action, sha, version = match.groups()
        assert action in _EXPECTED_ACTIONS, f"{workflow.name}: 未棚卸し action: {action}"
        assert (sha, version) == _EXPECTED_ACTIONS[action], f"{workflow.name}: {action} の pin が不一致"


def test_every_catalogued_action_is_used() -> None:
    used = {
        match.group(1)
        for workflow in _WORKFLOWS_DIR.glob("*.yml")
        for match in _USES_LINE.finditer(workflow.read_text(encoding="utf-8"))
    }
    assert used == set(_EXPECTED_ACTIONS)
