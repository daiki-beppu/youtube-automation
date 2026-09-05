from __future__ import annotations

import json
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
RECEIPT_PATH = ROOT / "docs/architecture/b6-integration-receipt.json"
B3_RECEIPT_PATH = ROOT / "docs/architecture/b3-owner-receipt.json"

EXPECTED_B3_MAPPINGS = {
    (mapping["old_owner"], mapping["exact_new_owner"])
    for mapping in json.loads(B3_RECEIPT_PATH.read_text(encoding="utf-8"))["mappings"]
}

EXPECTED_SKILL_FEEDBACK_OWNER_MAPPINGS = {
    "legacy..claude.skills.feedback.SKILL.md": ".claude/skills/skill-feedback/SKILL.md",
    "legacy..claude.skills.feedback.references.upstream-issue-template.md": (
        ".claude/skills/skill-feedback/references/upstream-issue-template.md"
    ),
}

EXPECTED_GROUP_EVIDENCE = {
    "C-01": "unreferenced after consumer search",
    "C-02": "unreferenced after consumer search",
    "C-03": "unreferenced after consumer search",
    "C-04": "repository-local generated settings",
    "C-05": "helper uses shared formatter contract",
    "C-06": "helper uses shared formatter contract",
    "C-07": "helper uses shared formatter contract",
    "legacy-08": ("setup guide ownership consolidated in docs/oauth-setup.md; ONBOARDING.md links to it"),
    "legacy-09": "completed plans received by plans/README.md",
    "legacy-10": "completed plans received by plans/README.md",
    "legacy-11": "completed plans received by plans/README.md",
    "legacy-12": "completed plans received by plans/README.md",
    "legacy-13": "completed plans received by plans/README.md",
    "legacy-14": "completed plan history received by plans/README.md",
    "legacy-15": "completed spec history received by current docs",
    "legacy-16": "audit findings received by audit summary",
    "legacy-17": "current vocabulary and architectural decisions received by the project glossary in architecture.md",
    "legacy-18": "public comprehensive mode is active",
    "legacy-19": "superseded ADR 0001/0002/0003/0004/0005/0008/0015 records are retained",
    "legacy-20": "completed plan received by plans/README.md",
    "legacy-21": "completed plan received by plans/README.md",
    "legacy-22": "completed plan received by plans/README.md",
    "legacy-23": "completed plan received by plans/README.md",
    "legacy-24": "completed plan received by plans/README.md",
    "legacy-25": "completed plan received by plans/README.md",
    "legacy-26": "canonical auth package resource",
    "legacy-27": "completed workflow execution ledger is received by the B6 receipt",
}

