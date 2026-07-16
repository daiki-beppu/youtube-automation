"""`tests/helpers/hcl.py` の挙動回帰テスト (Issue #169)。

`tests/test_terraform_streaming.py` / `tests/test_streaming_healthcheck.py` が
依存する 3 関数の挙動を凍結し、リファクタによる挙動ドリフトを検出する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.hcl import extract_block, find_block_with_position, read_file, strip_hcl_comments


class TestStripHclComments:
    def test_removes_hash_line_comments(self):
        text = "foo # comment\nbar"
        assert strip_hcl_comments(text) == "foo \nbar"

    def test_removes_double_slash_line_comments(self):
        text = "foo // comment\nbar"
        assert strip_hcl_comments(text) == "foo \nbar"

    def test_removes_block_comments_non_greedy(self):
        text = "a /* one */ b /* two */ c"
        assert strip_hcl_comments(text) == "a  b  c"

    def test_block_comment_spans_lines(self):
        text = "before /* multi\nline */ after"
        assert strip_hcl_comments(text) == "before  after"


class TestReadFile:
    def test_reads_existing_utf8_file(self, tmp_path: Path):
        target = tmp_path / "sample.txt"
        target.write_text("こんにちは", encoding="utf-8")
        assert read_file(target) == "こんにちは"

    def test_missing_file_calls_pytest_fail(self):
        # `_REPO_ROOT` 配下のリポジトリには確実に存在しない相対パスを与え、
        # `relative_to` を成立させた上で ``pytest.fail`` の発火だけを観測する。
        repo_root = Path(__file__).resolve().parent.parent.parent
        missing = repo_root / "__definitely_missing_file__.txt"
        assert not missing.exists()
        with pytest.raises(pytest.fail.Exception):
            read_file(missing)


class TestExtractBlock:
    def test_extracts_simple_block(self):
        text = 'terraform {\n  required_version = ">= 1.5"\n}\n'
        assert extract_block(text, r"terraform") == '\n  required_version = ">= 1.5"\n'

    def test_extracts_nested_block_balanced(self):
        text = "outer {\n  inner {\n    x = 1\n  }\n}\n"
        body = extract_block(text, r"outer")
        assert body is not None
        assert "inner {" in body
        assert body.count("{") == body.count("}")

    def test_returns_none_when_header_missing(self):
        assert extract_block("foo { bar }", r"baz") is None

    def test_supports_object_literal_with_equals(self):
        text = 'required_providers = {\n  vultr = { source = "vultr/vultr" }\n}\n'
        body = extract_block(text, r"required_providers")
        assert body is not None
        assert 'vultr = { source = "vultr/vultr" }' in body


class TestFindBlockWithPosition:
    def test_returns_matching_repeated_block_and_its_header_position(self):
        text = (
            'provisioner "remote-exec" {\n  inline = ["first"]\n}\n'
            'provisioner "remote-exec" {\n  inline = ["target"]\n}\n'
        )

        found = find_block_with_position(text, r'provisioner\s+"remote-exec"', "target")

        assert found is not None
        body, position = found
        assert "target" in body
        assert position == text.rfind('provisioner "remote-exec"')

    def test_returns_none_when_no_repeated_block_contains_required_text(self):
        assert find_block_with_position('item { value = "one" }', r"item", "two") is None
