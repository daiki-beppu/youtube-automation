"""OAuth onboarding text contract tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SKILL = REPO_ROOT / ".claude" / "skills" / "setup" / "SKILL.md"
CHANNEL_SETUP_SKILL = REPO_ROOT / ".claude" / "skills" / "channel-setup" / "SKILL.md"
README = REPO_ROOT / "README.md"
ONBOARDING = REPO_ROOT / "ONBOARDING.md"
AUTH_SETUP = REPO_ROOT / "auth" / "SETUP.md"

GOOGLE_AUTH_PLATFORM_KEYWORDS = (
    "Google Auth Platform",
    "Test users",
    "403 access_denied",
    "Clients",
    "Create client",
    "Desktop app",
    "Add secret",
    "auth/client_secrets.template.json",
)


def _assert_oauth_guidance_contract(text: str, context: str) -> None:
    for expected in GOOGLE_AUTH_PLATFORM_KEYWORDS:
        assert expected in text, f"{context} is missing {expected!r}"
    assert "認証情報を作成」→「OAuth クライアント ID" not in text
    assert "OAuth 同意画面のアプリ名" not in text
    assert "この 1 クリックだけ手動" not in text
    assert "OAuth クライアント ID 作成の 1 ステップだけ" not in text


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_gcp_bootstrap_stdout_follows_google_auth_platform_contract(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "gcloud",
        """#!/usr/bin/env bash
case "$*" in
  "--version"*) echo "Google Cloud SDK fake"; exit 0 ;;
  "auth list --filter=status:ACTIVE --format=value(account)"*) echo "user@example.com"; exit 0 ;;
  "projects describe test-proj --format=value(projectId)"*) echo "test-proj"; exit 0 ;;
  "services list --enabled --project=test-proj --format=value(config.name)"*)
    echo youtube.googleapis.com
    echo youtubeanalytics.googleapis.com
    echo aiplatform.googleapis.com
    echo generativelanguage.googleapis.com
    exit 0
    ;;
  "projects get-iam-policy test-proj"*) echo "roles/aiplatform.user"; exit 0 ;;
  *) exit 0 ;;
esac
""",
    )
    env = os.environ | {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    script = REPO_ROOT / ".claude/skills/channel-setup/references/gcp-bootstrap.sh"

    result = subprocess.run(
        ["bash", str(script), "--dry-run", "--skip-adc", "--env-file", str(tmp_path / ".env"), "test-proj"],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    _assert_oauth_guidance_contract(result.stdout, "gcp-bootstrap.sh stdout")
    assert "Google Auth Platform の手動設定" in result.stdout


def test_gcp_terraform_apply_stdout_follows_google_auth_platform_contract(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    tf_dir = tmp_path / "tf"
    bin_dir.mkdir()
    tf_dir.mkdir()
    _write_executable(
        bin_dir / "terraform",
        """#!/usr/bin/env bash
case "$*" in
  "output -json env_vars"*) echo '{"GOOGLE_GENAI_USE_VERTEXAI":"true","GOOGLE_CLOUD_LOCATION":"us-central1"}'; exit 0 ;;
  "output -raw oauth_console_url"*)
    echo "https://console.cloud.google.com/apis/credentials?project=test-proj"
    exit 0
    ;;
  "output -raw project_id"*) echo "test-proj"; exit 0 ;;
  *) exit 0 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "jq",
        """#!/usr/bin/env bash
cat >/dev/null
printf '%s\\t%s\\n' GOOGLE_GENAI_USE_VERTEXAI true GOOGLE_CLOUD_LOCATION us-central1
""",
    )
    _write_executable(
        bin_dir / "gcloud",
        """#!/usr/bin/env bash
exit 0
""",
    )
    env = os.environ | {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    script = REPO_ROOT / ".claude/skills/channel-setup/references/gcp-terraform-apply.sh"

    result = subprocess.run(
        ["bash", str(script), "--tf-dir", str(tf_dir), "--env-file", str(tmp_path / ".env"), "--auto-approve"],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    _assert_oauth_guidance_contract(result.stdout, "gcp-terraform-apply.sh stdout")
    assert "Google Auth Platform の手動設定" in result.stdout


def test_setup_entrypoints_do_not_keep_stale_oauth_contract() -> None:
    stale_phrases = (
        "OAuth クライアント ID 作成まで",
        "OAuth クライアント ID の手動配置",
        "OAuth クライアント ID 作成の 1 ステップだけ",
    )
    for path in (SETUP_SKILL, CHANNEL_SETUP_SKILL):
        text = path.read_text(encoding="utf-8")
        assert "Google Auth Platform" in text
        assert "Audience" in text
        assert "Clients" in text
        assert "client_secrets.json" in text
        for phrase in stale_phrases:
            assert phrase not in text


def test_auth_template_asset_is_documented_as_default_sync_target() -> None:
    for path in (README, ONBOARDING):
        text = path.read_text(encoding="utf-8")
        assert "yt-skills sync" in text
        assert "--asset auth-template" in text
        assert "auth/client_secrets.template.json" in text


def test_client_secrets_fallback_contract_is_documented() -> None:
    for path in (README, AUTH_SETUP):
        text = path.read_text(encoding="utf-8")
        assert "CLIENT_SECRETS_DIR" in text
        assert "<channel_dir>/auth/" in text
        assert "<channel_dir>/automation/auth/" in text
        assert "CLIENT_SECRETS_JSON" in text
        assert "1Password" in text
    assert "secret ファイルを書き出さない" in AUTH_SETUP.read_text(encoding="utf-8")
