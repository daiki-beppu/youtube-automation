"""Issue #1273: onboard から setup への skill rename 契約テスト。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
_SETUP_SKILL = _SKILLS_DIR / "setup" / "SKILL.md"
_CHANNEL_NEW_SKILL = _SKILLS_DIR / "channel-new" / "SKILL.md"
_ONBOARD_DIR = _SKILLS_DIR / "onboard"
_CURRENT_SETUP_DOCS = [
    _REPO_ROOT / "ONBOARDING.md",
    _REPO_ROOT / "auth" / "SETUP.md",
    _REPO_ROOT / "infra" / "terraform" / "gcp" / "README.md",
]


def _frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    end = text.find("\n---", 4)
    assert text.startswith("---\n")
    assert end != -1
    parsed = yaml.safe_load(text[4:end])
    assert isinstance(parsed, dict)
    return parsed


def test_onboard_skill_directory_is_removed() -> None:
    assert not os.path.lexists(_ONBOARD_DIR)


def test_setup_skill_frontmatter_matches_directory_name() -> None:
    frontmatter = _frontmatter(_SETUP_SKILL)
    assert frontmatter["name"] == "setup"


def test_setup_skill_description_mentions_new_and_legacy_commands() -> None:
    description = _frontmatter(_SETUP_SKILL)["description"]
    assert "/setup" in description
    assert "/onboard" in description


def test_setup_skill_uses_uv_run_for_automation_commands() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert "uv run yt-doctor --json" in text
    assert "uv run yt-channel-status" in text

    bare_command_patterns = [
        r"`yt-doctor --json`",
        r"(?m)^yt-channel-status$",
        r"`yt-channel-status`",
        r"(?m)>\s+\d+\.\s+yt-channel-status\b",
    ]
    for pattern in bare_command_patterns:
        assert re.search(pattern, text) is None


def test_setup_skill_follows_skills_synced_next_action_contract() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert '`next_action.kind == "ai-exec"`' in text
    assert '`next_action.kind == "human"`' in text
    assert "next_action.cmd" in text
    assert "next_action.instructions" in text
    assert "uv run yt-skills sync --asset auth-template" in text
    assert "uv run yt-skills sync --asset skills --force --prune --yes" in text
    assert "通常の `--force` sync では削除されない" in text
    assert "`.agents/skills` が `.claude/skills` を指す symlink" in text


def test_setup_skill_suggests_gcp_project_id_from_channel_name() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert "`config/channel/meta.json` の `channel.name`" in text
    assert "`yt-{channel-slug}`" in text
    assert "kebab-case" in text
    assert "6-30 文字" in text
    assert "`--name`): `{チャンネル名} YouTube`" in text
    assert "承認またはカスタム入力" in text


def test_setup_skill_suggests_oauth_app_and_client_names() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert "`gcp_project` と同じルールでチャンネル名を解決" in text
    assert "`{チャンネル名} YouTube Automation`" in text
    assert "`{チャンネル名} Desktop Client`" in text
    assert "Google Auth Platform > Branding のアプリ名: <channel-name> YouTube Automation" in text
    assert "OAuth クライアント ID 名: <channel-name> Desktop Client" in text
    assert "OAuth 同意画面のアプリ名: <channel-name> YouTube Automation" not in text


def test_skills_use_uv_run_for_doctor_json() -> None:
    offenders: list[str] = []
    for skill_md in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        lines = skill_md.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if "yt-doctor --json" in line and "uv run yt-doctor --json" not in line:
                relative_path = skill_md.relative_to(_REPO_ROOT)
                offenders.append(f"{relative_path}:{line_number}: {line.strip()}")

    assert offenders == []


def test_legacy_onboard_reference_is_limited_to_setup_description() -> None:
    offenders: list[str] = []
    for skill_md in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        if "/onboard" in text and skill_md != _SETUP_SKILL:
            offenders.append(str(skill_md.relative_to(_REPO_ROOT)))
    assert offenders == []


def test_current_setup_docs_do_not_route_to_legacy_onboard() -> None:
    offenders: list[str] = []
    for doc in _CURRENT_SETUP_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert "/setup" in text
        if "/onboard" in text:
            offenders.append(str(doc.relative_to(_REPO_ROOT)))

    assert offenders == []


def test_channel_new_setup_gate_does_not_require_doctor_all_green() -> None:
    text = _CHANNEL_NEW_SKILL.read_text(encoding="utf-8")
    assert "summary.next_check_id" not in text
    assert "`channel_config`: `config/channel/ ディレクトリが存在しない (新規チャンネル)`" in text
    assert "`upload_ready`: `config/channel/meta.json が存在しない`" in text
    assert "`upload_ready`: `channel.channel_id が未設定`" in text
    assert "`upload_ready` が `auth/token.json が存在しない`" in text
    assert "`upload 必須 scope 不足`" in text

    required_check_ids = {
        "ffmpeg",
        "ffprobe",
        "uv",
        "uv_project",
        "automation_package",
        "skills_synced",
        "gcloud",
        "gcloud_account",
        "gcp_project",
        "billing_linked",
        "apis_enabled",
        "adc",
        "adc_quota_project",
        "iam_aiplatform_user",
        "env_file",
        "client_secrets",
        "oauth_token",
    }
    for check_id in required_check_ids:
        assert f"`{check_id}`" in text


def test_setup_skill_handles_ttp_wf_new_readiness_next_check() -> None:
    text = _SETUP_SKILL.read_text(encoding="utf-8")
    assert (
        "`data` | `/wf-new` の入力モード判定データ（analytics_report / benchmark_data / ttp_wf_new_readiness）" in text
    )
    assert "#### `ttp_wf_new_readiness` — 承認済み TTP の `/channel-setup` benchmark 反映状態" in text
    assert "/channel-setup benchmark 反映未完了" in text
    assert "`config/skills/thumbnail.yaml::reference_images.default`" in text
    assert "`data/thumbnail_compare/benchmark/`" in text
    assert "uv run yt-doctor --json" in text
