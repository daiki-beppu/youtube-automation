"""移管後の onboarding と配布文書が dotenv なしの認証経路を使う契約。

`auth/SETUP.md` は `ONBOARDING.md`（推奨経路）と `docs/oauth-setup.md`（手動経路）へ
分割移管された。存在確認だけでは dotenv 復活や ADC 説明の欠落を検出できないため、
移設先を含めて禁止語・必須語の検査を維持する。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (
    "README.md",
    "ONBOARDING.md",
    "docs/oauth-setup.md",
    "docs/oauth-scopes.md",
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


def test_current_onboarding_docs_use_adc_without_dotenv_instructions() -> None:
    for relative_path in CURRENT_DOCS:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "GOOGLE_GENAI_USE_VERTEXAI" not in text, relative_path
        assert "GOOGLE_CLOUD_LOCATION" not in text, relative_path
        assert "load_dotenv" not in text, relative_path
        assert "grep -v '^#' .env" not in text, relative_path
        assert ".env 書き出し" not in text, relative_path


def test_adc_and_secret_resolution_are_documented() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    onboarding = (ROOT / "ONBOARDING.md").read_text(encoding="utf-8")
    oauth_setup = (ROOT / "docs/oauth-setup.md").read_text(encoding="utf-8")

    assert "gcloud auth application-default login" in readme
    assert "application-default set-quota-project" in readme
    assert "GOOGLE_CLOUD_PROJECT" in readme
    assert "1Password" in readme
    assert "gcloud auth application-default login" in onboarding
    assert "auth/client_secrets.json" in oauth_setup
    assert "用途別にアプリが決定" in oauth_setup


def test_oauth_setup_has_a_single_onboarding_owner() -> None:
    onboarding = ROOT / "ONBOARDING.md"
    assert onboarding.is_file()
    assert onboarding.read_text(encoding="utf-8").count("### 2.3 OAuth セットアップ") == 1


def test_dotenv_example_is_retired_and_channel_new_does_not_generate_it() -> None:
    assert not (ROOT / ".env.example").exists()
    channel_new = (ROOT / ".claude" / "skills" / "channel-new" / "SKILL.md").read_text(encoding="utf-8")
    generated_section = channel_new.split("生成対象:", 1)[1].split("定期制作", 1)[0]
    assert "- `.env`" not in generated_section
