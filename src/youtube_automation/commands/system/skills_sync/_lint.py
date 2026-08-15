"""yt-skills lint — SKILL.md の軽量契約検証 (Issues #2096, #3749, #3750, #3751, #3793)。

skill 編集後の検証を pytest 全体実行 (約 4 分) に律速されず秒単位で回すための
サブコマンド。frontmatter / flag の検証ロジックは domains.skills.inventory を
単一ソースとし、既存の回帰テストも同じ domain API を使う。

検証内容 (strict YAML 契約 + skill frontmatter / mode 規約):
    1. SKILL.md が frontmatter デリミタ `---` で始まり、閉じ `---` を持つ
    2. frontmatter が strict YAML (PyYAML safe_load) で dict として解釈できる
    3. name / description が存在し、いずれも非空文字列
    4. description の値が double-quoted string で書かれている
       (値内の `: ` がマッピング区切りと誤解釈されるのを防ぐ規約)
    5. purpose が 7 語の enum のいずれかである
    6. description の値なしフラグが mode / modifier 表のどちらか一方に属する
    7. mode は 5 個以下で、2 個以上の同時指定を停止する旨がある
    8. mode ごとにフラグ名と対応する実在 reference を 1 ファイル持つ
    9. 委譲先の宣言行が存在し、有向グラフに循環がない
    10. SKILL.md 本体が 400 行以下である
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

from youtube_automation.commands.system.skills_sync._delegation import DelegationGraph, format_path
from youtube_automation.domains.skills.inventory import SkillInventory, SkillLintViolation, lint_skill_contract

_SKILL_MD_MAX_LINES: Final[int] = 400
_SKILL_MD_LINE_LIMIT_VIOLATION: Final[str] = "skill_md_line_limit_exceeded"

# 統合前から上限を超えている skill は、現状より悪化させない範囲で段階的に是正する。
# channel-new は当初 450 行だったが既に上限内へ短縮されたため、猶予から除外済み。
_ALLOWLISTED_SKILL_MD_LINE_COUNTS: Final[dict[str, int]] = {
    "automation-release": 633,
    "automation-update": 566,
    "collection-ideate": 532,
    "loop-video": 405,
    "masterup": 561,
    "suno": 589,
    "thumbnail": 743,
    "wf-new": 478,
}

_ALLOWLISTED_VIOLATIONS = frozenset(
    {
        ("flop-analysis", "flag_tables_missing"),
        ("shadcn", "flag_tables_missing"),
        ("setup", "mode_reference_name_mismatch"),
    }
)


def _lint_skill_md_line_count(skill_dir: Path) -> tuple[SkillLintViolation | None, int]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None, 0
    line_count = len(skill_md.read_text(encoding="utf-8").splitlines())
    if line_count <= _SKILL_MD_MAX_LINES:
        return None, line_count
    return (
        SkillLintViolation(
            _SKILL_MD_LINE_LIMIT_VIOLATION,
            f"SKILL.md が {line_count} 行です (上限 {_SKILL_MD_MAX_LINES} 行 — references/ へ切り出してください)",
        ),
        line_count,
    )


def _is_allowlisted(name: str, violation: SkillLintViolation, line_count: int) -> bool:
    if (name, violation.identifier) in _ALLOWLISTED_VIOLATIONS:
        return True
    if violation.identifier != _SKILL_MD_LINE_LIMIT_VIOLATION:
        return False
    allowed_line_count = _ALLOWLISTED_SKILL_MD_LINE_COUNTS.get(name)
    return allowed_line_count is not None and line_count <= allowed_line_count


def cmd_lint(args: argparse.Namespace) -> int:
    """`yt-skills lint [<skill>...]` — skill 契約を検証し違反があれば非ゼロ exit。"""
    from youtube_automation.commands.system.skills_sync import _asset_root

    root = _asset_root("skills")
    inventory = SkillInventory(root)
    available = [path.name for path in inventory.skill_directories()]

    requested: list[str] = getattr(args, "skills", None) or []
    if requested:
        unknown = sorted(set(requested) - set(available))
        if unknown:
            print(f"error: 存在しない skill です: {', '.join(unknown)} (source: {root})")
            return 2
        targets = requested
    else:
        targets = available

    graph = DelegationGraph.load(inventory)

    failed_skills: set[str] = set()
    for name in targets:
        skill_dir = root / name
        violations = lint_skill_contract(skill_dir)
        line_violation, line_count = _lint_skill_md_line_count(skill_dir)
        if line_violation is not None:
            violations.append(line_violation)
        if name in graph.missing:
            print(f"{name}: `委譲先` 行がありません")
            failed_skills.add(name)
        blocking = [violation for violation in violations if not _is_allowlisted(name, violation, line_count)]
        if blocking:
            failed_skills.add(name)
        for violation in violations:
            suffix = " [allowlist]" if _is_allowlisted(name, violation, line_count) else ""
            print(f"{name}: {violation.message}{suffix}")

    target_set = set(targets)
    for cycle in graph.cycles():
        if not target_set.intersection(cycle[:-1]):
            continue
        print(f"委譲先に循環があります: {format_path(cycle)}")
        failed_skills.update(target_set.intersection(cycle[:-1]))

    if failed_skills:
        print(f"lint 失敗: {len(failed_skills)}/{len(targets)} skill に違反があります (source: {root})")
        return 1
    print(f"lint 合格: {len(targets)} skill (source: {root})")
    return 0
