"""yt-skills CLI の汎化動作テスト。

skill 配布パイプラインを `--asset` フラグ経由で動かすことを検証する。
importlib.resources ベースの wheel 解決ではなく、editable install 相当の
fallback (リポジトリルート直下の `.claude/skills/`) を tmp_path で偽装する。
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import pytest

from youtube_automation.cli import skills_sync
from youtube_automation.cli.skills_sync import (
    _ASSET_SPECS,
    _asset_root,
    _list_entries,
    build_parser,
    bundled_skill_names,
)


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp_path にダミーの skills ツリーを仕込む。

    `_asset_root` が importlib.resources で解決を試みた直後に拾われる editable
    fallback を、`_editable_root()` を monkeypatch で差し替えて tmp_path に向ける。
    """
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "channel-research").mkdir()
    (skills_dir / "channel-research" / "SKILL.md").write_text("# research\n", encoding="utf-8")
    (skills_dir / "channel-direction").mkdir()
    (skills_dir / "channel-direction" / "SKILL.md").write_text("# direction\n", encoding="utf-8")

    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)
    return tmp_path


# ---------- _asset_root ----------


def test_asset_root_skills_falls_back_to_editable(fake_repo: Path) -> None:
    assert _asset_root("skills") == fake_repo / ".claude" / "skills"


def test_asset_root_unknown_asset_raises(fake_repo: Path) -> None:
    with pytest.raises(KeyError):
        _asset_root("nope")


def test_asset_specs_has_skills() -> None:
    assert "skills" in _ASSET_SPECS


def test_asset_root_missing_source_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        _asset_root("skills")


# ---------- _list_entries ----------


def test_list_entries_skills_lists_directories_only(fake_repo: Path) -> None:
    root = _asset_root("skills")
    assert _list_entries(root) == ["channel-direction", "channel-research"]


def test_bundled_skill_names_uses_skills_asset(fake_repo: Path) -> None:
    assert bundled_skill_names() == ["channel-direction", "channel-research"]


# ---------- cmd_list ----------


