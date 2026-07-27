"""移管後の onboarding と配布文書が dotenv なしの認証経路を使う契約。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (
    "README.md",
    "ONBOARDING.md",
    ".claude/skills/setup/SKILL.md",
    ".claude/skills/lyria/SKILL.md",
    ".claude/skills/short-thumbnail/SKILL.md",
    ".claude/skills/channel-new/references/gcp-bootstrap.md",
    ".claude/skills/channel-new/references/regeneration-mode.md",
    "infra/terraform/gcp/README.md",
)


def test_current_onboarding_docs_are_present_and_old_auth_owner_is_absent() -> None:
    assert all((ROOT / relative_path).is_file() for relative_path in CURRENT_DOCS)
    assert not (ROOT / "auth/SETUP.md").exists()
    assert not (ROOT / "CONTEXT.md").exists()


def test_oauth_setup_has_a_single_onboarding_owner() -> None:
    onboarding = ROOT / "ONBOARDING.md"
    assert onboarding.is_file()
    assert onboarding.read_text(encoding="utf-8").count("### 2.3 OAuth セットアップ") == 1


def test_dotenv_example_is_retired_and_channel_new_does_not_generate_it() -> None:
    assert not (ROOT / ".env.example").exists()
    channel_new = (ROOT / ".claude" / "skills" / "channel-new" / "SKILL.md").read_text(encoding="utf-8")
    generated_section = channel_new.split("生成対象:", 1)[1].split("定期制作", 1)[0]
    assert "- `.env`" not in generated_section
