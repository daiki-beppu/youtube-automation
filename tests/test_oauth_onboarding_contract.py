"""OAuth onboarding text contract tests."""

from __future__ import annotations

from pathlib import Path

from tests.helpers.paths import REPO_ROOT

REPO_ROOT = REPO_ROOT
SETUP_SKILL = REPO_ROOT / ".claude" / "skills" / "setup" / "SKILL.md"
REGENERATION_MODE_MD = REPO_ROOT / ".claude" / "skills" / "setup" / "references" / "regeneration-mode.md"


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
    ):
        assert "Google Auth Platform" in text
        assert "Audience" in text
        assert "Clients" in text
        assert "client_secrets.json" in text
        for phrase in stale_phrases:
            assert phrase not in text


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


def test_client_secrets_resolution_order_matches_oauth_setup(tmp_path: Path, monkeypatch) -> None:
    """docs の解決順が実装の候補列と一致する。"""
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
