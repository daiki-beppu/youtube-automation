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
from youtube_automation.commands.system.skills_sync import _lint, _migrate_config, build_parser, main
from youtube_automation.commands.system.skills_sync._delegation import DelegationGraph
from youtube_automation.configuration import skills as skill_config
from youtube_automation.domains.skills.inventory import SkillInventory, lint_frontmatter_text, lint_skill

_VALID_SKILL_MD = """---
name: good-skill
description: "Use when: 良い skill のとき"
purpose: 作る
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `なし`
- `読み込む`: `なし`

# good
"""


def _write_skill(skills_dir: Path, name: str, content: str) -> None:
    (skills_dir / name).mkdir()
    (skills_dir / name / "SKILL.md").write_text(content, encoding="utf-8")


def _skill_md_with_line_count(line_count: int, *, name: str = "good-skill") -> str:
    lines = _VALID_SKILL_MD.replace("good-skill", name).splitlines()
    return "\n".join([*lines, *(["本文"] * (line_count - len(lines)))])


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp_path にダミーの skills ツリーを仕込み editable fallback を向ける。"""
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    _write_skill(skills_dir, "good-skill", _VALID_SKILL_MD)
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)
    monkeypatch.setattr(skill_config, "SKILL_CONFIG_KEYS", frozenset())
    monkeypatch.setattr(skill_config, "SKILL_ONLY_CONFIG_KEYS", frozenset())
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
    text = "---\nname: x\ndescription: 発動条件の説明\npurpose: 作る\n---\n"
    violations = lint_frontmatter_text(text)
    assert any("double-quoted" in v for v in violations)


def test_lint_missing_keys_reported_individually() -> None:
    violations = lint_frontmatter_text("---\ntitle: x\n---\n")
    assert any("'name' がありません" in v for v in violations)
    assert any("'description' がありません" in v for v in violations)


def test_lint_empty_description_violates() -> None:
    violations = lint_frontmatter_text('---\nname: x\ndescription: "  "\npurpose: 作る\n---\n')
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


def test_cli_lint_missing_purpose_reports_skill_and_exits_nonzero(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "missing-purpose",
        '---\nname: missing-purpose\ndescription: "Use when missing"\n---\n\n- `委譲先`: `なし`\n',
    )

    assert main(["lint", "missing-purpose"]) == 1
    out = capsys.readouterr().out
    assert "missing-purpose: frontmatter に 'purpose' がありません" in out


def test_cli_lint_unknown_purpose_reports_allowed_values_and_exits_nonzero(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "unknown-purpose",
        '---\nname: unknown-purpose\ndescription: "Use when unknown"\npurpose: 測る\n---\n\n- `委譲先`: `なし`\n',
    )

    assert main(["lint", "unknown-purpose"]) == 1
    out = capsys.readouterr().out
    assert "unknown-purpose: 'purpose' が許容値ではありません" in out
    for purpose in ("準備する", "調べる", "決める", "進める", "作る", "公開する", "振り返る"):
        assert purpose in out


def test_cli_lint_list_purpose_reports_single_value_requirement_and_exits_nonzero(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "multiple-purposes",
        """---
name: multiple-purposes
description: "Use when multiple"
purpose: [作る, 公開する]
---

- `委譲先`: `なし`
""",
    )

    assert main(["lint", "multiple-purposes"]) == 1
    out = capsys.readouterr().out
    assert "multiple-purposes: 'purpose' は単一の文字列で指定してください" in out


def test_cli_lint_removed_flop_analysis_allowlist_now_fails(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "flop-analysis",
        """---
name: flop-analysis
description: "Use --since"
purpose: 振り返る
---

## 成果物

- `書き込む`: `なし`
- `読み込む`: `なし`

- `委譲先`: `なし`

