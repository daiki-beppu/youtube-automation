"""yt-skills CLI の汎化動作テスト。

skill 配布パイプラインを `--asset` フラグ経由で動かすことを検証する。
importlib.resources ベースの wheel 解決ではなく、editable install 相当の
fallback (リポジトリルート直下の `.claude/skills/`) を tmp_path で偽装する。
"""

from __future__ import annotations

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
    # Given: target に bundled + 孤児 (only_disk) 1 件
    target = tmp_path / "out" / ".claude" / "skills"
    target.mkdir(parents=True)
    src = _asset_root("skills")
    for entry in src.iterdir():
        shutil.copytree(entry, target / entry.name)
    (target / "legacy-skill").mkdir()
    (target / "legacy-skill" / "SKILL.md").write_text("# legacy\n", encoding="utf-8")

    # When: diff を実行
    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "skills", "--target", str(target)])
    rc = args.func(args)

    # Then: 孤児リスト直後に --prune の案内が出る
    assert rc == 0
    out = capsys.readouterr().out
    assert "target にのみ存在" in out
    assert "legacy-skill" in out
    assert "--prune" in out
    assert "--yes" in out


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


def test_cmd_sync_prune_removes_orphan_symlink_but_keeps_link_target(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 孤児 symlink (link 先は別の場所にある実体ディレクトリ)
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    external = tmp_path / "external" / "legacy"
    external.mkdir(parents=True)
    (external / "SKILL.md").write_text("# external\n", encoding="utf-8")
    orphan_link = target / "legacy-link"
    orphan_link.symlink_to(external)

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: symlink は消えるが link 先は残る
    assert rc == 0
    assert not os.path.lexists(orphan_link)
    assert external.exists()
    assert (external / "SKILL.md").read_text(encoding="utf-8") == "# external\n"


def test_cmd_sync_prune_removes_orphan_broken_symlink(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 孤児 broken symlink (link 先は存在しない)
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    broken = target / "broken-link"
    broken.symlink_to(tmp_path / "does-not-exist")
    assert os.path.lexists(broken)
    assert not broken.exists()  # broken なので exists は False

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: broken symlink も消える
    assert rc == 0
    assert not os.path.lexists(broken)


def test_cmd_sync_prune_removes_orphan_file(fake_repo: Path, tmp_path: Path) -> None:
    # Given: 孤児が通常ファイル
    target = tmp_path / "out" / ".claude" / "skills"
    _seed_bundled_target(target)
    orphan_file = target / "analyze.txt"
    orphan_file.write_text("legacy\n", encoding="utf-8")

    # When: --prune --yes
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "skills", "--target", str(target), "--force", "--prune", "--yes"])
    rc = args.func(args)

    # Then: ファイルでも削除される
    assert rc == 0
    assert not orphan_file.exists()


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
