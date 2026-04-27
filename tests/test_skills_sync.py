"""yt-skills CLI の汎化動作テスト。

skill 配布パイプラインを `--asset` フラグ経由で動かすことを検証する。
importlib.resources ベースの wheel 解決ではなく、editable install 相当の
fallback (リポジトリルート直下の `.claude/skills/`) を tmp_path で偽装する。
"""

from __future__ import annotations

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


def test_cmd_list_default_asset_is_skills(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    args = parser.parse_args(["list"])
    rc = args.func(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "channel-research" in out
    assert "channel-direction" in out


# ---------- cmd_sync ----------


def test_cmd_sync_default_target_skills(fake_repo: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["sync", "--dry-run"])
    skills_sync._resolve_default_target(args)
    assert args.target == ".claude/skills"
    assert args.asset == "skills"


def test_cmd_sync_skills_dry_run_does_not_write(fake_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "downstream" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--dry-run", "--target", str(target)])
    rc = args.func(args)
    assert rc == 0
    assert not (target / "channel-research").exists()


def test_cmd_sync_skills_copies_skill_dirs(fake_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / ".claude" / "skills"
    parser = build_parser()
    args = parser.parse_args(["sync", "--target", str(target), "--force"])
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
    args = parser.parse_args(["sync", "--target", str(target), "--force"])
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
    args = parser.parse_args(["sync", "--target", str(target)])
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
    args = parser.parse_args(["diff", "--target", str(target)])
    rc = args.func(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "差分なし" in out


def test_cmd_diff_default_asset_is_skills(fake_repo: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["diff"])
    skills_sync._resolve_default_target(args)
    assert args.asset == "skills"
    assert args.target == ".claude/skills"
