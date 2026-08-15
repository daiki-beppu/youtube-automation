"""Residual `/channel-new` and migrated `/setup` contracts for issue #3746."""

from __future__ import annotations

import os
import re
import shutil
from hashlib import sha256
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "channel-new"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCES = SKILL_DIR / "references"
SETUP_REFERENCES = REPO_ROOT / ".claude" / "skills" / "setup" / "references"

SHARED_ASSET_SHA256 = {
    "claude-md-template.md": "c63c2e6411b4103183a9d228ef36265ca098574468f2a28f7fce039b32d138fe",
    "config-generation-rules.md": "5b336c56a31e4f4d46e44bc1cb6923c8b8af7fd1f41b67d4576f33535ef07e50",
    "config-template/analytics.json": "4344ad8d4c9a1c81958b721eb3d999172f14f71f17d863a1708492ce687b68d2",
    "config-template/audio.json": "c55033dc448cb91fe3cdb47e20f220c5879c05f95855d918a8e72297a5f20a43",
    "config-template/content.json": "5a60fc3327bb2cca1daa5da3744dc218495f3f0f304aebdad41fd2ba32d1bed0",
    "config-template/meta.json": "324194e12d576604b3751af469bd7e965efb28db088b4671d76bb80b499d9da4",
    "config-template/skills/suno.yaml": "2500c62eb81531b722d4ddabddc223c8e4ec9bb9441637b1d5cc2df435145765",
    "config-template/skills/thumbnail.yaml": "3e5b6d35963ab1313bc691d0e7cd9f2ec4f118abf1a66d689d4813511e785231",
    "config-template/youtube.json": "849f4b0912cb7be3d1cc92b7607d355e856b5af3e9e85db0449fabdf1713bb6c",
    "desire-vocabulary.md": "d6a2a6eda7597b9aa66f0b140a42834807374cc80a313c9b8edb8114f3126388",
    "direction-mode.md": "47efcc813fd99ccbf7736a8d122b407c00fd2e2bb1b6bf6056dbc68e439b7e3a",
    "directory-structure.md": "d8590189cf8929b968b4f1169b723cc0ed71e0be06dbd57cc3ed405967bc4e14",
    "fetch_branding_snapshot.py": "9735fa8d2af47b932c2c5318d0f4a4efa2bfdbd95e2bb33dece0752994bf7fef",
    "generate_image.py": "537257487c8cf1b5828ddeae85ff329326d4961b6ce90bd7d1f8a16c8fa684c6",
    "schedule-template.json": "2e950062bef269cea670d219024528e06079697997f9c59f244cebdf6a6f3026",
    "verification.md": "4ce440663e0faf0f1e5916920486f9e62c3ed0a3ab86624c189ebbe19cd5d8f1",
}
MOVED_ASSET_SHA256 = {
    "import-mode.md": "c9e8eb78de548fab2f720964bc2a6b97565e368cbc71be6d014914a74233c9bc",
    "localizations-template.json": "d0267074151af61f27856d0e67e8f0c3d56cf327b2255e00a8035e2851cde558",
    "push-mode.md": "be122ecbe19c803cfe09465f68ab364636f46f92f0ec842fb803566337eb57ee",
    "regeneration-mode.md": "152a4e233862da2abc84cc7fa229c6ac630a2830d4ac7297828f8ab6bef39347",
    "save-push-troubleshooting.md": "89a7cab34a96ddf7f10636293621c8b39e6cdf9f17e033a0469d5b14c0fc9a45",
}


def _asset_digest(path: Path) -> str:
    payload = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    return sha256(payload).hexdigest()


def _shared_asset_violations(references: Path) -> set[str]:
    actual = {
        path.relative_to(references).as_posix() for path in references.rglob("*") if path.is_file() or path.is_symlink()
    }
    expected = set(SHARED_ASSET_SHA256)
    violations = {f"missing:{relative}" for relative in expected - actual}
    violations.update(f"unexpected:{relative}" for relative in actual - expected)
    for relative in expected & actual:
        if _asset_digest(references / relative) != SHARED_ASSET_SHA256[relative]:
            violations.add(f"changed:{relative}")
    return violations


def _numbered_steps(markdown: str, pattern: str) -> list[str]:
    return re.findall(pattern, markdown, re.MULTILINE)


def test_residual_owner_routes_market_analysis_and_keeps_direction_mode() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    assert "## 方向性検討モード（Step D1〜D5）" in skill
    assert "/channel-research --market" in skill


def test_analysis_direction_import_and_regeneration_step_order_is_exact() -> None:
    analysis = (REPO_ROOT / ".claude" / "skills" / "channel-research" / "references" / "market.md").read_text(
        encoding="utf-8"
    )
    direction = (REFERENCES / "direction-mode.md").read_text(encoding="utf-8")
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


def test_shared_residual_assets_and_mode_contracts_are_byte_exact() -> None:
    assert _shared_asset_violations(REFERENCES) == set()
    for relative, expected in MOVED_ASSET_SHA256.items():
        assert _asset_digest(SETUP_REFERENCES / relative) == expected
        assert not (REFERENCES / relative).exists()


def test_shared_asset_inventory_detects_removal_content_change_and_symlink_retarget(tmp_path: Path) -> None:
    candidate = tmp_path / "references"
    shutil.copytree(REFERENCES, candidate, symlinks=True)
    (candidate / "verification.md").unlink()
    (candidate / "fetch_branding_snapshot.py").write_bytes(
        (candidate / "fetch_branding_snapshot.py").read_bytes() + b"\n# mutation\n"
    )
    symlink = candidate / "generate_image.py"
    symlink.unlink()
    symlink.symlink_to("../../../../src/youtube_automation/commands/analytics/wrong.py")

    assert _shared_asset_violations(candidate) == {
        "missing:verification.md",
        "changed:fetch_branding_snapshot.py",
        "changed:generate_image.py",
    }


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