def test_cmd_list_skills_asset_lists_skill_dirs(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    args = parser.parse_args(["list", "--asset", "skills"])
    rc = args.func(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "channel-research" in out
    assert "channel-direction" in out


def test_cmd_list_default_asset_is_all() -> None:
    """default の `yt-skills list` は `--asset all` 相当で全 asset を一覧する。"""
    parser = build_parser()
    args = parser.parse_args(["list"])
    assert args.asset == "all"


# ---------- cmd_sync ----------


def test_cmd_sync_default_target_resolves_for_skills(fake_repo: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--dry-run"])
    skills_sync._resolve_default_target(args)
    assert args.target == ".claude/skills"
    assert args.asset == "skills"


def test_cmd_sync_default_asset_is_all() -> None:
    """default の `yt-skills sync` は `--asset all` で全 asset を sync する。"""
    parser = build_parser()
    args = parser.parse_args(["sync"])
    assert args.asset == "all"


def test_cmd_sync_default_all_includes_auth_template(
    fake_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (fake_repo / ".claude" / "CLAUDE.template.md").write_text("# policy\n", encoding="utf-8")
    docs = fake_repo / "docs"
    docs.mkdir()
    (docs / "workflow-cheatsheet.md").write_text("# workflow\n", encoding="utf-8")
    (docs / "features.md").write_text("# features\n", encoding="utf-8")
    auth = fake_repo / "auth"
    auth.mkdir()
    (auth / "client_secrets.template.json").write_text('{"installed": {}}\n', encoding="utf-8")
    downstream = tmp_path / "downstream"
    downstream.mkdir()
    monkeypatch.chdir(downstream)

    parser = build_parser()
    args = parser.parse_args(["sync", "--force"])
    rc = args.func(args)

    assert rc == 0
    assert (downstream / ".claude" / "skills" / "channel-research" / "SKILL.md").exists()
    assert (downstream / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") == "# policy\n"
    assert (downstream / "docs" / "workflow-cheatsheet.md").exists()
    assert (downstream / "docs" / "features.md").exists()
    assert (downstream / "auth" / "client_secrets.template.json").exists()


def test_cmd_sync_all_keeps_target_unset_after_resolve() -> None:
    """`--asset all` では target は asset ごとに resolve するため、parse 直後は None のまま。"""
    parser = build_parser()
    args = parser.parse_args(["sync"])
    skills_sync._resolve_default_target(args)
    assert args.target is None


def test_cmd_sync_all_with_target_exits_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    """`--asset all` + `--target` は silent な誤動作を防ぐため error で止める。"""
    parser = build_parser()
    args = parser.parse_args(["sync", "--target", "/tmp/custom-path"])
    with pytest.raises(SystemExit) as exc_info:
        skills_sync._resolve_default_target(args)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--target は --asset all モードでは使えません" in err
    assert "--asset skills --target" in err


def test_cmd_diff_all_with_target_exits_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    """`yt-skills diff --target X` (asset 未指定) も同様に error で止める。"""
    parser = build_parser()
    args = parser.parse_args(["diff", "--target", "/tmp/custom-path"])
    with pytest.raises(SystemExit) as exc_info:
        skills_sync._resolve_default_target(args)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--target は --asset all モードでは使えません" in err


def test_cmd_sync_public_api_with_all_and_target_raises_value_error() -> None:
    """`cmd_sync` 公開 API 直呼びで asset=all + target は `ValueError` を raise する。

    Library 呼び出し元が `SystemExit` で強制終了されないよう、`sys.exit` ではなく
    通常の Python 例外で通知する設計。CLI 経由では `_resolve_default_target` が
    catch して exit 2 に変換する。
    """
    from youtube_automation.cli.skills_sync._sync import cmd_sync

    args = argparse.Namespace(
        asset="all",
        target="/tmp/custom-path",
        symlink=False,
        force=False,
        dry_run=True,
        only=None,
        prune=False,
        yes=False,
    )
    with pytest.raises(ValueError, match="--target は --asset all モードでは使えません"):
        cmd_sync(args)


def test_cmd_diff_public_api_with_all_and_target_raises_value_error() -> None:
    """`cmd_diff` 公開 API 直呼びでも同様に `ValueError` を raise する。"""
    from youtube_automation.cli.skills_sync._diff import cmd_diff

    args = argparse.Namespace(asset="all", target="/tmp/custom-path")
    with pytest.raises(ValueError, match="--target は --asset all モードでは使えません"):
        cmd_diff(args)


def test_guard_target_with_all_is_noop_for_compatible_args() -> None:
    """正当な組み合わせでは `_guard_target_with_all` は何もしない。"""
    # asset=all + target=None
    skills_sync._guard_target_with_all(argparse.Namespace(asset="all", target=None))
    # asset=skills + target=指定
    skills_sync._guard_target_with_all(argparse.Namespace(asset="skills", target="/tmp/x"))
    # asset=skills + target=None
    skills_sync._guard_target_with_all(argparse.Namespace(asset="skills", target=None))


def test_cmd_sync_skills_dry_run_does_not_write(fake_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "downstream" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--dry-run", "--target", str(target)])
    rc = args.func(args)
    assert rc == 0
    assert not (target / "channel-research").exists()


def test_cmd_sync_skills_copies_skill_dirs(fake_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)
    assert rc == 0
    assert (target / "channel-research" / "SKILL.md").read_text(encoding="utf-8") == "# research\n"
    assert (target / "channel-direction" / "SKILL.md").exists()


def test_cmd_sync_warns_on_numbered_duplicates_in_target(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """sync 先に iCloud bounce 形式の重複があると stderr で警告する (#1410)。削除はしない。"""
    target = tmp_path / "out" / ".claude" / "skills"
    # bounce された skill ディレクトリ (bundled entry 名と一致しないため sync は触らない)
    bounced_dir = target / "channel-research 2"
    bounced_dir.mkdir(parents=True)
    (bounced_dir / "SKILL.md").write_text("# research\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)
    assert rc == 0
    err = capsys.readouterr().err
    assert "番号付き重複ファイルを検出" in err
    assert "channel-research 2" in err
    assert "numbered-duplicate-files-cleanup" in err
    assert "https://github.com/daiki-beppu/youtube-automation/blob/main/" in err
    # 検知のみで自動削除はしない
    assert bounced_dir.exists()


def test_cmd_sync_without_force_warns_on_bounced_file_inside_skill(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--force なし (skip) では skill 内の bounce ファイルが残るため警告される。"""
    target = tmp_path / "out" / ".claude" / "skills"
    existing = target / "channel-research"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("# research\n", encoding="utf-8")
    (existing / "SKILL 2.md").write_text("# research\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target)])
    rc = args.func(args)
    assert rc == 0
    err = capsys.readouterr().err
    assert "番号付き重複ファイルを検出" in err
    assert "SKILL 2.md" in err


def test_cmd_sync_force_warns_before_overwriting_bounced_file_inside_skill(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--force で skill dir を削除する前に bounce ファイルを警告する。"""
    target = tmp_path / "out" / ".claude" / "skills"
    existing = target / "channel-research"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("OLD\n", encoding="utf-8")
    bounced_file = existing / "SKILL 2.md"
    bounced_file.write_text("OLD duplicate\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)
    assert rc == 0
    err = capsys.readouterr().err
    assert "番号付き重複ファイルを検出" in err
    assert "SKILL 2.md" in err
    assert not bounced_file.exists()


def test_cmd_sync_resolves_symlink_target(fake_repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "out" / ".claude" / "skills"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)

    assert rc == 0
    assert target.is_symlink()
    assert (outside / "channel-research" / "SKILL.md").read_text(encoding="utf-8") == "# research\n"


def test_cmd_sync_no_duplicate_warning_when_clean(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)
    assert rc == 0
    assert "番号付き重複ファイル" not in capsys.readouterr().err


def test_cmd_sync_force_overwrites_existing_skill(fake_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    target.mkdir(parents=True)
    existing = target / "channel-research"
    existing.mkdir()
    (existing / "SKILL.md").write_text("OLD\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)
    assert rc == 0
    assert (target / "channel-research" / "SKILL.md").read_text(encoding="utf-8") == "# research\n"


def test_cmd_sync_skips_existing_without_force(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    target.mkdir(parents=True)
    existing = target / "channel-research"
    existing.mkdir()
    (existing / "SKILL.md").write_text("OLD\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target)])
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped" in out
    assert (target / "channel-research" / "SKILL.md").read_text(encoding="utf-8") == "OLD\n"


def test_cmd_sync_only_filters_entries(fake_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(
        [
            "sync",
            "--asset",
            "skills",
            "--target",
            str(target),
            "--force",
            "--only",
            "channel-research",
        ]
    )
    rc = args.func(args)
    assert rc == 0
    assert (target / "channel-research").exists()
    assert not (target / "channel-direction").exists()


# ---------- .agents/skills symlink (Codex 探索パス) ----------


def test_cmd_sync_skills_creates_agents_symlink(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 標準レイアウトの target
    target = tmp_path / "out" / ".claude" / "skills"

    # When: skills を sync
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)

    # Then: .claude の隣に .agents/skills が ../.claude/skills を指す symlink として作られる
    assert rc == 0
    link = tmp_path / "out" / ".agents" / "skills"
    assert link.is_symlink()
    assert os.readlink(link) == str(Path("..") / ".claude" / "skills")
    # 相対リンクが実体の skills ディレクトリに解決する
    assert (link / "channel-research" / "SKILL.md").read_text(encoding="utf-8") == "# research\n"


def test_cmd_sync_skills_agents_symlink_in_summary_and_stdout(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "linked: .agents/skills -> ../.claude/skills" in out
    assert "'linked': 1" in out


def test_cmd_sync_skills_agents_symlink_is_idempotent(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()

    # 1 回目: linked
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    assert args.func(args) == 0
    capsys.readouterr()

    link = tmp_path / "out" / ".agents" / "skills"
    before = os.readlink(link)

    # 2 回目 (--force なし): 既存の正しい symlink は skipped で触らない
    args2 = parser.parse_args(["sync", "--asset", "skills", "--target", str(target)])
    assert args2.func(args2) == 0
    out = capsys.readouterr().out

    assert link.is_symlink()
    assert os.readlink(link) == before
    assert "skipped: .agents/skills -> ../.claude/skills" in out


def test_cmd_sync_skills_agents_symlink_dry_run_does_not_write(fake_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--dry-run"])
    rc = args.func(args)

    assert rc == 0
    assert not (tmp_path / "out" / ".agents").exists()


def test_cmd_sync_skills_force_relinks_wrong_agents_symlink(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 既存の .agents/skills が誤った場所を指している
    agents_dir = tmp_path / "out" / ".agents"
    agents_dir.mkdir(parents=True)
    wrong = agents_dir / "skills"
    wrong.symlink_to(tmp_path / "somewhere-else")
    assert os.readlink(wrong) == str(tmp_path / "somewhere-else")

    # When: --force 付きで sync
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)

    # Then: 正しい相対リンクに張り直される
    assert rc == 0
    assert os.readlink(wrong) == str(Path("..") / ".claude" / "skills")


def test_cmd_sync_skills_keeps_wrong_agents_symlink_without_force(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 既存の誤 symlink (--force なし)
    agents_dir = tmp_path / "out" / ".agents"
    agents_dir.mkdir(parents=True)
    wrong = agents_dir / "skills"
    wrong.symlink_to(tmp_path / "somewhere-else")

    # When: --force なしで sync
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target)])
    rc = args.func(args)

    # Then: 既存は冪等に温存される (上書きには --force が必要)
    assert rc == 0
    assert os.readlink(wrong) == str(tmp_path / "somewhere-else")


def test_cmd_sync_skills_non_standard_target_skips_agents(fake_repo: Path, tmp_path: Path) -> None:
    # Given: `.claude/skills` レイアウトでない target
    target = tmp_path / "custom" / "skills"

    # When: skills を sync
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)

    # Then: .agents 規約が成立しないので symlink は作られない
    assert rc == 0
    assert (target / "channel-research").exists()
    assert not (tmp_path / "custom" / ".agents").exists()
    assert not (tmp_path / ".agents").exists()


def test_ensure_agents_skills_symlink_unsupported_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: symlink 非対応環境を模す (symlink_to が OSError)
    from youtube_automation.cli.skills_sync import _ops

    def raise_oserror(self: Path, *a: object, **k: object) -> None:
        raise OSError("symlink not supported")

    monkeypatch.setattr(Path, "symlink_to", raise_oserror)

    target = tmp_path / "out" / ".claude" / "skills"
    target.mkdir(parents=True)

    # When/Then: 例外を握りつぶし 'unsupported' を返す (sync 全体は失敗させない)
    result = _ops._ensure_agents_skills_symlink(target, force=False, dry_run=False)
    assert result == "unsupported"


def test_ensure_agents_skills_symlink_unsupported_warns_but_sync_succeeds(
    fake_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: symlink 非対応環境
    def raise_oserror(self: Path, *a: object, **k: object) -> None:
        raise OSError("symlink not supported")

    monkeypatch.setattr(Path, "symlink_to", raise_oserror)

    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])

    # When: sync (symlink だけ失敗)
    rc = args.func(args)

    # Then: skills 本体は配布され、rc は 0、stderr に警告
    assert rc == 0
    assert (target / "channel-research" / "SKILL.md").exists()
    err = capsys.readouterr().err
    assert ".agents/skills" in err


def test_ensure_agents_skills_symlink_returns_none_for_non_standard_layout(tmp_path: Path) -> None:
    from youtube_automation.cli.skills_sync import _ops

    target = tmp_path / "custom" / "skills"
    target.mkdir(parents=True)
    assert _ops._ensure_agents_skills_symlink(target, force=False, dry_run=False) is None


# ---------- .agents/skills symlink: permission-denied ----------


def test_ensure_agents_skills_symlink_returns_permission_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`PermissionError` は `OSError` と区別して `'permission-denied'` を返す。"""
    from youtube_automation.cli.skills_sync import _ops

    def raise_permission_error(self: Path, *a: object, **k: object) -> None:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "symlink_to", raise_permission_error)

    target = tmp_path / "out" / ".claude" / "skills"
    target.mkdir(parents=True)

    result = _ops._ensure_agents_skills_symlink(target, force=False, dry_run=False)
    assert result == "permission-denied"


def test_ensure_agents_skills_symlink_permission_error_on_parent_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """親 `.agents/` 作成の `PermissionError` も `'permission-denied'` で表面化する。"""
    from youtube_automation.cli.skills_sync import _ops

    original_mkdir = Path.mkdir

    def selective_mkdir(self: Path, *a: object, **k: object) -> None:
        if self.name == ".agents":
            raise PermissionError("Permission denied: cannot create .agents")
        return original_mkdir(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", selective_mkdir)

    target = tmp_path / "out" / ".claude" / "skills"
    # mkdir patch の前に target dir を作っておく (selective_mkdir が .agents だけを reject)
    target.mkdir(parents=True)

    result = _ops._ensure_agents_skills_symlink(target, force=False, dry_run=False)
    assert result == "permission-denied"


def test_cmd_sync_skills_permission_denied_sets_nonzero_rc(
    fake_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """symlink 作成が `PermissionError` で失敗したら sync 全体の rc は非ゼロ。"""

    def raise_permission_error(self: Path, *a: object, **k: object) -> None:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "symlink_to", raise_permission_error)

    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)

    # 終了コードは非ゼロ (silent な握りつぶしを禁じる)
    assert rc != 0


def test_cmd_sync_skills_permission_denied_emits_error_and_recovery_hint(
    fake_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """エラーメッセージに手動復旧手順 (`ln -s ../.claude/skills .agents/skills`) を含む。"""

    def raise_permission_error(self: Path, *a: object, **k: object) -> None:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "symlink_to", raise_permission_error)

    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    args.func(args)

    err = capsys.readouterr().err
    # 明示的なエラーラベル
    assert "[error]" in err
    assert ".agents/skills" in err
    # 手動復旧コマンドの案内
    assert "ln -s ../.claude/skills" in err


def test_cmd_sync_skills_permission_denied_still_distributes_skills(
    fake_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """symlink 失敗時でも skills 本体は配布される (部分成功 + rc!=0)。"""

    def raise_permission_error(self: Path, *a: object, **k: object) -> None:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "symlink_to", raise_permission_error)

    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)

    # rc は非ゼロだが、skills 本体は target に展開済み
    assert rc != 0
    assert (target / "channel-research" / "SKILL.md").exists()
    assert (target / "channel-direction" / "SKILL.md").exists()


def test_cmd_sync_skills_unsupported_keeps_rc_zero(
    fake_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """汎用 `OSError` (symlink 非対応) は今まで通り rc=0 のままにする (退行検出)。"""

    def raise_oserror(self: Path, *a: object, **k: object) -> None:
        raise OSError("symlink not supported")

    monkeypatch.setattr(Path, "symlink_to", raise_oserror)

    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force"])
    rc = args.func(args)

    # symlink 非対応環境は警告のみで rc=0 (PermissionError とは扱いを分ける)
    assert rc == 0


# ---------- cmd_diff ----------


def test_cmd_diff_skills_no_diff(fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    target.mkdir(parents=True)
    src = _asset_root("skills")
    for entry in src.iterdir():
        shutil.copytree(entry, target / entry.name)

    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "skills", "--target", str(target)])
    rc = args.func(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "差分なし" in out


def test_cmd_diff_default_target_resolves_for_skills(fake_repo: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "skills"])
    skills_sync._resolve_default_target(args)
    assert args.asset == "skills"
    assert args.target == ".claude/skills"


def test_cmd_diff_default_asset_is_all() -> None:
    """default の `yt-skills diff` も `--asset all` で全 asset を diff する。"""
    parser = build_parser()
    args = parser.parse_args(["diff"])
    assert args.asset == "all"


def test_cmd_diff_skills_only_disk_emits_prune_hint(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: target に bundled + 既知 orphan 1 件
    target = tmp_path / "out" / ".claude" / "skills"
    target.mkdir(parents=True)
    src = _asset_root("skills")
    for entry in src.iterdir():
        shutil.copytree(entry, target / entry.name)
    (target / "analyze").mkdir()
    (target / "analyze" / "SKILL.md").write_text("# legacy\n", encoding="utf-8")

    # When: diff を実行
    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "skills", "--target", str(target)])
    rc = args.func(args)

    # Then: 既知 orphan のリスト直後に --prune の案内が出る
    assert rc == 0
    out = capsys.readouterr().out
    assert "upstream 管理の既知の旧 skill" in out
    assert "analyze" in out
    assert "--prune" in out
    assert "--yes" in out


def test_cmd_diff_skills_protects_unknown_local_entry_without_prune_hint(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: target に bundled + 未知のローカル entry 1 件
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    custom = target / "suno-preflight"
    custom.mkdir()

    # When: diff を実行
    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "skills", "--target", str(target)])
    rc = args.func(args)

    # Then: ローカル entry として保護され、削除コマンドは案内されない
    assert rc == 0
    out = capsys.readouterr().out
    assert "未知のローカル entry として prune から保護されます" in out
    assert "suno-preflight" in out
    assert "--prune --yes" not in out


def test_cmd_diff_skills_no_orphans_does_not_emit_prune_hint(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: target は bundled と完全一致 (only_disk なし)
    target = tmp_path / "out" / ".claude" / "skills"
    target.mkdir(parents=True)
    src = _asset_root("skills")
    for entry in src.iterdir():
        shutil.copytree(entry, target / entry.name)

    # When: diff を実行
    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "skills", "--target", str(target)])
    rc = args.func(args)

    # Then: 孤児がないので --prune ヒントは出ない
    assert rc == 0
    out = capsys.readouterr().out
    assert "--prune" not in out


def test_cmd_diff_claude_md_does_not_emit_prune_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: claude-md asset の fake_repo と diff 可能な target
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.template.md").write_text("# template\n", encoding="utf-8")
    (claude_dir / "skills").mkdir()
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)

    target_dir = tmp_path / "downstream" / ".claude"
    target_dir.mkdir(parents=True)
    target = target_dir / "CLAUDE.md"
    # 内容を変えて差分を発生させる (only_disk ではなく内容差分)
    target.write_text("# different\n", encoding="utf-8")

    # When: --asset claude-md で diff
    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "claude-md", "--target", str(target)])
    rc = args.func(args)

    # Then: file asset では --prune は無関係なのでヒント文字列が出ない
    assert rc == 0
    out = capsys.readouterr().out
    assert "--prune" not in out


# ---------- cmd_sync --prune ----------


def _seed_bundled_target(target: Path) -> None:
    """target に bundled (fake_repo の同梱スキル) を事前 copy する。"""
    target.mkdir(parents=True, exist_ok=True)
    src = _asset_root("skills")
    for entry in src.iterdir():
        shutil.copytree(entry, target / entry.name)


def test_cmd_sync_prune_removes_orphan_dir_when_yes(fake_repo: Path, tmp_path: Path) -> None:
    # Given: target に bundled + 孤児 analyze/
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()
    (target / "analyze" / "SKILL.md").write_text("# legacy\n", encoding="utf-8")

    # When: --prune --yes で sync
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: 孤児が消える
    assert rc == 0
    assert not (target / "analyze").exists()


@pytest.mark.parametrize(
    "skill_name",
    ["onboard", "distrokid-prep", "channel-import", "channel-setup", "channel-direction"],
)
def test_cmd_sync_prune_removes_known_removed_skill_when_yes(fake_repo: Path, tmp_path: Path, skill_name: str) -> None:
    """upstream で削除された既知 skill は --yes で prune できる。"""
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    source_orphan = fake_repo / ".claude" / "skills" / skill_name
    if source_orphan.exists():
        shutil.rmtree(source_orphan)
    orphan = target / skill_name
    if orphan.exists():
        shutil.rmtree(orphan)
    orphan.mkdir()
    (orphan / "SKILL.md").write_text("# legacy\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    assert rc == 0
    assert not orphan.exists()


def test_cmd_sync_prune_preserves_user_skill(fake_repo: Path, tmp_path: Path) -> None:
    """同梱外の未知 skill はユーザー作成の可能性があるため prune しない。"""
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    custom = target / "suno-preflight"
    custom.mkdir()
    (custom / "SKILL.md").write_text("# local\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    assert rc == 0
    assert (custom / "SKILL.md").read_text(encoding="utf-8") == "# local\n"


def test_cmd_sync_prune_dry_run_distinguishes_known_orphan_and_user_skill(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """dry-run でも既知 orphan のみを削除候補として表示する。"""
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()
    custom = target / "suno-preflight"
    custom.mkdir()

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune"])
    rc = args.func(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "would-prune: analyze" in out
    assert "suno-preflight" not in out
    assert (target / "analyze").exists()
    assert custom.exists()


def test_cmd_sync_prune_keeps_bundled_entries_when_yes(fake_repo: Path, tmp_path: Path) -> None:
    # Given: target に bundled + 孤児
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: bundled (channel-research / channel-direction) は残る
    assert rc == 0
    assert (target / "channel-research" / "SKILL.md").exists()
    assert (target / "channel-direction" / "SKILL.md").exists()


def test_cmd_sync_prune_yes_emits_pruned_label_on_stdout(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: target に孤児 analyze/
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: stdout に pruned: analyze が出る
    assert rc == 0
    out = capsys.readouterr().out
    assert "pruned" in out
    assert "analyze" in out


def test_cmd_sync_prune_yes_summary_counts_include_pruned(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: 孤児 1 件
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: 完了行に 'pruned': 1 が含まれる
    assert rc == 0
    out = capsys.readouterr().out
    assert "完了:" in out
    assert "'pruned': 1" in out


def test_cmd_sync_prune_without_yes_emits_would_prune(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: 孤児 analyze/
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()
    (target / "analyze" / "SKILL.md").write_text("# legacy\n", encoding="utf-8")

    # When: --prune 単体（--yes なし）
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune"])
    rc = args.func(args)

    # Then: 削除されない + stdout に would-prune: analyze
    assert rc == 0
    assert (target / "analyze").exists()
    out = capsys.readouterr().out
    assert "would-prune" in out
    assert "analyze" in out


def test_cmd_sync_prune_without_yes_emits_hint(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: 孤児 analyze/
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()

    # When: --prune 単体
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune"])
    rc = args.func(args)

    # Then: 「実削除には --yes」ヒントが stdout に出る
    assert rc == 0
    out = capsys.readouterr().out
    assert "--yes" in out


def test_build_parser_exposes_prune_and_yes() -> None:
    # Given/When: parse_args に --prune --yes を渡す
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--prune", "--yes"])

    # Then: args 属性で受け取れる
    assert args.prune is True
    assert args.yes is True


def test_build_parser_prune_help_describes_known_upstream_skills_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: yt-skills の CLI parser
    parser = build_parser()

    # When: sync のヘルプを表示する
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["sync", "--help"])

    # Then: 既知の upstream 管理 skill だけが対象で、未知の local skill は保護される
    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "upstream 管理の既知の旧 skill を削除候補として列挙する" in help_text
    assert "未知のローカル skill は対象外" in help_text


def test_build_parser_prune_defaults_false() -> None:
    # Given/When: フラグ省略
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills"])

    # Then: 既存挙動が破壊されないようデフォルトは False
    assert args.prune is False
    assert args.yes is False


def test_cmd_sync_prune_recursively_deletes_nested_files(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 孤児ディレクトリにネストファイル
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    legacy = target / "analyze"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text("# legacy\n", encoding="utf-8")
    nested = legacy / "references"
    nested.mkdir()
    (nested / "note.md").write_text("note\n", encoding="utf-8")

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: ネスト含めて消える
    assert rc == 0
    assert not legacy.exists()
    assert not nested.exists()


def test_cmd_sync_prune_preserves_unknown_symlink_and_link_target(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 未知名の symlink (link 先は別の場所にある実体ディレクトリ)
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    external = tmp_path / "external" / "legacy"
    external.mkdir(parents=True)
    (external / "SKILL.md").write_text("# external\n", encoding="utf-8")
    custom_link = target / "suno-preflight"
    custom_link.symlink_to(external)

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: symlink と link 先の両方が保護される
    assert rc == 0
    assert os.path.lexists(custom_link)
    assert custom_link.is_symlink()
    assert external.exists()
    assert (external / "SKILL.md").read_text(encoding="utf-8") == "# external\n"


def test_cmd_sync_prune_preserves_unknown_broken_symlink(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 未知名の broken symlink (link 先は存在しない)
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    broken = target / "suno-preflight"
    broken.symlink_to(tmp_path / "does-not-exist")
    assert os.path.lexists(broken)
    assert not broken.exists()  # broken なので exists は False

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: broken symlink もローカル entry として保護される
    assert rc == 0
    assert os.path.lexists(broken)


def test_cmd_sync_prune_preserves_unknown_file(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 未知名のローカル entry が通常ファイル
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    custom_file = target / "suno-preflight"
    custom_file.write_text("local\n", encoding="utf-8")

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: ファイルでもローカル entry として保護される
    assert rc == 0
    assert custom_file.read_text(encoding="utf-8") == "local\n"


def test_cmd_sync_prune_yes_with_no_orphans_is_noop(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: 孤児なし
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: 何も消えず、pruned 行が出ない
    assert rc == 0
    assert (target / "channel-research").exists()
    assert (target / "channel-direction").exists()
    out = capsys.readouterr().out
    # bundled 上書き行に "pruned" の語が紛れ込まないよう、行単位で確認
    pruned_lines = [line for line in out.splitlines() if "pruned" in line and "would-prune" not in line]
    # 集約行 "完了: ... {... 'pruned': 0 ...}" は許容するが個別 entry 行は出ない
    entry_pruned_lines = [line for line in pruned_lines if line.lstrip().startswith("pruned")]
    assert entry_pruned_lines == []


def test_cmd_sync_prune_yes_removes_multiple_orphans(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: 孤児 3 件
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    for name in ("analyze", "collect", "report"):
        (target / name).mkdir()
        (target / name / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: 3 件全て消える + summary に 'pruned': 3
    assert rc == 0
    for name in ("analyze", "collect", "report"):
        assert not (target / name).exists()
    out = capsys.readouterr().out
    assert "'pruned': 3" in out


def test_cmd_sync_prune_dry_run_wins_over_yes(
    fake_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: 孤児 analyze/
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()
    (target / "analyze" / "SKILL.md").write_text("# legacy\n", encoding="utf-8")

    # When: --prune --dry-run --yes （dry-run が優先）
    parser = build_parser()
    args = parser.parse_args(
        ["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--dry-run", "--yes"]
    )
    rc = args.func(args)

    # Then: 削除されず would-prune のみ
    assert rc == 0
    assert (target / "analyze").exists()
    out = capsys.readouterr().out
    assert "would-prune" in out


def test_cmd_sync_prune_only_does_not_prune_bundled(fake_repo: Path, tmp_path: Path) -> None:
    # Given: target に bundled 2 件と孤児 analyze/
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()
    (target / "analyze" / "SKILL.md").write_text("# legacy\n", encoding="utf-8")

    # When: --only channel-research --prune --yes
    #       （bundled は全集合で判定するべきなので channel-direction は残るはず）
    parser = build_parser()
    args = parser.parse_args(
        [
            "sync",
            "--asset",
            "skills",
            "--target",
            str(target),
            "--force",
            "--only",
            "channel-research",
            "--prune",
            "--yes",
        ]
    )
    rc = args.func(args)

    # Then: bundled channel-direction が残る (誤認 prune 防止)
    assert rc == 0
    assert (target / "channel-direction" / "SKILL.md").exists()
    assert (target / "channel-research" / "SKILL.md").exists()


def test_cmd_sync_prune_only_removes_real_orphan(fake_repo: Path, tmp_path: Path) -> None:
    # Given: target に bundled + 孤児 analyze/
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    (target / "analyze").mkdir()

    # When: --only channel-research --prune --yes
    parser = build_parser()
    args = parser.parse_args(
        [
            "sync",
            "--asset",
            "skills",
            "--target",
            str(target),
            "--force",
            "--only",
            "channel-research",
            "--prune",
            "--yes",
        ]
    )
    rc = args.func(args)

    # Then: 真の孤児 analyze/ は削除される (--only でフィルタしても prune 判定は全集合)
    assert rc == 0
    assert not (target / "analyze").exists()


def test_cmd_sync_prune_only_lists_entries_once(
    fake_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: `--only` と `--prune` を併用しても bundled 判定は初回取得結果を再利用する
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(
        [
            "sync",
            "--asset",
            "skills",
            "--target",
            str(target),
            "--force",
            "--only",
            "channel-research",
            "--prune",
            "--yes",
        ]
    )

    import youtube_automation.cli.skills_sync._sync as sync_module

    call_count = 0
    original_list_entries = sync_module._list_entries

    def counting_list_entries(*args: object, **kwargs: object) -> list[str]:
        nonlocal call_count
        call_count += 1
        return original_list_entries(*args, **kwargs)

    monkeypatch.setattr(sync_module, "_list_entries", counting_list_entries)

    # When: sync を実行
    rc = args.func(args)

    # Then: `_list_entries` は 1 回だけ呼ばれる
    assert rc == 0
    assert call_count == 1


def test_cmd_sync_prune_file_asset_warns_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: claude-md asset を扱える fake_repo を仕込む
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.template.md").write_text("# template\n", encoding="utf-8")
    (claude_dir / "skills").mkdir()  # _asset_root("skills") 要件は満たさないがここでは不要
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)

    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"

    # When: --asset claude-md --prune
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "claude-md", "--target", str(target), "--force", "--prune"])
    rc = args.func(args)

    # Then: stderr に file asset での prune 不可警告
    assert rc == 0
    err = capsys.readouterr().err
    assert "[warn] --prune は kind='file'" in err


def test_cmd_sync_prune_file_asset_does_not_delete_neighbors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: claude-md asset 用 fake_repo、target 親に他ファイル
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.template.md").write_text("# template\n", encoding="utf-8")
    (claude_dir / "skills").mkdir()
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)

    target_dir = tmp_path / "downstream" / ".claude"
    target_dir.mkdir(parents=True)
    target = target_dir / "CLAUDE.md"
    neighbor = target_dir / "CLAUDE.local.md"
    neighbor.write_text("# private\n", encoding="utf-8")

    # When: --asset claude-md --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "claude-md", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: 他ファイルは保護される (file asset では prune は実行されない)
    assert rc == 0
    assert neighbor.exists()
    assert neighbor.read_text(encoding="utf-8") == "# private\n"
