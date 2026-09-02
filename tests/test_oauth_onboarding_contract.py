"""OAuth onboarding text contract tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

REPO_ROOT = REPO_ROOT
SETUP_SKILL = REPO_ROOT / ".claude" / "skills" / "setup" / "SKILL.md"
GCP_BOOTSTRAP_MD = REPO_ROOT / ".claude" / "skills" / "setup" / "references" / "gcp-bootstrap.md"
REGENERATION_MODE_MD = REPO_ROOT / ".claude" / "skills" / "setup" / "references" / "regeneration-mode.md"

GOOGLE_AUTH_PLATFORM_KEYWORDS = (
    "Google Auth Platform",
    "Test users",
    "403 access_denied",
    "Clients",
    "Create client",
    "Desktop app",
    "Add secret",
    "Download JSON",
    "uv run yt-doctor --fix-client-secrets",
    "uv run yt-doctor --json",
)


def _assert_oauth_guidance_contract(text: str, context: str) -> None:
    for expected in GOOGLE_AUTH_PLATFORM_KEYWORDS:
        assert expected in text, f"{context} is missing {expected!r}"
    assert "認証情報を作成」→「OAuth クライアント ID" not in text
    assert "OAuth 同意画面のアプリ名" not in text
    assert "この 1 クリックだけ手動" not in text
    assert "OAuth クライアント ID 作成の 1 ステップだけ" not in text
    assert "作成直後" not in text
    assert "JSON をダウンロード" not in text


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
    script = REPO_ROOT / ".claude/skills/setup/references/gcp-bootstrap.sh"
    env_path = tmp_path / ".env"

    result = subprocess.run(
        ["bash", str(script), "--dry-run", "--skip-adc", "test-proj"],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    _assert_oauth_guidance_contract(result.stdout, "gcp-bootstrap.sh stdout")
    assert "Google Auth Platform の手動設定" in result.stdout
    assert not env_path.exists()


def test_gcp_terraform_apply_stdout_follows_google_auth_platform_contract(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    tf_dir = tmp_path / "tf"
    bin_dir.mkdir()
    tf_dir.mkdir()
    _write_executable(
        bin_dir / "terraform",
        """#!/usr/bin/env bash
case "$*" in
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
        bin_dir / "gcloud",
        """#!/usr/bin/env bash
exit 0
""",
    )
    env = os.environ | {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    script = REPO_ROOT / ".claude/skills/setup/references/gcp-terraform-apply.sh"
    env_path = tmp_path / ".env"

    result = subprocess.run(
        ["bash", str(script), "--tf-dir", str(tf_dir), "--auto-approve"],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    _assert_oauth_guidance_contract(result.stdout, "gcp-terraform-apply.sh stdout")
    assert "Google Auth Platform の手動設定" in result.stdout
    assert not env_path.exists()


def test_setup_entrypoints_do_not_keep_stale_oauth_contract() -> None:
    stale_phrases = (
        "OAuth クライアント ID 作成まで",
        "OAuth クライアント ID の手動配置",
        "OAuth クライアント ID 作成の 1 ステップだけ",
        "作成直後",
        "JSON をダウンロード",
    )
    # setup は OAuth 案内を含む再生成モード（Step R6）が references へ切り出されているため、
    # SKILL.md 本体と regeneration-mode.md を合わせて 1 つの entrypoint として扱う。
    setup_docs = "\n".join(p.read_text(encoding="utf-8") for p in (SETUP_SKILL, REGENERATION_MODE_MD))
    for text in (
        SETUP_SKILL.read_text(encoding="utf-8"),
        setup_docs,
        GCP_BOOTSTRAP_MD.read_text(encoding="utf-8"),
    ):
        assert "Google Auth Platform" in text
        assert "Audience" in text
        assert "Clients" in text
        assert "client_secrets.json" in text
        for phrase in stale_phrases:
            assert phrase not in text


def _make_workspace_channel_worktree(tmp_path: Path) -> Path:
    """workspace channel かつ linked worktree の channel_dir を作る。

    workspace root fallback と main worktree fallback の両方が候補に載る唯一の構造で、
    `client_secrets_file_candidates()` の全 4 候補を一度に観測できる。
    """
    main_root = tmp_path / "main"
    gitdir = main_root / ".git" / "worktrees" / "alpha"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    channel = tmp_path / "workspace" / "channels" / "alpha"
    (channel / "config" / "channel").mkdir(parents=True)
    (channel / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return channel


def test_client_secrets_resolution_order_matches_oauth_setup(tmp_path: Path, monkeypatch) -> None:
    """docs の解決順が実装の候補列と一致する。"""
    from youtube_automation.infrastructure.auth.youtube import client_secrets_file_candidates

    monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
    channel = _make_workspace_channel_worktree(tmp_path)
    workspace_root = channel.parents[1]
    main_root = tmp_path / "main"

    candidates = client_secrets_file_candidates(channel)
    assert candidates == [
        channel / "auth" / "client_secrets.json",
        channel / "automation" / "auth" / "client_secrets.json",
        workspace_root / "auth" / "client_secrets.json",
        main_root.resolve() / "auth" / "client_secrets.json",
    ]

    # 候補ごとに文書側の表記を固定する。候補の追加・削除・並べ替えはこの対応表の更新を強制する
    documented_tokens = (
        "<channel_dir>/auth/",
        "<channel_dir>/automation/auth/",
        "<workspace_root>/auth/",
        "<main_worktree_root>/auth/",
    )
    assert len(documented_tokens) == len(candidates)

    oauth_setup = (REPO_ROOT / "docs" / "oauth-setup.md").read_text(encoding="utf-8")
    resolution_section = oauth_setup.split("`client_secrets.json` の解決順", 1)[1].split("## 動作確認", 1)[0]
    positions = []
    for token in documented_tokens:
        assert token in resolution_section, f"docs/oauth-setup.md is missing {token!r}"
        positions.append(resolution_section.index(token))
    assert positions == sorted(positions), "docs/oauth-setup.md lists the candidates out of implementation order"
