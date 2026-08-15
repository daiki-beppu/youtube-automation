"""yt-skills lint — SKILL.md frontmatter の軽量検証 (Issue #2096)。

skill 編集後の検証を pytest 全体実行 (約 4 分) に律速されず秒単位で回すための
サブコマンド。検証ロジックは domains.skills.inventory を単一ソースとし、既存の
回帰テストも同じ domain API を使う。

検証内容 (Issue #652 の strict YAML 契約 + CLAUDE.md「skill frontmatter」規約):
    1. SKILL.md が frontmatter デリミタ `---` で始まり、閉じ `---` を持つ
    2. frontmatter が strict YAML (PyYAML safe_load) で dict として解釈できる
    3. name / description が存在し、いずれも非空文字列
    4. description の値が double-quoted string で書かれている
       (値内の `: ` がマッピング区切りと誤解釈されるのを防ぐ規約)
"""

from __future__ import annotations

import argparse

from youtube_automation.domains.skills.inventory import SkillInventory, lint_skill


def cmd_lint(args: argparse.Namespace) -> int:
    """`yt-skills lint [<skill>...]` — frontmatter を検証し違反があれば非ゼロ exit。"""
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

    failed = 0
    for name in targets:
        violations = lint_skill(root / name)
        if violations:
            failed += 1
            for message in violations:
                print(f"{name}: {message}")

    if failed:
        print(f"lint 失敗: {failed}/{len(targets)} skill に違反があります (source: {root})")
        return 1
    print(f"lint 合格: {len(targets)} skill (source: {root})")
    return 0
