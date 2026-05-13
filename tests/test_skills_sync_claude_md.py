"""yt-skills の `claude-md` (kind="file") asset 動作テスト。

`.claude/CLAUDE.template.md` を `.claude/CLAUDE.md` として配布する単一ファイル
asset の list / sync / diff の各サブコマンドが期待通りに動くことを検証する。
"""

from __future__ import annotations

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
def fake_repo_with_claude_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp_path にダミーの `.claude/CLAUDE.template.md` を仕込む。

    `_asset_root` の editable fallback が `_editable_root() / ".claude"` を見るため、
    そこに `CLAUDE.template.md` を置く。`skills` asset と共存させるため
    `.claude/skills/` も作っておく（編集モードの本物リポと同等の構造）。
    """
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.template.md").write_text("# BGM template v0\n", encoding="utf-8")

    skills_dir = claude_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "dummy-skill").mkdir()
    (skills_dir / "dummy-skill" / "SKILL.md").write_text("# dummy\n", encoding="utf-8")

    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)
    return tmp_path


# ---------- _ASSET_SPECS ----------


def test_asset_specs_has_claude_md() -> None:
    spec = _ASSET_SPECS["claude-md"]
    assert spec["kind"] == "file"
    assert spec["source_filename"] == "CLAUDE.template.md"
    assert spec["default_target"] == ".claude/CLAUDE.md"


def test_asset_specs_skills_kind_is_dir() -> None:
    # 後方互換: 既存 skills entry も kind を持つ
    assert _ASSET_SPECS["skills"]["kind"] == "dir"


# ---------- _asset_root ----------


def test_asset_root_claude_md_falls_back_to_editable(fake_repo_with_claude_md: Path) -> None:
    # kind="file" でも `_asset_root` は親ディレクトリ (.claude/) を返す。
    # 実体ファイルは `root / source_filename` で取得する。
    root = _asset_root("claude-md")
    assert root == fake_repo_with_claude_md / ".claude"
    assert (root / "CLAUDE.template.md").is_file()


# ---------- _list_entries ----------


def test_list_entries_file_returns_single_filename(fake_repo_with_claude_md: Path) -> None:
    root = _asset_root("claude-md")
    assert _list_entries(root, kind="file", source_filename="CLAUDE.template.md") == [
        "CLAUDE.template.md"
    ]


def test_list_entries_file_requires_source_filename(fake_repo_with_claude_md: Path) -> None:
    with pytest.raises(ValueError):
        _list_entries(fake_repo_with_claude_md, kind="file")


# ---------- cmd_list ----------


def test_cmd_list_claude_md_shows_template(
    fake_repo_with_claude_md: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    args = parser.parse_args(["list", "--asset", "claude-md"])
    rc = args.func(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "CLAUDE.template.md" in out
    assert "1 件" in out


# ---------- cmd_sync ----------


def test_cmd_sync_claude_md_default_target_is_file_path(fake_repo_with_claude_md: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "claude-md", "--dry-run"])
    skills_sync._resolve_default_target(args)
    assert args.target == ".claude/CLAUDE.md"


def test_cmd_sync_claude_md_creates_file_at_target(
    fake_repo_with_claude_md: Path, tmp_path: Path
) -> None:
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    parser = build_parser()
    args = parser.parse_args(
        ["sync", "--asset", "claude-md", "--target", str(target), "--force"]
    )
    rc = args.func(args)
    assert rc == 0
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "# BGM template v0\n"


def test_cmd_sync_claude_md_does_not_overwrite_local_md(
    fake_repo_with_claude_md: Path, tmp_path: Path
) -> None:
    """`--force` で `.claude/CLAUDE.md` を上書きしても `.claude/CLAUDE.local.md` は触られない。"""
    target_dir = tmp_path / "downstream" / ".claude"
    target_dir.mkdir(parents=True)
    target = target_dir / "CLAUDE.md"
    target.write_text("# OLD\n", encoding="utf-8")
    local = target_dir / "CLAUDE.local.md"
    local.write_text("# my private notes\n", encoding="utf-8")
    local_mtime = local.stat().st_mtime

    parser = build_parser()
    args = parser.parse_args(
        ["sync", "--asset", "claude-md", "--target", str(target), "--force"]
    )
    rc = args.func(args)
    assert rc == 0
    assert target.read_text(encoding="utf-8") == "# BGM template v0\n"
    # local.md は内容も mtime も変化しない
    assert local.read_text(encoding="utf-8") == "# my private notes\n"
    assert local.stat().st_mtime == local_mtime


def test_cmd_sync_claude_md_skips_existing_without_force(
    fake_repo_with_claude_md: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text("# OLD\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["sync", "--asset", "claude-md", "--target", str(target)])
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped" in out
    assert target.read_text(encoding="utf-8") == "# OLD\n"


def test_cmd_sync_claude_md_dry_run_does_not_write(
    fake_repo_with_claude_md: Path, tmp_path: Path
) -> None:
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    parser = build_parser()
    args = parser.parse_args(
        ["sync", "--asset", "claude-md", "--target", str(target), "--dry-run"]
    )
    rc = args.func(args)
    assert rc == 0
    assert not target.exists()


def test_cmd_sync_claude_md_symlink_creates_symlink(
    fake_repo_with_claude_md: Path, tmp_path: Path
) -> None:
    """`--symlink --asset claude-md` で target が source への symlink になる。"""
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    parser = build_parser()
    args = parser.parse_args(
        ["sync", "--asset", "claude-md", "--target", str(target), "--symlink"]
    )
    rc = args.func(args)
    assert rc == 0
    assert target.is_symlink()
    expected_src = (fake_repo_with_claude_md / ".claude" / "CLAUDE.template.md").resolve()
    assert target.resolve() == expected_src
    # symlink 経由で source の内容が読める
    assert target.read_text(encoding="utf-8") == "# BGM template v0\n"


def test_cmd_sync_claude_md_symlink_force_replaces_existing_file(
    fake_repo_with_claude_md: Path, tmp_path: Path
) -> None:
    """既存の通常ファイルがあっても `--symlink --force` で symlink に置き換わる。"""
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text("# OLD regular file\n", encoding="utf-8")
    assert not target.is_symlink()

    parser = build_parser()
    args = parser.parse_args(
        ["sync", "--asset", "claude-md", "--target", str(target), "--symlink", "--force"]
    )
    rc = args.func(args)
    assert rc == 0
    assert target.is_symlink()
    assert target.read_text(encoding="utf-8") == "# BGM template v0\n"


def test_cmd_sync_claude_md_symlink_skips_existing_without_force(
    fake_repo_with_claude_md: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """既存の symlink/file がある状態で `--force` なしなら skipped で何も触らない。"""
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text("# OLD\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(
        ["sync", "--asset", "claude-md", "--target", str(target), "--symlink"]
    )
    rc = args.func(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "skipped" in out
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "# OLD\n"


def test_cmd_sync_claude_md_only_emits_warning_but_runs(
    fake_repo_with_claude_md: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--only` は file asset では意味がないため警告を出す（ただし sync は走る）。"""
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    parser = build_parser()
    args = parser.parse_args(
        [
            "sync",
            "--asset",
            "claude-md",
            "--target",
            str(target),
            "--force",
            "--only",
            "anything",
        ]
    )
    rc = args.func(args)
    captured = capsys.readouterr()
    assert rc == 0
    assert "[warn] --only は kind='file'" in captured.err
    assert target.is_file()