## 本文
""",
    )

    assert main(["lint", "flop-analysis"]) == 1
    out = capsys.readouterr().out
    assert "flop-analysis:" in out
    assert "allowlist" not in out
    assert "lint 失敗: 1/1 skill" in out


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
purpose: 振り返る
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


def test_cli_lint_skill_md_over_400_lines_reports_count_and_exits_nonzero(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "long-skill", _skill_md_with_line_count(401, name="long-skill"))

    assert main(["lint", "long-skill"]) == 1
    out = capsys.readouterr().out
    assert "long-skill: SKILL.md が 401 行です (上限 400 行 — references/ へ切り出してください)" in out


def test_cli_lint_skill_md_at_400_lines_exits_zero(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "limit-skill", _skill_md_with_line_count(400, name="limit-skill"))

    assert main(["lint", "limit-skill"]) == 0
    out = capsys.readouterr().out
    assert "limit-skill: SKILL.md" not in out


def test_cli_lint_allowlisted_skill_md_line_violation_is_reported_without_failing(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "automation-release", _skill_md_with_line_count(401, name="automation-release"))

    assert main(["lint", "automation-release"]) == 0
    out = capsys.readouterr().out
    assert "automation-release: SKILL.md が 401 行です" in out
    assert "[allowlist]" in out


def test_cli_lint_allowlisted_skill_md_growth_exits_nonzero(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "automation-release", _skill_md_with_line_count(639, name="automation-release"))

    assert main(["lint", "automation-release"]) == 1
    out = capsys.readouterr().out
    assert "automation-release: SKILL.md が 639 行です" in out
    assert "[allowlist]" not in out


def test_cli_lint_resolved_thumbnail_line_violation_is_not_allowlisted(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "thumbnail", _skill_md_with_line_count(401, name="thumbnail"))

    assert main(["lint", "thumbnail"]) == 1
    out = capsys.readouterr().out
    assert "thumbnail: SKILL.md が 401 行です" in out
    assert "[allowlist]" not in out


def test_cli_lint_does_not_count_reference_lines(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    reference = skills_dir / "good-skill" / "references" / "details.md"
    reference.parent.mkdir()
    reference.write_text("\n".join(["詳細"] * 500), encoding="utf-8")

    assert main(["lint", "good-skill"]) == 0
    assert "SKILL.md が" not in capsys.readouterr().out


def test_cli_lint_rejects_registered_skill_config_without_default(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(skill_config, "SKILL_CONFIG_KEYS", frozenset({"missing-config"}))

    assert main(["lint"]) == 1
    assert "missing-config/config.default.yaml がありません" in capsys.readouterr().out


def test_cli_lint_rejects_unregistered_skill_config_default(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    default_config = fake_repo / ".claude" / "skills" / "good-skill" / "config.default.yaml"
    default_config.write_text("{}\n", encoding="utf-8")

    assert main(["lint"]) == 1
    assert "good-skill/config.default.yaml がどちらのキー集合にも登録されていません" in capsys.readouterr().out


def test_cli_lint_rejects_skill_config_registered_in_both_key_sets(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default_config = fake_repo / ".claude" / "skills" / "good-skill" / "config.default.yaml"
    default_config.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(skill_config, "SKILL_CONFIG_KEYS", frozenset({"good-skill"}))
    monkeypatch.setattr(skill_config, "SKILL_ONLY_CONFIG_KEYS", frozenset({"good-skill"}))

    assert main(["lint"]) == 1
    assert "good-skill が SKILL_CONFIG_KEYS と SKILL_ONLY_CONFIG_KEYS の両方" in capsys.readouterr().out


def test_cli_lint_resolves_namespaced_key_to_owning_skill_default(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "music", _VALID_SKILL_MD.replace("good-skill", "music"))
    (skills_dir / "music" / "config.default.yaml").write_text("prompt: {}\n", encoding="utf-8")
    monkeypatch.setattr(skill_config, "SKILL_CONFIG_KEYS", frozenset({"music.prompt"}))

    assert main(["lint"]) == 0
    assert "lint 合格" in capsys.readouterr().out


def test_cli_lint_accepts_registered_key_whose_default_moved_to_another_skill(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(skills_dir, "channel-research", _VALID_SKILL_MD.replace("good-skill", "channel-research"))
    (skills_dir / "channel-research" / "config.default.yaml").write_text("freshness_days: 3\n", encoding="utf-8")
    monkeypatch.setattr(skill_config, "SKILL_CONFIG_KEYS", frozenset({"benchmark"}))
    monkeypatch.setattr(skill_config, "SKILL_ONLY_CONFIG_KEYS", frozenset())
    monkeypatch.setattr(
        skill_config,
        "_MOVED_SKILL_CONFIG_DEFAULTS",
        {"benchmark": Path("channel-research/config.default.yaml")},
    )

    assert main(["lint"]) == 0
    assert "lint 合格" in capsys.readouterr().out


def test_cli_lint_guides_unmigrated_downstream_skill_config(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = fake_repo / "config" / "skills" / "suno.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("model: v5\n", encoding="utf-8")
    monkeypatch.chdir(fake_repo)
    monkeypatch.setattr(
        _migrate_config,
        "SKILL_CONFIG_MIGRATIONS",
        {"suno": _migrate_config.SkillConfigMigration("music", "prompt")},
    )

    assert main(["lint"]) == 1
    output = capsys.readouterr().out
    assert "config/skills/suno.yaml は未移行" in output
    assert "yt-skills migrate-config" in output


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
purpose: 作る
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
        '---\nname: missing-delegation\ndescription: "Use when missing"\npurpose: 作る\n---\n',
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
        _VALID_SKILL_MD.replace("good-skill", "alpha").replace("- `委譲先`: `なし`", "- `委譲先`: `/beta`"),
    )
    _write_skill(
        skills_dir,
        "beta",
        _VALID_SKILL_MD.replace("good-skill", "beta").replace("- `委譲先`: `なし`", "- `委譲先`: `/alpha`"),
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
        _VALID_SKILL_MD.replace("good-skill", "recursive").replace("- `委譲先`: `なし`", "- `委譲先`: `/recursive`"),
    )

    assert main(["lint", "recursive"]) == 1
    assert "循環があります: /recursive -> /recursive" in capsys.readouterr().out


def test_cli_lint_rejects_delegation_depth_two_with_path(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "alpha",
        _VALID_SKILL_MD.replace("good-skill", "alpha").replace("- `委譲先`: `なし`", "- `委譲先`: `/beta`"),
    )
    _write_skill(
        skills_dir,
        "beta",
        _VALID_SKILL_MD.replace("good-skill", "beta").replace("- `委譲先`: `なし`", "- `委譲先`: `/gamma`"),
    )
    _write_skill(skills_dir, "gamma", _VALID_SKILL_MD.replace("good-skill", "gamma"))

    assert main(["lint"]) == 1
    out = capsys.readouterr().out
    assert "alpha: 委譲深さ 2 以上: /alpha -> /beta -> /gamma" in out
    assert "lint 失敗: 1/4 skill" in out


def test_cli_lint_accepts_delegation_depth_one_boundary(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "alpha",
        _VALID_SKILL_MD.replace("good-skill", "alpha").replace("- `委譲先`: `なし`", "- `委譲先`: `/leaf`"),
    )
    _write_skill(skills_dir, "leaf", _VALID_SKILL_MD.replace("good-skill", "leaf"))

    assert main(["lint"]) == 0
    assert "委譲深さ 2 以上" not in capsys.readouterr().out


def test_cli_lint_reports_allowlisted_depth_without_failing(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "alpha",
        _VALID_SKILL_MD.replace("good-skill", "alpha").replace("- `委譲先`: `なし`", "- `委譲先`: `/beta`"),
    )
    _write_skill(
        skills_dir,
        "beta",
        _VALID_SKILL_MD.replace("good-skill", "beta").replace("- `委譲先`: `なし`", "- `委譲先`: `/gamma`"),
    )
    _write_skill(skills_dir, "gamma", _VALID_SKILL_MD.replace("good-skill", "gamma"))
    monkeypatch.setattr(
        _lint,
        "_ALLOWLISTED_DELEGATION_DEPTH_VIOLATIONS",
        frozenset({("alpha", "delegation_depth_exceeded")}),
    )

    assert main(["lint"]) == 0
    out = capsys.readouterr().out
    assert "alpha: 委譲深さ 2 以上: /alpha -> /beta -> /gamma [allowlist]" in out
    assert "lint 合格: 4 skill" in out


def test_real_delegation_depth_allowlist_matches_current_delegation_output() -> None:
    graph = DelegationGraph.load(SkillInventory(REPO_ROOT / ".claude" / "skills"))
    violations = {
        (skill, "delegation_depth_exceeded") for skill in graph.edges if len(graph.longest_path(skill)) - 1 >= 2
    }

    assert violations == set(_lint._ALLOWLISTED_DELEGATION_DEPTH_VIOLATIONS)


def test_authoring_guidelines_require_shallow_delegation_or_chain_manifest() -> None:
    guidelines = (REPO_ROOT / "docs" / "skill-design" / "skill-authoring-guidelines.md").read_text(encoding="utf-8")

    assert "委譲深さは 1 以下" in guidelines
    assert "委譲先を持つ skill の委譲先がさらに別 skill へ委譲してはいけない" in guidelines
    assert "[chain-manifest-schema.md](chain-manifest-schema.md)" in guidelines
    assert "薄いインタープリタ方式" in guidelines


def test_cli_delegation_reports_each_depth_longest_path_and_summary(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills_dir = fake_repo / ".claude" / "skills"
    _write_skill(
        skills_dir,
        "alpha",
        _VALID_SKILL_MD.replace("good-skill", "alpha").replace("- `委譲先`: `なし`", "- `委譲先`: `/beta`, `/leaf`"),
    )
    _write_skill(
        skills_dir,
        "beta",
        _VALID_SKILL_MD.replace("good-skill", "beta").replace("- `委譲先`: `なし`", "- `委譲先`: `/leaf`"),
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
        _VALID_SKILL_MD.replace("good-skill", "recursive").replace("- `委譲先`: `なし`", "- `委譲先`: `/recursive`"),
    )

    assert main(["delegation"]) == 0
    assert "循環: 1 件" in capsys.readouterr().out
