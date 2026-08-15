"""Exact residual `/channel-new` contracts preserved by issue #3982."""

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

SHARED_ASSET_SHA256 = {
    "analysis-mode.md": "3c71c613e009766268f6eb2d7aaed23921009313756889f077f0e88352acf518",
    "benchmark_collector.py": "82a83d1c23cb128f312732fbb928bdacbec8a3006ce6766ae278233a86ed3b45",
    "claude-md-template.md": "c63c2e6411b4103183a9d228ef36265ca098574468f2a28f7fce039b32d138fe",
    "config-generation-rules.md": "70b73064efa6b6c9c9f9287b2aecb843c7f6f60d439c815d062d1c2741dd90cf",
    "config-template/analytics.json": "4344ad8d4c9a1c81958b721eb3d999172f14f71f17d863a1708492ce687b68d2",
    "config-template/audio.json": "c55033dc448cb91fe3cdb47e20f220c5879c05f95855d918a8e72297a5f20a43",
    "config-template/content.json": "5a60fc3327bb2cca1daa5da3744dc218495f3f0f304aebdad41fd2ba32d1bed0",
    "config-template/meta.json": "324194e12d576604b3751af469bd7e965efb28db088b4671d76bb80b499d9da4",
    "config-template/skills/suno.yaml": "2500c62eb81531b722d4ddabddc223c8e4ec9bb9441637b1d5cc2df435145765",
    "config-template/skills/thumbnail.yaml": "77a05753fa35fec9192f01d8f7166774f99c56c25ef057465958d4c29d649533",
    "config-template/youtube.json": "849f4b0912cb7be3d1cc92b7607d355e856b5af3e9e85db0449fabdf1713bb6c",
    "desire-vocabulary.md": "b166b310ccac37333070cd548d66857582d3551bc942c4618363713111c8ccb8",
    "direction-mode.md": "ad1561abb048a24319cdfc404d0939d7e05a6511223034a0814d3d38c88797ef",
    "directory-structure.md": "1ed088ad46926a03dde0929775027b5b8571951cf9f9e994ab68d881bb672046",
    "fetch_benchmark_comments.py": "d69ee100c7f3655394a6fb50b0aa9c4a1ae8b8b733d8243c0600ec9acfc2b93e",
    "fetch_branding_snapshot.py": "9735fa8d2af47b932c2c5318d0f4a4efa2bfdbd95e2bb33dece0752994bf7fef",
    "generate_image.py": "537257487c8cf1b5828ddeae85ff329326d4961b6ce90bd7d1f8a16c8fa684c6",
    "import-mode.md": "3a3703654189f9e5cc42e9441297752c581d87185b32c6af407fd5e3ac0f0bd2",
    "localizations-template.json": "d0267074151af61f27856d0e67e8f0c3d56cf327b2255e00a8035e2851cde558",
    "regeneration-mode.md": "a6cc2edf61dabc16eec5b2a840efc9f3cc81e99415ee7b047ae06a09f68d17bc",
    "save-push-troubleshooting.md": "89a7cab34a96ddf7f10636293621c8b39e6cdf9f17e033a0469d5b14c0fc9a45",
    "schedule-template.json": "2e950062bef269cea670d219024528e06079697997f9c59f244cebdf6a6f3026",
    "verification.md": "9d1a2ffe02a4dfd7e229adc005054c550fb9a2dc3c5a1466a2db8ce3a0d6871f",
}
SETTINGS_PUSH_SHA256 = "86d216c837df6939f8c88676605112f473c268ebc41808d43539d9876ef0fedf"


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


def test_residual_mode_order_is_exact() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    expected = [
        "1. **既存チャンネル取り込みモード**（取り込み Step 1〜8）",
        "2. **方向性検討モード**（Step D1〜D5）",
        "3. **再生成モード**（Step R1〜R8）",
        "4. **設定 push モード**",
        "5. **分析モード**（Step 0〜7）",
    ]

    assert [line for line in skill.splitlines() if re.match(r"^[1-5]\. \*\*", line)] == expected


def test_analysis_direction_import_and_regeneration_step_order_is_exact() -> None:
    analysis = (REFERENCES / "analysis-mode.md").read_text(encoding="utf-8")
    direction = (REFERENCES / "direction-mode.md").read_text(encoding="utf-8")
    imported = (REFERENCES / "import-mode.md").read_text(encoding="utf-8")
    regeneration = (REFERENCES / "regeneration-mode.md").read_text(encoding="utf-8")

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


def test_shared_asset_inventory_detects_removal_content_change_and_symlink_retarget(tmp_path: Path) -> None:
    candidate = tmp_path / "references"
    shutil.copytree(REFERENCES, candidate, symlinks=True)
    (candidate / "verification.md").unlink()
    (candidate / "fetch_branding_snapshot.py").write_bytes(
        (candidate / "fetch_branding_snapshot.py").read_bytes() + b"\n# mutation\n"
    )
    symlink = candidate / "benchmark_collector.py"
    symlink.unlink()
    symlink.symlink_to("../../../../src/youtube_automation/commands/analytics/wrong.py")

    assert _shared_asset_violations(candidate) == {
        "missing:verification.md",
        "changed:fetch_branding_snapshot.py",
        "changed:benchmark_collector.py",
    }


def test_settings_push_contract_is_byte_exact_and_requires_review_before_apply() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    settings_mode = skill.split("## 設定 push モード", 1)[1].split("## 障害時ガイダンス", 1)[0]

    assert sha256(settings_mode.encode()).hexdigest() == SETTINGS_PUSH_SHA256
    diff = settings_mode.index("uv run yt-channel-settings diff")
    push_dry_run = settings_mode.index("uv run yt-channel-settings push", diff)
    approval = settings_mode.index("ユーザー承認", push_dry_run)
    push_apply = settings_mode.index("uv run yt-channel-settings push --apply", approval)
    pull_dry_run = settings_mode.index("uv run yt-channel-settings pull", push_apply)
    pull_apply = settings_mode.index("uv run yt-channel-settings pull --apply", pull_dry_run)
    post_pull_diff = settings_mode.index("`--apply` 後は `git diff` で確認する", pull_apply)

    assert diff < push_dry_run < approval < push_apply < pull_dry_run < pull_apply < post_pull_diff
