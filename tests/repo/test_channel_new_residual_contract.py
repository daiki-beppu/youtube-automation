"""Residual `/channel-new` mode contracts preserved by issue #3983."""

from tests.helpers.paths import REPO_ROOT

SKILL_MD = REPO_ROOT / ".claude" / "skills" / "channel-new" / "SKILL.md"


def test_settings_push_requires_review_and_approval_before_apply() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    settings_mode = skill.index("## 設定 push モード")

    diff = skill.index("uv run yt-channel-settings diff", settings_mode)
    dry_run = skill.index("uv run yt-channel-settings push", diff)
    approval = skill.index("ユーザー承認", dry_run)
    apply = skill.index("uv run yt-channel-settings push --apply", approval)

    assert settings_mode < diff < dry_run < approval < apply
