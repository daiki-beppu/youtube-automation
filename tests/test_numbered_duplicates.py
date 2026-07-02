"""utils.numbered_duplicates の検知ロジックのテスト (#1410)。"""

from __future__ import annotations

from pathlib import Path

from youtube_automation.utils.numbered_duplicates import (
    find_numbered_duplicates,
    format_duplicate_name,
    numbered_duplicate_base_name,
    scan_numbered_duplicates,
)


class TestNumberedDuplicateBaseName:
    def test_plain_command_bounce(self):
        assert numbered_duplicate_base_name("yt-analytics 2") == "yt-analytics"

    def test_bounce_with_extension(self):
        assert numbered_duplicate_base_name("SKILL 2.md") == "SKILL.md"

    def test_multi_dot_name_keeps_inner_extension(self):
        # iCloud は最終拡張子の直前に連番を挿入する
        assert numbered_duplicate_base_name("abc.tar 2.gz") == "abc.tar.gz"

    def test_double_digit_number(self):
        assert numbered_duplicate_base_name("yt-analytics 12") == "yt-analytics"

    def test_number_one_is_not_bounce(self):
        # bounce は 2 始まり。"chapter 1" 等の正当な命名を誤検知しない
        assert numbered_duplicate_base_name("chapter 1") is None
        assert numbered_duplicate_base_name("chapter 1.md") is None

    def test_zero_padded_number_is_not_bounce(self):
        assert numbered_duplicate_base_name("part 02") is None

    def test_regular_names_are_not_bounce(self):
        assert numbered_duplicate_base_name("yt-analytics") is None
        assert numbered_duplicate_base_name("SKILL.md") is None
        assert numbered_duplicate_base_name("v2") is None


class TestFindNumberedDuplicates:
    def test_detects_bounce_next_to_base(self, tmp_path: Path):
        (tmp_path / "yt-analytics").write_text("#!/bin/sh\n", encoding="utf-8")
        (tmp_path / "yt-analytics 2").write_text("#!/bin/sh\n", encoding="utf-8")
        (tmp_path / "yt-analytics 3").write_text("#!/bin/sh\n", encoding="utf-8")
        found = find_numbered_duplicates(tmp_path)
        assert [p.name for p in found] == ["yt-analytics 2", "yt-analytics 3"]

    def test_ignores_pattern_without_base(self, tmp_path: Path):
        # bounce 元が存在しない場合は正当なファイル名の可能性があるため検知しない
        (tmp_path / "notes 2.md").write_text("memo\n", encoding="utf-8")
        assert find_numbered_duplicates(tmp_path) == []

    def test_non_recursive_ignores_subdirectories(self, tmp_path: Path):
        sub = tmp_path / "skill"
        sub.mkdir()
        (sub / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        (sub / "SKILL 2.md").write_text("# skill\n", encoding="utf-8")
        assert find_numbered_duplicates(tmp_path) == []
        assert [p.name for p in find_numbered_duplicates(tmp_path, recursive=True)] == ["SKILL 2.md"]

    def test_bounced_directory_counts_once(self, tmp_path: Path):
        base = tmp_path / "channel-new"
        base.mkdir()
        (base / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        bounced = tmp_path / "channel-new 2"
        bounced.mkdir()
        (bounced / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        (bounced / "SKILL 2.md").write_text("# skill\n", encoding="utf-8")
        found = find_numbered_duplicates(tmp_path, recursive=True)
        # bounce されたディレクトリは 1 エントリとして数え、配下には降りない
        assert [p.name for p in found] == ["channel-new 2"]

    def test_missing_directory_returns_empty(self, tmp_path: Path):
        assert find_numbered_duplicates(tmp_path / "no-such-dir") == []

    def test_scan_reports_iterdir_errors(self, tmp_path: Path, monkeypatch):
        original_iterdir = Path.iterdir

        def fail_for_root(path: Path):
            if path == tmp_path:
                raise OSError("permission denied")
            return original_iterdir(path)

        monkeypatch.setattr(Path, "iterdir", fail_for_root)

        result = scan_numbered_duplicates(tmp_path)

        assert result.duplicates == ()
        assert len(result.errors) == 1
        assert result.errors[0].path == tmp_path
        assert "permission denied" in result.errors[0].reason

    def test_scan_rejects_symlink_root(self, tmp_path: Path):
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "skills"
        root.symlink_to(outside, target_is_directory=True)

        result = scan_numbered_duplicates(root, recursive=True)

        assert result.duplicates == ()
        assert len(result.errors) == 1
        assert result.errors[0].path == root
        assert "symlink" in result.errors[0].reason

    def test_format_duplicate_name_escapes_control_characters(self, tmp_path: Path):
        path = tmp_path / "yt-\x1b[31m 2"

        rendered = format_duplicate_name(path)

        assert "\x1b" not in rendered
        assert "\\x1b" in rendered
