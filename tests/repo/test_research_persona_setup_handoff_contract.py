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
        "audience-persona-design",
        (("prelaunch-entry", "new-opening"), ("missing-config-new", "new-opening"), ("missing-input", "new-opening")),
        (("missing-config-existing", "existing-import"),),
    ),
    *_occurrences(
        "benchmark",
        (("missing-config-new", "new-opening"), ("missing-benchmarks", "new-opening")),
        (
            ("frontmatter-analysis", "analysis"),
            ("downstream-analysis", "analysis"),
            ("missing-config-existing", "existing-import"),
        ),
    ),
    *_occurrences(
        "discover-competitors",
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
        "market-research",
        (("setup-cross-reference", "new-opening"),),
        (
            ("frontmatter-analysis", "analysis"),
            ("analysis-table", "analysis"),
            ("analysis-cross-reference", "analysis"),
        ),
    ),
    *_occurrences(
        "thumbnail-research",
        (),
        (
            ("frontmatter-analysis", "analysis"),
            ("desire-vocabulary", "shared-reference"),
            ("analysis-cross-reference", "analysis"),
        ),
    ),
    *_occurrences("video-analyze", (), (("direction-caller", "direction"),)),
    *_occurrences(
        "viewer-voice",
        (
            ("frontmatter-prelaunch", "new-opening"),
            ("prelaunch-entry", "new-opening"),
            ("missing-config-new", "new-opening"),
            ("missing-benchmarks", "new-opening"),
        ),
        (("missing-config-existing", "existing-import"),),
    ),
    *_occurrences(
        "viewing-scene",
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
    "audience-persona-design": "07abb23816cc3c7de0497ab7b4906d756c48009c416eae84afd755ae11ac1d3c",
    "benchmark": "477ff4325d535455a107b86cd091d539e119267dc63f800525527a2f38baf1ca",
    "discover-competitors": "5674e18a4fb70b2eef85cbc72e64b35000666230ee71e6ec957f1e306ba08edb",
    "market-research": "b54b28a9d6cddd9d91e49002b787b38a7b5381546a6fa643532d34aef451bfef",
    "thumbnail-research": "ea3a96bf784d4d510491d9c2ac5f516dfaa6984f0e6acfbc0754c8b753662609",
    "video-analyze": "f28ee9c9b0a18c3ecae15b631f970d780b18bda72185a25935b56f0a66ba6552",
    "viewer-voice": "d805ae103e78d460505834402d19333151c2a7a5b09e87ac394bceabe8436373",
    "viewing-scene": "c11dca52ed69e846b14fc51bcd46859a6bb4ac937844cc9f472ad8c81ddde393",
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
    "thumbnail-research": "424dd55ca34e5d991034ccbc45ee565c2ae35669ba5a22c38821b7e75a74a0da",
    "video-analyze": "36b7a7566c529682bc3ca34c5aaf72c7569aea79bb396d3a5562d45dfb76498f",
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
    "discover-competitors": "91325074ff74f89681a6972f3c56c5c093dfd4aa779f0ca4425e66d348a3a891",
    "market-research": "a6350cc0f44adf9895aefb0b98fc177415b5bebb55e17b3fb056d3df8d111448",
}


def _skill_text(skill: str) -> str:
    return (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")


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
        has_route = "/channel-new" in line or "/setup --channel" in line
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
    asset = SETUP_ASSET_OWNERS.get(skill)
    if asset is not None and f".claude/skills/setup/references/{asset}" not in text:
        violations.add(f"setup asset:{asset}")
    return violations


def test_all_eight_skills_match_the_context_classified_occurrence_ledger() -> None:
    assert {entry[0] for entry in OCCURRENCE_LEDGER} == set(TARGET_SKILLS)
    assert len(OCCURRENCE_LEDGER) == 35
    assert sum(entry[3] == "redirected" for entry in OCCURRENCE_LEDGER) == 17
    assert sum(entry[3] == "residual" for entry in OCCURRENCE_LEDGER) == 18

    for skill in TARGET_SKILLS:
        assert _route_violations(skill, _skill_text(skill)) == set()


def test_opening_route_validator_detects_wrong_redirect_and_residual_overwrite() -> None:
    audience = _skill_text("audience-persona-design")
    wrong_redirect = audience.replace("`/setup --channel` Step 7", "`/channel-new` Step 7", 1)
    assert "active route context ledger" in _route_violations("audience-persona-design", wrong_redirect)

    discover = _skill_text("discover-competitors")
    residual_overwrite = discover.replace("/channel-new 分析モード", "/setup --channel", 1)
    assert "active route context ledger" in _route_violations("discover-competitors", residual_overwrite)


def test_route_validator_rejects_inactive_mixed_swapped_and_relocated_routes() -> None:
    audience = _skill_text("audience-persona-design")
    canonical = next(line for line in audience.splitlines() if "新規チャンネルは `/setup --channel` Step 4" in line)
    inactive_mixed = audience.replace(
        canonical,
        "~~新規チャンネルは /setup --channel Step 4~~ 新規チャンネルは /channel-new Step 4、既存チャンネルは /setup",
    )
    assert _route_violations("audience-persona-design", inactive_mixed) >= {
        "active route context ledger",
        "inactive Markdown route",
    }

    swapped = audience.replace(
        "新規チャンネルは `/setup --channel` Step 4、既存チャンネルは `/channel-new`",
        "新規チャンネルは `/channel-new` Step 4、既存チャンネルは `/setup --channel`",
    )
    assert "active route context ledger" in _route_violations("audience-persona-design", swapped)

    relocated = audience.replace(canonical + "\n", "").replace(
        "## 障害時ガイダンス", f"## 障害時ガイダンス\n\n{canonical}"
    )
    assert "active route context ledger" in _route_violations("audience-persona-design", relocated)

    commented = audience.replace(canonical, f"<!-- {canonical} -->\n新規チャンネルは `/channel-new` Step 4")
    assert _route_violations("audience-persona-design", commented) >= {
        "active route context ledger",
        "inactive Markdown route",
    }

    multiline_comment = audience.replace(canonical, f"<!--\n{canonical}\n-->")
    assert _route_violations("audience-persona-design", multiline_comment) >= {
        "active route context ledger",
        "inactive Markdown route",
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
