"""Research/persona opening handoffs owned by ``/setup --channel``."""

from __future__ import annotations

from hashlib import sha256

from tests.helpers.paths import REPO_ROOT

SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
TARGET_SKILLS = (
    "channel-strategy",
    "channel-research",
    "video-analyze",
)


def _occurrences(
    skill: str,
    redirected: tuple[tuple[str, str], ...],
    residual: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple((skill, occurrence, context, "redirected") for occurrence, context in redirected) + tuple(
        (skill, occurrence, context, "residual") for occurrence, context in residual
    )


# The 35 /channel-new occurrences on main before #3985, classified by execution context.
OCCURRENCE_LEDGER = (
    *_occurrences(
        "channel-strategy",
        (("prelaunch-entry", "new-opening"), ("missing-config-new", "new-opening"), ("missing-input", "new-opening")),
        (("missing-config-existing", "existing-import"),),
    ),
    *_occurrences(
        "channel-research",
        (("upstream-setup", "new-opening"), ("missing-config-new", "new-opening")),
        (
            ("downstream-analysis", "analysis"),
            ("upstream-import", "existing-import"),
            ("missing-config-existing", "existing-import"),
        ),
    ),
    *_occurrences(
        "channel-research",
        (
            ("upstream-setup", "new-opening"),
            ("new-channel-seed", "new-opening"),
            ("setup-cross-reference", "new-opening"),
        ),
        (
            ("frontmatter-analysis", "analysis"),
            ("outside-channel-existing", "existing-import"),
            ("direction-mode", "direction"),
            ("regeneration-mode", "regeneration"),
            ("analysis-cross-reference", "analysis"),
        ),
    ),
    *_occurrences(
        "channel-research",
        (("setup-cross-reference", "new-opening"),),
        (
            ("frontmatter-analysis", "analysis"),
            ("analysis-table", "analysis"),
            ("analysis-cross-reference", "analysis"),
        ),
    ),
    *_occurrences(
        "channel-research",
        (),
        (
            ("frontmatter-analysis", "analysis"),
            ("desire-vocabulary", "shared-reference"),
            ("analysis-cross-reference", "analysis"),
        ),
    ),
    *_occurrences("video-analyze", (), (("direction-caller", "direction"),)),
    *_occurrences(
        "channel-research",
        (
            ("frontmatter-prelaunch", "new-opening"),
            ("prelaunch-entry", "new-opening"),
            ("missing-config-new", "new-opening"),
            ("missing-benchmarks", "new-opening"),
        ),
        (("missing-config-existing", "existing-import"),),
    ),
    *_occurrences(
        "channel-strategy",
        (
            ("prelaunch-entry", "new-opening"),
            ("missing-config-new", "new-opening"),
            ("missing-input", "new-opening"),
            ("missing-input-guidance", "new-opening"),
        ),
        (("missing-config-existing", "existing-import"),),
    ),
)

# SHA-256 of ordered ``section heading + active route line`` records. This binds
# every route to its exact active Markdown context without duplicating long prose.
ROUTE_CONTEXT_SHA256 = {
    "channel-strategy": "6ffe3799d52297a6b98bad83b6871e796c09a3be8beae084f412f66682e13902",
    "channel-research": "626835fe7b37f18bdbf3e233dcc070b533415a4538133ffbb0e02a448fe59b5b",
    "video-analyze": "f28ee9c9b0a18c3ecae15b631f970d780b18bda72185a25935b56f0a66ba6552",
}
SETUP_ASSET_OWNERS = {
    "channel-strategy": ("persona-branding-readiness.md",),
    "channel-research": (
        "ttp-seed-and-duration.md",
        "persona-branding-readiness.md",
        "new-channel-bootstrap.md",
    ),
}
UNCHANGED_SKILL_SHA256 = {
    "video-analyze": "45032757ba0366fa467160d1cde67f8bc28033cc24c1a7b9d8a8cb436af2e666",
}
RESIDUAL_LINE_MARKERS = {
    "channel-research": (
        "description:",
        "- `後工程`:",
        "- 実行場所がチャンネルリポジトリ",
        "- 方向性決定・config 生成",
        "- `/channel-research --market`:",
        "- この branch は **状態を持たない読み取り専用の調査**",
        "- 既定の成果物は会話内レポートだけ。",
    ),
}
RESIDUAL_SHA256 = {
    "channel-research": "7757b2717f72bf8af2f28346f91497c36ff53d5f276fb9d2aeb61d7fe8a1aee5",
}


def _skill_text(skill: str) -> str:
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    if skill == "channel-strategy":
        text += (SKILLS_DIR / skill / "references" / "persona.md").read_text(encoding="utf-8")
        text += (SKILLS_DIR / skill / "references" / "scene.md").read_text(encoding="utf-8")
    if skill == "channel-research":
        text += (SKILLS_DIR / skill / "references" / "discover.md").read_text(encoding="utf-8")
        text += (SKILLS_DIR / skill / "references" / "market.md").read_text(encoding="utf-8")
        text += (SKILLS_DIR / skill / "references" / "voice.md").read_text(encoding="utf-8")
        text += (SKILLS_DIR / skill / "references" / "thumbnail.md").read_text(encoding="utf-8")
    return text


def _active_route_snapshot(text: str) -> tuple[bytes, bool]:
    section = "frontmatter"
    records: list[str] = []
    in_fence = False
    in_html_comment = False
    inactive_route = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        has_route = any(
            route in line for route in ("/channel-new", "/setup --channel", "/setup --import", "/setup --regenerate")
        )
        starts_comment = "<!--" in line
        ends_comment = "-->" in line
        if in_fence or in_html_comment or starts_comment or "~~" in line:
            inactive_route |= has_route
            if in_html_comment and ends_comment:
                in_html_comment = False
            elif starts_comment and not ends_comment:
                in_html_comment = True
            continue
        if line.startswith("##"):
            section = line
        if has_route:
            records.append(f"{section}\0{line}")
    return "\n".join(records).encode(), inactive_route


def _route_violations(skill: str, text: str) -> set[str]:
    violations = set()
    snapshot, inactive_route = _active_route_snapshot(text)
    if sha256(snapshot).hexdigest() != ROUTE_CONTEXT_SHA256[skill]:
        violations.add("active route context ledger")
    if inactive_route:
        violations.add("inactive Markdown route")
    for asset in SETUP_ASSET_OWNERS.get(skill, ()):
        if f".claude/skills/setup/references/{asset}" not in text:
            violations.add(f"setup asset:{asset}")
    return violations


def test_all_three_skills_match_the_context_classified_occurrence_ledger() -> None:
    assert {entry[0] for entry in OCCURRENCE_LEDGER} == set(TARGET_SKILLS)
    assert len(OCCURRENCE_LEDGER) == 35
    assert sum(entry[3] == "redirected" for entry in OCCURRENCE_LEDGER) == 17
    assert sum(entry[3] == "residual" for entry in OCCURRENCE_LEDGER) == 18

    for skill in TARGET_SKILLS:
        assert _route_violations(skill, _skill_text(skill)) == set()


def test_opening_route_validator_detects_wrong_redirect_and_residual_overwrite() -> None:
    strategy = _skill_text("channel-strategy")
    wrong_redirect = strategy.replace("`/setup --channel` Step 7", "`/channel-new` Step 7", 1)
    assert "active route context ledger" in _route_violations("channel-strategy", wrong_redirect)

    research = _skill_text("channel-research")
    residual_overwrite = research.replace("/channel-research --market", "/setup --channel", 1)
    assert "active route context ledger" in _route_violations("channel-research", residual_overwrite)


def test_route_validator_rejects_inactive_mixed_swapped_and_relocated_routes() -> None:
    strategy = _skill_text("channel-strategy")
    canonical = next(line for line in strategy.splitlines() if "新規チャンネルは `/setup --channel` Step 4" in line)
    inactive_mixed = strategy.replace(
        canonical,
        "~~新規チャンネルは /setup --channel Step 4~~ 新規チャンネルは /channel-new Step 4、既存チャンネルは /setup",
    )
    assert _route_violations("channel-strategy", inactive_mixed) >= {
        "active route context ledger",
        "inactive Markdown route",
    }

    swapped = strategy.replace(
        "新規チャンネルは `/setup --channel` Step 4、既存チャンネルは `/setup --import`",
        "新規チャンネルは `/setup --import` Step 4、既存チャンネルは `/setup --channel`",
    )
    assert "active route context ledger" in _route_violations("channel-strategy", swapped)

    relocated = strategy.replace(canonical + "\n", "").replace(
        "## 障害時ガイダンス", f"## 障害時ガイダンス\n\n{canonical}"
    )
    assert "active route context ledger" in _route_violations("channel-strategy", relocated)

    commented = strategy.replace(canonical, f"<!-- {canonical} -->\n新規チャンネルは `/channel-new` Step 4")
    assert _route_violations("channel-strategy", commented) >= {
        "active route context ledger",
        "inactive Markdown route",
    }

    multiline_comment = strategy.replace(canonical, f"<!--\n{canonical}\n-->")
    assert _route_violations("channel-strategy", multiline_comment) >= {
        "active route context ledger",
        "inactive Markdown route",
    }


def test_skills_without_opening_occurrences_remain_byte_identical() -> None:
    for skill, expected in UNCHANGED_SKILL_SHA256.items():
        payload = (SKILLS_DIR / skill / "SKILL.md").read_bytes()
        assert sha256(payload).hexdigest() == expected


def test_analysis_and_direction_residual_routes_remain_byte_identical() -> None:
    for skill, markers in RESIDUAL_LINE_MARKERS.items():
        lines = _skill_text(skill).encode().splitlines(keepends=True)
        selected = [next(line for line in lines if line.decode().startswith(marker)) for marker in markers]
        payload = b"".join(selected)
        assert sha256(payload).hexdigest() == RESIDUAL_SHA256[skill]
