"""yt-skills lint サブコマンドのテスト (Issue #2096)。

frontmatter 検証ロジック (_lint.py) の単体検証と、CLI 経由の exit code /
出力の検証。editable fallback を tmp_path で偽装する方式は
tests/test_skills_sync.py と同じ。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.cli import skills_sync
from youtube_automation.cli.skills_sync import build_parser, main
from youtube_automation.cli.skills_sync._lint import lint_frontmatter_text, lint_skill

_VALID_SKILL_MD = '---\nname: good-skill\ndescription: "Use when: 良い skill のとき"\n---\n\n# good\n'


def _write_skill(skills_dir: Path, name: str, content: str) -> None:
    (skills_dir / name).mkdir()
    (skills_dir / name / "SKILL.md").write_text(content, encoding="utf-8")


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp_path にダミーの skills ツリーを仕込み editable fallback を向ける。"""
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    _write_skill(skills_dir, "good-skill", _VALID_SKILL_MD)
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)
    return tmp_path


# ---------- lint_frontmatter_text (検証ロジック単体) ----------


def test_lint_valid_frontmatter_has_no_violations() -> None:
    assert lint_frontmatter_text(_VALID_SKILL_MD) == []


def test_lint_missing_opening_delimiter() -> None:
    violations = lint_frontmatter_text("# no frontmatter\n")
    assert len(violations) == 1
    assert "'---' で始まっていません" in violations[0]


def test_lint_missing_closing_delimiter() -> None:
    violations = lint_frontmatter_text('---\nname: x\ndescription: "y"\n')
    assert len(violations) == 1
    assert "閉じデリミタ" in violations[0]


def test_lint_unquoted_description_with_colon_breaks_strict_yaml() -> None:
    # Issue #652 の本丸: 値内の `: ` が bare だとマッピング区切りと誤解釈される
    text = "---\nname: x\ndescription: Use when: 発動条件\n---\n"
    violations = lint_frontmatter_text(text)
    assert violations
    assert "strict YAML" in violations[0]


def test_lint_unquoted_description_without_colon_violates_quote_rule() -> None:
    # パースは通るが double-quote 規約に違反するケース
    text = "---\nname: x\ndescription: 発動条件の説明\n---\n"
    violations = lint_frontmatter_text(text)
    assert any("double-quoted" in v for v in violations)


def test_lint_missing_keys_reported_individually() -> None:
    violations = lint_frontmatter_text("---\ntitle: x\n---\n")
    assert any("'name' がありません" in v for v in violations)
    assert any("'description' がありません" in v for v in violations)


def test_lint_empty_description_violates() -> None:
    violations = lint_frontmatter_text('---\nname: x\ndescription: "  "\n---\n')
    assert any("'description' が空です" in v for v in violations)


def test_lint_non_dict_frontmatter_violates() -> None:
    violations = lint_frontmatter_text("---\n- a\n- b\n---\n")
    assert violations == ["frontmatter が dict として解釈できません"]


def test_lint_skill_without_skill_md(tmp_path: Path) -> None:
    (tmp_path / "empty-skill").mkdir()
    assert lint_skill(tmp_path / "empty-skill") == ["SKILL.md がありません"]


# ---------- cmd_lint (CLI 経由) ----------


def test_cli_lint_all_green_exits_zero(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint"]) == 0
    out = capsys.readouterr().out
    assert "lint 合格: 1 skill" in out


def test_cli_lint_violation_exits_nonzero(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "bad-skill", "---\nname: bad\ndescription: Use when: 壊れる\n---\n")

    assert main(["lint"]) == 1
    out = capsys.readouterr().out
    assert "bad-skill:" in out
    assert "lint 失敗: 1/2 skill" in out


def test_cli_lint_single_skill_filters_targets(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "bad-skill", "# frontmatter なし\n")

    # 正常な skill だけを指定すれば bad-skill は検証されず green
    assert main(["lint", "good-skill"]) == 0
    out = capsys.readouterr().out
    assert "bad-skill" not in out


def test_cli_lint_unknown_skill_exits_two(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint", "no-such-skill"]) == 2
    out = capsys.readouterr().out
    assert "存在しない skill" in out
    assert "no-such-skill" in out


def test_lint_parser_registered() -> None:
    parser = build_parser()
    args = parser.parse_args(["lint", "a", "b"])
    assert args.skills == ["a", "b"]
    assert args.asset == "skills"
