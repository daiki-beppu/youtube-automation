"""Current onboarding docs must not prescribe channel-root dotenv setup."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT_DOCS = (
    "README.md",
    "auth/SETUP.md",
    ".claude/skills/setup/SKILL.md",
    ".claude/skills/lyria/SKILL.md",
    ".claude/skills/short-thumbnail/SKILL.md",
    ".claude/skills/channel-new/references/gcp-bootstrap.md",
    ".claude/skills/channel-new/references/regeneration-mode.md",
    "infra/terraform/gcp/README.md",
)


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
    setup = (ROOT / "auth/SETUP.md").read_text(encoding="utf-8")

    assert "gcloud auth application-default login" in readme
    assert "application-default set-quota-project" in readme
    assert "GOOGLE_CLOUD_PROJECT" in readme
    assert "1Password" in readme
    assert "auth/client_secrets.json" in setup
    assert "用途別にアプリが決定" in setup


def test_dotenv_example_is_retired_and_channel_new_does_not_generate_it() -> None:
    assert not (ROOT / ".env.example").exists()
    channel_new = (ROOT / ".claude" / "skills" / "channel-new" / "SKILL.md").read_text(encoding="utf-8")
    generated_section = channel_new.split("生成対象:", 1)[1].split("定期制作", 1)[0]
    assert "- `.env`" not in generated_section
