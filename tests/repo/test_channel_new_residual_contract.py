"""Final owner contracts after removing the former channel bootstrap hub (#3823)."""

from __future__ import annotations

import os
import re
from hashlib import sha256
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "channel-strategy"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCES = SKILL_DIR / "references"
SETUP_REFERENCES = REPO_ROOT / ".claude" / "skills" / "setup" / "references"

SETUP_ASSET_SHA256 = {
    "claude-md-template.md": "64882d3cbe6c1d69c982f723d2a62bf67a88aa6895dddc79b75ce3c45857bbdd",
    "config-generation-rules.md": "73067404592646cc3073f9ca1912c703f57f25fc9a6f597c4843622f8f3f9188",
    "config-template/analytics.json": "4344ad8d4c9a1c81958b721eb3d999172f14f71f17d863a1708492ce687b68d2",
    "config-template/audio.json": "c55033dc448cb91fe3cdb47e20f220c5879c05f95855d918a8e72297a5f20a43",
    "config-template/content.json": "5a60fc3327bb2cca1daa5da3744dc218495f3f0f304aebdad41fd2ba32d1bed0",
    "config-template/meta.json": "324194e12d576604b3751af469bd7e965efb28db088b4671d76bb80b499d9da4",
    "config-template/skills/music.yaml": "5e626dc43b3ba208729d0d338683bcc014e302149d0e917e30d9877efff707be",
    "config-template/skills/thumbnail.yaml": "9b284e8ec42a52fecee9c813fd0ca042009623ce0923c30d50f1b3ad7ec7a14e",
    "config-template/youtube.json": "849f4b0912cb7be3d1cc92b7607d355e856b5af3e9e85db0449fabdf1713bb6c",
    "directory-structure.md": "d8590189cf8929b968b4f1169b723cc0ed71e0be06dbd57cc3ed405967bc4e14",
    "fetch_branding_snapshot.py": "3f7ecd1eb902ee8ae1b4002f23d6d3c7ed793d93200d87cc11777b55745a51a3",
    "generate_image.py": "537257487c8cf1b5828ddeae85ff329326d4961b6ce90bd7d1f8a16c8fa684c6",
    "schedule-template.json": "2e950062bef269cea670d219024528e06079697997f9c59f244cebdf6a6f3026",
    "verification.md": "4ce440663e0faf0f1e5916920486f9e62c3ed0a3ab86624c189ebbe19cd5d8f1",
}
STRATEGY_ASSET_SHA256 = {
    "desire-vocabulary.md": "d6a2a6eda7597b9aa66f0b140a42834807374cc80a313c9b8edb8114f3126388",
    "direction.md": "b8f62e9cbb5ea41af8dbd5ff697486950058d0ed6f6d964c27764a093ec9c440",
}
MOVED_ASSET_SHA256 = {
    "import-mode.md": "2e7a69d0e45994d4ce267a7852c475b8db86bd6971e64311bf53021f337d060b",
    "localizations-template.json": "d0267074151af61f27856d0e67e8f0c3d56cf327b2255e00a8035e2851cde558",
    "push-mode.md": "be122ecbe19c803cfe09465f68ab364636f46f92f0ec842fb803566337eb57ee",
    "regeneration-mode.md": "81b254e4ae5f63ddba121b40653100c93c55468fe3ebffbd198c32f0995f9bc7",
    "save-push-troubleshooting.md": "89a7cab34a96ddf7f10636293621c8b39e6cdf9f17e033a0469d5b14c0fc9a45",
}


def _asset_digest(path: Path) -> str:
    payload = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    return sha256(payload).hexdigest()


def _numbered_steps(markdown: str, pattern: str) -> list[str]:
    return re.findall(pattern, markdown, re.MULTILINE)


def test_strategy_owner_routes_market_analysis_and_keeps_direction_mode() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    assert "`--direction` | `references/direction.md`" in skill
    assert "/channel-research --market" in skill


def test_analysis_direction_import_and_regeneration_step_order_is_exact() -> None:
    analysis = (REPO_ROOT / ".claude" / "skills" / "channel-research" / "references" / "market.md").read_text(
        encoding="utf-8"
    )
    direction = (REFERENCES / "direction.md").read_text(encoding="utf-8")
    imported = (SETUP_REFERENCES / "import-mode.md").read_text(encoding="utf-8")
    regeneration = (SETUP_REFERENCES / "regeneration-mode.md").read_text(encoding="utf-8")

    assert _numbered_steps(analysis, r"^### Step ([0-7]):") == [str(step) for step in range(8)]
    assert _numbered_steps(direction, r"^## Step D([1-5]):") == [str(step) for step in range(1, 6)]
    assert _numbered_steps(imported, r"^## 取り込み Step ([1-8]):") == [str(step) for step in range(1, 9)]
    assert _numbered_steps(regeneration, r"^## Step R([1-8](?:\.5)?):") == [
        "1",
        "2",
        "3",
        "3.5",
        "4",
        "5",
        "6",
        "7",
        "8",
    ]


def test_every_former_asset_has_a_canonical_owner() -> None:
    assert not (REPO_ROOT / ".claude" / "skills" / "channel-new").exists()
    for relative, expected in SETUP_ASSET_SHA256.items():
        assert _asset_digest(SETUP_REFERENCES / relative) == expected
    for relative, expected in STRATEGY_ASSET_SHA256.items():
        assert _asset_digest(REFERENCES / relative) == expected
    for relative, expected in MOVED_ASSET_SHA256.items():
        assert _asset_digest(SETUP_REFERENCES / relative) == expected


def test_settings_push_contract_is_byte_exact_and_requires_review_before_apply() -> None:
    settings_mode = (SETUP_REFERENCES / "push-mode.md").read_text(encoding="utf-8")

    assert sha256(settings_mode.encode()).hexdigest() == MOVED_ASSET_SHA256["push-mode.md"]
    diff = settings_mode.index("uv run yt-channel-settings diff")
    push_dry_run = settings_mode.index("uv run yt-channel-settings push", diff)
    approval = settings_mode.index("ユーザー承認", push_dry_run)
    push_apply = settings_mode.index("uv run yt-channel-settings push --apply", approval)
    pull_dry_run = settings_mode.index("uv run yt-channel-settings pull", push_apply)
    pull_apply = settings_mode.index("uv run yt-channel-settings pull --apply", pull_dry_run)
    post_pull_diff = settings_mode.index("`--apply` 後は `git diff` で確認する", pull_apply)

    assert diff < push_dry_run < approval < push_apply < pull_dry_run < pull_apply < post_pull_diff
