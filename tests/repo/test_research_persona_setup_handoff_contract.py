"""Research/persona opening handoffs owned by ``/setup --channel``."""

from __future__ import annotations

from hashlib import sha256

from tests.helpers.paths import REPO_ROOT

SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
TARGET_SKILLS = (
    "audience-persona-design",
    "benchmark",
    "discover-competitors",
    "market-research",
    "thumbnail-research",
    "video-analyze",
    "viewer-voice",
    "viewing-scene",
)
EXPECTED_CHANNEL_NEW_OCCURRENCES = {
    "audience-persona-design": 1,
    "benchmark": 3,
    "discover-competitors": 5,
    "market-research": 3,
    "thumbnail-research": 3,
    "video-analyze": 1,
    "viewer-voice": 1,
    "viewing-scene": 1,
}
EXPECTED_SETUP_OCCURRENCES = {
    "audience-persona-design": 3,
    "benchmark": 2,
    "discover-competitors": 3,
    "market-research": 1,
    "thumbnail-research": 0,
    "video-analyze": 0,
    "viewer-voice": 4,
    "viewing-scene": 4,
}
OPENING_ROUTE_MARKERS = {
    "audience-persona-design": (
        "`/setup --channel` Step 7 から呼ばれた経路",
        "新規チャンネルは `/setup --channel` Step 4",
        "`/setup --channel` Step 5 または Step 7",
    ),
    "benchmark": (
        "新規チャンネルは `/setup --channel` Step 4",
        "`/setup --channel` Step 5（`.claude/skills/setup/references/ttp-seed-and-duration.md`）",
    ),
    "discover-competitors": (
        "前工程の `/setup` は `/setup --channel` Step 6",
        "標準フローでは本スキルを実行せず",
        "`/setup --channel` Step 1/4/5",
        "`/setup --channel`: TTP 対象確認と初期 config 生成",
    ),
    "market-research": ("`/setup --channel` Step 1/4/5（`.claude/skills/setup/references/new-channel-bootstrap.md`",),
    "viewer-voice": (
        "新規開設では /setup --channel Step 7 で必須",
        "`/setup --channel` の新規開設モードでは Step 7",
        "新規チャンネルは `/setup --channel` Step 4",
        "`/setup --channel` Step 5 / `/discover-competitors`",
    ),
    "viewing-scene": (
        "`/setup --channel` Step 7（`.claude/skills/setup/references/persona-branding-readiness.md`）→ ",
        "新規チャンネルは `/setup --channel` Step 4",
        "`/setup --channel` Step 5 または Step 7",
        "`/setup --channel` Step 5 または Step 7",
    ),
}
SETUP_ASSET_OWNERS = {
    "audience-persona-design": "persona-branding-readiness.md",
    "benchmark": "ttp-seed-and-duration.md",
    "discover-competitors": "persona-branding-readiness.md",
    "market-research": "new-channel-bootstrap.md",
    "viewer-voice": "persona-branding-readiness.md",
    "viewing-scene": "persona-branding-readiness.md",
}
UNCHANGED_SKILL_SHA256 = {
    "thumbnail-research": "4f1052032ca41873e9642e8a25824a5c64e9330c15df77e90d0046e0dbc12f94",
    "video-analyze": "b1049a71ace16481363318d89886c14ef49401fd0d77691e73b36ab167bdeb96",
}
RESIDUAL_LINE_MARKERS = {
    "benchmark": ("description:", "- `後工程`:"),
    "discover-competitors": (
        "description:",
        "- 実行場所がチャンネルリポジトリ",
        "- 方向性決定・config 生成",
        "- `/channel-new` 分析モード:",
    ),
    "market-research": (
        "description:",
        "| `/channel-new` 分析モード |",
        "- `/channel-new` 分析モード —",
    ),
}
RESIDUAL_SHA256 = {
    "benchmark": "2fb95bb4e810ba0ca2bf7ece521a8aac529fb461c7d970540ea32ede584f9b03",
    "discover-competitors": "c44dfd9e96135f2886f05c7853b1c4ec3db0d20e8326f93b2d147abf2ac3fdcc",
    "market-research": "a6350cc0f44adf9895aefb0b98fc177415b5bebb55e17b3fb056d3df8d111448",
}


def _skill_text(skill: str) -> str:
    return (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")


def _route_violations(skill: str, text: str) -> set[str]:
    violations = set()
    if text.count("/channel-new") != EXPECTED_CHANNEL_NEW_OCCURRENCES[skill]:
        violations.add("channel-new occurrence ledger")
    if text.count("/setup --channel") != EXPECTED_SETUP_OCCURRENCES[skill]:
        violations.add("setup occurrence ledger")
    for marker in OPENING_ROUTE_MARKERS.get(skill, ()):
        if marker not in text:
            violations.add(f"opening route:{marker}")
    asset = SETUP_ASSET_OWNERS.get(skill)
    if asset is not None and f".claude/skills/setup/references/{asset}" not in text:
        violations.add(f"setup asset:{asset}")
    return violations


def test_all_eight_skills_match_the_context_classified_occurrence_ledger() -> None:
    assert set(EXPECTED_CHANNEL_NEW_OCCURRENCES) == set(TARGET_SKILLS)
    assert set(EXPECTED_SETUP_OCCURRENCES) == set(TARGET_SKILLS)
    assert sum(EXPECTED_CHANNEL_NEW_OCCURRENCES.values()) == 18

    for skill in TARGET_SKILLS:
        assert _route_violations(skill, _skill_text(skill)) == set()


def test_opening_route_validator_detects_wrong_redirect_and_residual_overwrite() -> None:
    audience = _skill_text("audience-persona-design")
    wrong_redirect = audience.replace("`/setup --channel` Step 7", "`/channel-new` Step 7", 1)
    assert _route_violations("audience-persona-design", wrong_redirect) >= {
        "channel-new occurrence ledger",
        "setup occurrence ledger",
    }

    discover = _skill_text("discover-competitors")
    residual_overwrite = discover.replace("/channel-new 分析モード", "/setup --channel", 1)
    assert _route_violations("discover-competitors", residual_overwrite) >= {
        "channel-new occurrence ledger",
        "setup occurrence ledger",
    }


def test_skills_without_opening_occurrences_remain_byte_identical() -> None:
    for skill, expected in UNCHANGED_SKILL_SHA256.items():
        payload = (SKILLS_DIR / skill / "SKILL.md").read_bytes()
        assert sha256(payload).hexdigest() == expected


def test_analysis_and_direction_residual_routes_remain_byte_identical() -> None:
    for skill, markers in RESIDUAL_LINE_MARKERS.items():
        lines = (SKILLS_DIR / skill / "SKILL.md").read_bytes().splitlines(keepends=True)
        selected = [next(line for line in lines if line.decode().startswith(marker)) for marker in markers]
        payload = b"".join(selected)
        assert sha256(payload).hexdigest() == RESIDUAL_SHA256[skill]
