"""yt-skills lint サブコマンドのテスト (Issue #2096)。

frontmatter 検証ロジック (_lint.py) の単体検証と、CLI 経由の exit code /
出力の検証。editable fallback を tmp_path で偽装する方式は
tests/commands/system/test_skills_sync.py と同じ。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import skills_sync
from youtube_automation.commands.system.skills_sync import build_parser, main
from youtube_automation.domains.skills.inventory import lint_frontmatter_text, lint_skill

_VALID_SKILL_MD = """---
name: good-skill
description: "Use when: 良い skill のとき"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `なし`
- `委譲先`: `なし`

# good
"""


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


def test_cli_lint_allowlisted_violation_is_reported_without_failing(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "flop-analysis",
        '---\nname: flop-analysis\ndescription: "Use --since"\n---\n\n- `委譲先`: `なし`\n\n## 本文\n',
    )

    assert main(["lint", "flop-analysis"]) == 0
    out = capsys.readouterr().out
    assert "flop-analysis:" in out
    assert "allowlist" in out
    assert "lint 合格: 1 skill" in out


def test_cli_lint_allowlist_does_not_hide_another_violation(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "flop-analysis",
        """---
name: flop-analysis
description: "Use --since"
---

## 修飾フラグ

| modifier | 効果 |
|---|---|
| `--other` | 別の調整 |
""",
    )

    assert main(["lint", "flop-analysis"]) == 1
    out = capsys.readouterr().out
    assert "--since" in out
    assert "未登録" in out


def test_cli_lint_missing_mode_reference_reports_skill_flag_and_path(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "mode-skill",
        """---
name: mode-skill
description: "Use --fast"
---

## モード判定

2 個以上の同時指定なら停止する。

| mode | 読む reference |
|---|---|
| `--fast` | `references/fast.md` |
""",
    )

    assert main(["lint", "mode-skill"]) == 1
    out = capsys.readouterr().out
    assert "mode-skill: --fast の reference が見つかりません: references/fast.md" in out


def test_cli_lint_analytics_mode_references_are_valid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: REPO_ROOT)

    assert main(["lint", "analytics"]) == 0
    out = capsys.readouterr().out
    assert "lint 合格: 1 skill" in out
    assert "analytics:" not in out


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


def test_cli_lint_missing_delegation_line_exits_nonzero(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "missing-delegation",
        '---\nname: missing-delegation\ndescription: "Use when missing"\n---\n',
    )

    assert main(["lint", "missing-delegation"]) == 1
    out = capsys.readouterr().out
    assert "missing-delegation: `委譲先` 行がありません" in out


def test_cli_lint_delegation_cycle_reports_path_and_exits_nonzero(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "alpha",
        _VALID_SKILL_MD.replace("good-skill", "alpha").replace("`なし`\n\n# good", "`/beta`\n\n# good"),
    )
    _write_skill(
        skills_dir,
        "beta",
        _VALID_SKILL_MD.replace("good-skill", "beta").replace("`なし`\n\n# good", "`/alpha`\n\n# good"),
    )

    assert main(["lint"]) == 1
    out = capsys.readouterr().out
    assert "循環があります: /alpha -> /beta -> /alpha" in out


def test_cli_lint_self_delegation_reports_cycle_and_exits_nonzero(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "recursive",
        _VALID_SKILL_MD.replace("good-skill", "recursive").replace("`なし`\n\n# good", "`/recursive`\n\n# good"),
    )

    assert main(["lint", "recursive"]) == 1
    assert "循環があります: /recursive -> /recursive" in capsys.readouterr().out


def test_cli_lint_does_not_reject_delegation_depth_two(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "alpha",
        _VALID_SKILL_MD.replace("good-skill", "alpha").replace("`なし`\n\n# good", "`/beta`\n\n# good"),
    )
    _write_skill(
        skills_dir,
        "beta",
        _VALID_SKILL_MD.replace("good-skill", "beta").replace("`なし`\n\n# good", "`/gamma`\n\n# good"),
    )
    _write_skill(skills_dir, "gamma", _VALID_SKILL_MD.replace("good-skill", "gamma"))

    assert main(["lint"]) == 0
    assert "lint 合格: 4 skill" in capsys.readouterr().out


def test_cli_delegation_reports_each_depth_longest_path_and_summary(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "alpha",
        _VALID_SKILL_MD.replace("good-skill", "alpha").replace("`なし`\n\n# good", "`/beta`, `/leaf`\n\n# good"),
    )
    _write_skill(
        skills_dir,
        "beta",
        _VALID_SKILL_MD.replace("good-skill", "beta").replace("`なし`\n\n# good", "`/leaf`\n\n# good"),
    )
    _write_skill(skills_dir, "leaf", _VALID_SKILL_MD.replace("good-skill", "leaf"))

    assert main(["delegation"]) == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "2" in out
    assert "/alpha -> /beta -> /leaf" in out
    assert "最大深さ: 2 / 委譲を持つ skill: 2 件 / 循環: 0 件" in out


def test_cli_delegation_without_edges_reports_zero_depth(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["delegation"]) == 0
    out = capsys.readouterr().out
    assert "/good-skill" in out
    assert "最大深さ: 0 / 委譲を持つ skill: 0 件 / 循環: 0 件" in out


def test_cli_delegation_with_cycle_reports_it_and_exits_zero(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "recursive",
        _VALID_SKILL_MD.replace("good-skill", "recursive").replace("`なし`\n\n# good", "`/recursive`\n\n# good"),
    )

    assert main(["delegation"]) == 0
    assert "循環: 1 件" in capsys.readouterr().out