EXPECTED_GROUPS = {
    "C-01": (
        "src/youtube_automation/utils/logging_setup.py",
        "delete",
        "docs/architecture/b6-integration-receipt.json",
    ),
    "C-02": (
        "src/youtube_automation/templates/individual_track.md",
        "delete",
        "docs/architecture/b6-integration-receipt.json",
    ),
    "C-03": (
        "src/youtube_automation/templates/complete_collection.md",
        "delete",
        "docs/architecture/b6-integration-receipt.json",
    ),
    "C-04": (".claude/settings.local.json", "delete", "docs/architecture/b6-integration-receipt.json"),
    "C-05": ("extensions/suno-helper/.prettierrc.json", "delete", "docs/architecture/b6-integration-receipt.json"),
    "C-06": ("extensions/distrokid-helper/.prettierrc.json", "delete", "docs/architecture/b6-integration-receipt.json"),
    "C-07": ("extensions/community-helper/.prettierrc.json", "delete", "docs/architecture/b6-integration-receipt.json"),
    "legacy-08": ("auth/SETUP.md", "delete", "docs/oauth-setup.md"),
    "legacy-09": ("plans/001-* + plans/002-*", "delete", "plans/README.md"),
    "legacy-10": ("plans/003-*", "delete", "plans/README.md"),
    "legacy-11": ("plans/004-*", "delete", "plans/README.md"),
    "legacy-12": ("plans/005-*", "delete", "plans/README.md"),
    "legacy-13": ("plans/006-*", "delete", "plans/README.md"),
    "legacy-14": ("docs/superpowers/plans", "delete", "plans/README.md"),
    "legacy-15": ("docs/superpowers/specs", "merge", "docs/architecture/b6-integration-receipt.json"),
    "legacy-16": (
        "docs/audits/2026-05-18-skills-operational-risk-audit/raw",
        "merge",
        "docs/audits/2026-05-18-skills-operational-risk-audit.md",
    ),
    "legacy-17": ("CONTEXT.md", "merge", "docs/architecture.md"),
    "legacy-18": (
        "src/youtube_automation/domains/analytics/collection/strategic_analytics.py",
        "retain",
        "src/youtube_automation/domains/analytics/collection/strategic_analytics.py",
    ),
    "legacy-19": ("docs/adr", "retain", "docs/adr"),
    "legacy-20": ("plans/007-*", "delete", "plans/README.md"),
    "legacy-21": ("plans/008-*", "delete", "plans/README.md"),
    "legacy-22": ("plans/009-*", "delete", "plans/README.md"),
    "legacy-23": ("plans/010-*", "delete", "plans/README.md"),
    "legacy-24": ("plans/011-*", "delete", "plans/README.md"),
    "legacy-25": ("plans/012-* through plans/024-*", "delete", "plans/README.md"),
    "legacy-26": (
        "src/youtube_automation/infrastructure/resources/auth/client_secrets.template.json",
        "merge",
        "src/youtube_automation/infrastructure/resources/auth/client_secrets.template.json",
    ),
    "legacy-27": (
        ".codex/takt-open-issues-execution-notes.md",
        "merge",
        "docs/architecture/b6-integration-receipt.json",
    ),
}
MERGE_SOURCE_EXISTS = {"legacy-26", "legacy-27"}


def _read_receipt() -> dict[str, object]:
    loaded = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _normalise_sdist_member(name: str) -> str:
    parts = Path(name).parts
    assert len(parts) > 1, f"sdist member has no version root: {name}"
    return Path(*parts[1:]).as_posix()


def test_b6_receipt_accounts_for_every_old_owner_without_duplicates() -> None:
    receipt = _read_receipt()
    mappings = receipt.get("mappings")
    assert isinstance(mappings, list)

    old_owners = [mapping["old_owner"] for mapping in mappings if isinstance(mapping, dict)]

    assert len(old_owners) == 223
    assert len(set(old_owners)) == 223
    assert receipt["counts"]["old_owners"] == len(old_owners)
    assert all(owner for owner in old_owners)

    mapping_pairs = {(mapping["old_owner"], mapping["exact_new_owner"]) for mapping in mappings}
    assert EXPECTED_B3_MAPPINGS <= mapping_pairs


def test_b6_receipt_maps_historical_feedback_owners_to_skill_feedback() -> None:
    mappings = _read_receipt().get("mappings")
    assert isinstance(mappings, list)

    actual = {
        mapping["old_owner"]: mapping["exact_new_owner"]
        for mapping in mappings
        if isinstance(mapping, dict) and mapping.get("old_owner") in EXPECTED_SKILL_FEEDBACK_OWNER_MAPPINGS
    }

    assert actual == EXPECTED_SKILL_FEEDBACK_OWNER_MAPPINGS


@pytest.mark.parametrize(
    ("disposition", "expected_count"),
    (("delete", 20), ("merge", 5), ("retain", 2)),
)
def test_b6_receipt_has_the_planned_provenance_group_counts(disposition: str, expected_count: int) -> None:
    groups = _read_receipt().get("provenance_groups")
    assert isinstance(groups, list)

    matching = [group for group in groups if isinstance(group, dict) and group.get("disposition") == disposition]

    assert len(matching) == expected_count
    assert _read_receipt()["counts"][disposition] == len(matching)
    assert all(group.get("id") and group.get("path") and group.get("evidence") for group in matching)


