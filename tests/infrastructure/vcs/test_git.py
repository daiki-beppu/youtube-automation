from __future__ import annotations

from youtube_automation.infrastructure.vcs._git import parse_status_paths


def test_parse_status_paths_returns_sorted_unique_paths():
    stdout = " M b.txt\0M  a.txt\0 M b.txt\0"

    assert parse_status_paths(stdout) == ("a.txt", "b.txt")


def test_parse_status_paths_reports_both_sides_of_a_rename():
    stdout = "R  new.txt\0old.txt\0 M other.txt\0"

    assert parse_status_paths(stdout) == ("new.txt", "old.txt", "other.txt")


def test_parse_status_paths_skips_copy_source_but_consumes_its_record():
    stdout = "C  copy.txt\0source.txt\0 M other.txt\0"

    assert parse_status_paths(stdout) == ("copy.txt", "other.txt")


def test_parse_status_paths_keeps_paths_with_spaces_and_non_ascii():
    stdout = " M docs/日本語 ノート.md\0"

    assert parse_status_paths(stdout) == ("docs/日本語 ノート.md",)


def test_parse_status_paths_returns_empty_for_clean_tree():
    assert parse_status_paths("") == ()
