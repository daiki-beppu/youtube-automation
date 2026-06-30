"""OAuth onboarding text contract tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GOOGLE_AUTH_PLATFORM_KEYWORDS = (
    "Google Auth Platform",
    "Test users",
    "403 access_denied",
    "Clients",
    "Create client",
    "Desktop app",
    "Add secret",
    "auth/client_secrets_template.json",
)

CHANNEL_SETUP_OAUTH_ENTRYPOINTS = (
    ".claude/skills/channel-setup/references/gcp-bootstrap.sh",
    ".claude/skills/channel-setup/references/gcp-terraform-apply.sh",
    ".claude/skills/channel-setup/references/gcp-bootstrap.md",
)


def test_channel_setup_oauth_entrypoints_follow_google_auth_platform_contract() -> None:
    for relative_path in CHANNEL_SETUP_OAUTH_ENTRYPOINTS:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

        for expected in GOOGLE_AUTH_PLATFORM_KEYWORDS:
            assert expected in text, f"{relative_path} is missing {expected!r}"
        assert "認証情報を作成」→「OAuth クライアント ID" not in text