def test_b6_receipt_has_expected_group_identity_and_plan_coverage() -> None:
    groups = _read_receipt()["provenance_groups"]
    assert isinstance(groups, list)
    by_id = {group["id"]: group for group in groups if isinstance(group, dict)}
    assert set(by_id) == set(EXPECTED_GROUPS)
    for group_id, (path, disposition, received_by) in EXPECTED_GROUPS.items():
        group = by_id[group_id]
        assert group["path"] == path
        assert group["disposition"] == disposition
        assert group["received_by"] == received_by
        assert group["verification"]
        assert group["evidence"] == EXPECTED_GROUP_EVIDENCE[group_id]
        assert (ROOT / received_by).exists()

    covered_plans = {
        path for group in by_id.values() for path in group.get("paths", [group["path"]]) if path.startswith("plans/")
    }
    assert covered_plans == {f"plans/{number:03d}-*" for number in range(1, 25)}


def test_b6_receipt_excludes_active_workflow_run_from_provenance() -> None:
    groups = _read_receipt()["provenance_groups"]
    assert isinstance(groups, list)
    paths = {path for group in groups if isinstance(group, dict) for path in group.get("paths", [group["path"]])}
    assert ".takt/runs/20260727-040740-implement-using-only-the-files-9izdz1" not in paths
    assert ".codex/takt-open-issues-execution-notes.md" in paths


def test_b6_receipt_delete_groups_have_no_remaining_paths() -> None:
    groups = _read_receipt()["provenance_groups"]
    assert isinstance(groups, list)
    for group in groups:
        if not isinstance(group, dict) or group.get("disposition") != "delete":
            continue
        paths = group.get("paths", [group["path"]])
        assert all(not list(ROOT.glob(path)) for path in paths), group["id"]


def test_b6_receipt_merge_and_retain_groups_match_post_cleanup_state() -> None:
    groups = _read_receipt()["provenance_groups"]
    assert isinstance(groups, list)
    for group in groups:
        if not isinstance(group, dict) or group["disposition"] == "delete":
            continue
        source_paths = group.get("paths", [group["path"]])
        source_exists = any(list(ROOT.glob(path)) for path in source_paths)
        if group["disposition"] == "retain":
            assert source_exists, group["id"]
        elif group["id"] in MERGE_SOURCE_EXISTS:
            assert source_exists, group["id"]
        else:
            assert not source_exists, group["id"]
        assert (ROOT / group["received_by"]).exists()


def test_b6_current_cli_contract_uses_yt_entrypoints() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = project["project"]["scripts"]

    assert scripts
    assert all(name.startswith("yt-") for name in scripts)
    assert "tayk" not in scripts


def test_b6_receipt_has_no_unassigned_or_duplicate_provenance_groups() -> None:
    groups = _read_receipt().get("provenance_groups")
    assert isinstance(groups, list)

    ids = [group["id"] for group in groups if isinstance(group, dict)]
    assert len(ids) == 27
    assert len(set(ids)) == 27
    assert all(group.get("disposition") in {"delete", "merge", "retain"} for group in groups)


def test_b6_receipt_retains_all_superseded_adr_records() -> None:
    groups = _read_receipt().get("provenance_groups")
    assert isinstance(groups, list)
    retained_paths = {
        group["path"] for group in groups if isinstance(group, dict) and group.get("disposition") == "retain"
    }
    assert "docs/adr" in retained_paths
    assert all(
        (ROOT / path).exists()
        for path in (
            "docs/adr/0001-ai-first-ts-rewrite.md",
            "docs/adr/0002-service-first-architecture.md",
            "docs/adr/0003-service-boundary-contracts.md",
            "docs/adr/0004-core-feature-registry.md",
            "docs/adr/0005-metadata-pure-layer.md",
            "docs/adr/0008-cutover-merge-strategy.md",
            "docs/adr/0015-development-roadmap.md",
        )
    )


def test_sdist_configuration_uses_an_explicit_only_include_allowlist() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    sdist = project["tool"]["hatch"]["build"]["targets"]["sdist"]

    assert "only-include" in sdist
    assert "include" not in sdist
    assert "exclude" not in sdist


