"""yt-skills lint — SKILL.md の軽量契約検証 (Issues #2096, #3749, #3750, #3751)。

skill 編集後の検証を pytest 全体実行 (約 4 分) に律速されず秒単位で回すための
サブコマンド。検証ロジックは domains.skills.inventory を単一ソースとし、既存の
回帰テストも同じ domain API を使う。

検証内容 (strict YAML 契約 + skill frontmatter / mode 規約):
    1. SKILL.md が frontmatter デリミタ `---` で始まり、閉じ `---` を持つ
    2. frontmatter が strict YAML (PyYAML safe_load) で dict として解釈できる
    3. name / description が存在し、いずれも非空文字列
    4. description の値が double-quoted string で書かれている
       (値内の `: ` がマッピング区切りと誤解釈されるのを防ぐ規約)
    5. description の値なしフラグが mode / modifier 表のどちらか一方に属する
    6. mode は 5 個以下で、2 個以上の同時指定を停止する旨がある
    7. mode ごとにフラグ名と対応する実在 reference を 1 ファイル持つ
    8. 委譲先の宣言行が存在し、有向グラフに循環がない
"""

from __future__ import annotations

import argparse

from youtube_automation.commands.system.skills_sync._delegation import DelegationGraph, format_path
from youtube_automation.domains.skills.inventory import SkillInventory, lint_skill_contract

_ALLOWLISTED_VIOLATIONS = frozenset(
    {
        ("flop-analysis", "flag_tables_missing"),
        ("shadcn", "flag_tables_missing"),
        ("setup", "mode_reference_name_mismatch"),
    }
)


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
        violations = lint_skill_contract(root / name)
        if name in graph.missing:
            print(f"{name}: `委譲先` 行がありません")
            failed_skills.add(name)
        blocking = [
            violation for violation in violations if (name, violation.identifier) not in _ALLOWLISTED_VIOLATIONS
        ]
        if blocking:
            failed_skills.add(name)
        for violation in violations:
            suffix = " [allowlist]" if (name, violation.identifier) in _ALLOWLISTED_VIOLATIONS else ""
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