# ---------- cmd_diff ----------


def test_cmd_diff_claude_md_no_diff(
    fake_repo_with_claude_md: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    src = _asset_root("claude-md") / "CLAUDE.template.md"
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "claude-md", "--target", str(target)])
    rc = args.func(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "差分なし" in out


def test_cmd_diff_claude_md_detects_difference(
    fake_repo_with_claude_md: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text("# DIFFERENT\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "claude-md", "--target", str(target)])
    rc = args.func(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "内容が異なる" in out
    assert "CLAUDE.md" in out


def test_cmd_diff_claude_md_missing_target_returns_error(
    fake_repo_with_claude_md: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "claude-md", "--target", str(target)])
    rc = args.func(args)
    err = capsys.readouterr().err
    assert rc == 1
    assert "target が存在しません" in err


def test_cmd_diff_claude_md_target_is_directory_returns_error(
    fake_repo_with_claude_md: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "downstream" / ".claude" / "CLAUDE.md"
    target.mkdir(parents=True)  # ディレクトリ化された壊れた状態を擬似
    parser = build_parser()
    args = parser.parse_args(["diff", "--asset", "claude-md", "--target", str(target)])
    rc = args.func(args)
    err = capsys.readouterr().err
    assert rc == 1
    assert "ファイルではありません" in err


# ---------- argparse choices ----------


def test_argparse_choices_includes_both_assets() -> None:
    parser = build_parser()
    args = parser.parse_args(["list", "--asset", "claude-md"])
    assert args.asset == "claude-md"
    args2 = parser.parse_args(["list", "--asset", "skills"])
    assert args2.asset == "skills"
