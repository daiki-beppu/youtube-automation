"""OAuth onboarding credential resolution contracts."""

from __future__ import annotations

from pathlib import Path

from tests.helpers.paths import REPO_ROOT


def _make_workspace_channel_worktree(tmp_path: Path) -> Path:
    """workspace channel かつ linked worktree の channel_dir を作る。

    旧 workspace の配下でも候補が増えず、main worktree fallback を含む
    `client_secrets_file_candidates()` の全 3 候補だけが返ることを観測する。
    """
    main_root = tmp_path / "main"
    gitdir = main_root / ".git" / "worktrees" / "alpha"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    channel = tmp_path / "workspace" / "channels" / "alpha"
    (channel / "config" / "channel").mkdir(parents=True)
    (channel / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return channel


def test_client_secrets_resolution_order(tmp_path: Path, monkeypatch) -> None:
    """チャンネル固有候補を共有候補より先に解決する。"""
    from youtube_automation.infrastructure.auth.youtube import client_secrets_file_candidates

    monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
    channel = _make_workspace_channel_worktree(tmp_path)
    main_root = tmp_path / "main"

    candidates = client_secrets_file_candidates(channel)
    assert candidates == [
        channel / "auth" / "client_secrets.json",
        channel / "automation" / "auth" / "client_secrets.json",
        main_root.resolve() / "auth" / "client_secrets.json",
    ]

    # 候補ごとに文書側の表記を固定する。候補の追加・削除・並べ替えはこの対応表の更新を強制する
    documented_tokens = (
        "<channel_dir>/auth/",
        "<channel_dir>/automation/auth/",
        "<main_worktree_root>/auth/",
    )
    assert len(documented_tokens) == len(candidates)

    oauth_setup = (REPO_ROOT / "docs" / "oauth-setup.md").read_text(encoding="utf-8")
    resolution_section = oauth_setup.split("`client_secrets.json` の解決順", 1)[1].split("## 動作確認", 1)[0]
    assert "<workspace_root>/auth/" not in resolution_section
    positions = []
    for token in documented_tokens:
        assert token in resolution_section, f"docs/oauth-setup.md is missing {token!r}"
        positions.append(resolution_section.index(token))
    assert positions == sorted(positions), "docs/oauth-setup.md lists the candidates out of implementation order"


def test_public_gcp_guides_reference_upstream_instead_of_removed_assets() -> None:
    """Public entrypoints must resolve to the upstream owner after asset removal."""
    upstream = REPO_ROOT / "infra/terraform/gcp/README.md"
    for relative, target in (
        ("ONBOARDING.md", "infra/terraform/gcp/README.md"),
        ("docs/oauth-setup.md", "../infra/terraform/gcp/README.md"),
    ):
        guide = REPO_ROOT / relative
        text = guide.read_text(encoding="utf-8")
        assert f"]({target})" in text
        assert (guide.parent / target).resolve() == upstream
        assert upstream.is_file()
        assert "gcp-bootstrap" not in text
        assert "references/terraform-gcp" not in text