def test_built_sdist_contains_only_approved_members(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(dist)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    sdists = list(dist.glob("*.tar.gz"))
    assert len(sdists) == 1

    with tarfile.open(sdists[0]) as archive:
        members = {_normalise_sdist_member(member.name) for member in archive.getmembers()}

    allowed_exact = {
        "LICENSE",
        "README.md",
        "PKG-INFO",
        ".gitignore",
        "hatch_build.py",
        "pyproject.toml",
        ".claude/CLAUDE.template.md",
        ".claude/settings.template.json",
        "docs/features.md",
        "docs/workflow-cheatsheet.md",
        "ONBOARDING.md",
        "docs/tool-setup.md",
        "docs/oauth-setup.md",
        "docs/oauth-scopes.md",
        "infra/terraform/gcp/README.md",
    }
    allowed_prefixes = ("src/", "tests/", ".claude/skills/")
    assert all(member in allowed_exact or member.startswith(allowed_prefixes) for member in members)
    required_exact = allowed_exact
    required_prefixes = allowed_prefixes
    assert required_exact <= members
    assert all(any(member.startswith(prefix) for member in members) for prefix in required_prefixes)

    # README から辿る OAuth 導線は sdist 内で完結する（auth/SETUP.md 廃止時の欠落を再発させない）
    oauth_entrypoints = {
        "ONBOARDING.md",
        "docs/oauth-setup.md",
        "docs/oauth-scopes.md",
        "infra/terraform/gcp/README.md",
    }
    assert oauth_entrypoints <= members
    setup_gcp_assets = {
        ".claude/skills/setup/references/gcp-bootstrap.md",
        ".claude/skills/setup/references/gcp-bootstrap.sh",
    }
    assert setup_gcp_assets <= members
    forbidden_prefixes = (
        ".github/",
        ".takt/",
        "auth/",
        "bench/",
        "extensions/",
        "flake.nix",
        "infra/",
        "plans/",
        "site/",
    )
    # allowlist へ明示した member（例: ルート B の infra README）だけが forbidden prefix の例外になる
    assert not [member for member in members if member.startswith(forbidden_prefixes) and member not in allowed_exact]
    forbidden_names = {
        "client_secrets.json",
        "token.json",
        "token.pickle",
        "credentials.json",
        "client_secret.json",
    }
    basenames = {Path(member).name for member in members}
    assert not basenames & forbidden_names
    assert not any(name.startswith("token") and name.endswith(".json") for name in basenames)


def test_root_auth_and_provenance_confirmed_legacy_files_are_removed() -> None:
    root_auth = ROOT / "auth"
    if root_auth.exists():
        assert not list(root_auth.glob("**/*"))

    removed_paths = (
        ROOT / "src/youtube_automation/utils/logging_setup.py",
        ROOT / "src/youtube_automation/templates/individual_track.md",
        ROOT / "src/youtube_automation/templates/complete_collection.md",
        ROOT / ".claude/settings.local.json",
        ROOT / "extensions/suno-helper/.prettierrc.json",
        ROOT / "extensions/distrokid-helper/.prettierrc.json",
        ROOT / "extensions/community-helper/.prettierrc.json",
    )
    assert all(not path.exists() for path in removed_paths)


def test_integrated_history_assets_are_absent_after_receipt_handoff() -> None:
    removed_history = (
        ROOT / "plans/001-serve-distrokid-post-hardening.md",
        ROOT / "plans/002-distrokid-helper-dep-unification.md",
        ROOT / "plans/003-distrokid-helper-lint-format-ci.md",
        ROOT / "plans/004-server-url-constant-consolidation.md",
        ROOT / "plans/005-skill-authoring-standard.md",
        ROOT / "docs/superpowers/plans",
        ROOT / "docs/superpowers/specs",
        ROOT / "docs/audits/2026-05-18-skills-operational-risk-audit/raw",
        ROOT / "CONTEXT.md",
    )

    assert all(not any(path.iterdir()) if path.is_dir() else not path.exists() for path in removed_history)
    assert (ROOT / "docs/adr/0001-ai-first-ts-rewrite.md").exists()
