"""yt-skills lint — SKILL.md frontmatter の軽量検証 (Issue #2096)。

skill 編集後の検証を pytest 全体実行 (約 4 分) に律速されず秒単位で回すための
サブコマンド。検証ロジックはこのモジュールを単一ソースとし、既存の回帰テスト
(tests/test_skill_frontmatter_yaml.py) もここを import して同じ判定基準を使う。

検証内容 (Issue #652 の strict YAML 契約 + CLAUDE.md「skill frontmatter」規約):
    1. SKILL.md が frontmatter デリミタ `---` で始まり、閉じ `---` を持つ
    2. frontmatter が strict YAML (PyYAML safe_load) で dict として解釈できる
    3. name / description が存在し、いずれも非空文字列
    4. description の値が double-quoted string で書かれている
       (値内の `: ` がマッピング区切りと誤解釈されるのを防ぐ規約)
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

_FRONTMATTER_DELIMITER = "---"

# frontmatter 内の description 行が double-quoted string で始まることを検査する。
# 値が複数行に折り返されていても、開始行が `description: "` であればよい。
_DESCRIPTION_DOUBLE_QUOTED = re.compile(r'^description:\s*"', re.MULTILINE)


def extract_frontmatter(text: str) -> str:
    """先頭の `---` から次の `---` までの frontmatter ブロックを返す。

    デリミタが欠けている場合は `ValueError` を raise する (呼び出し側で
    violation メッセージに変換する)。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        raise ValueError("SKILL.md が frontmatter デリミタ '---' で始まっていません")
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONTMATTER_DELIMITER:
            return "\n".join(lines[1:i])
    raise ValueError("frontmatter の閉じデリミタ '---' が見つかりません")


def lint_frontmatter_text(text: str) -> list[str]:
    """SKILL.md 全文を検証し、違反メッセージのリストを返す (空 = 合格)。

    最初に構造 (デリミタ / YAML パース) を検証し、破綻していたらその時点の
    violation だけ返す (壊れた frontmatter に対するキー検査は無意味なため)。
    """
    try:
        frontmatter = extract_frontmatter(text)
    except ValueError as exc:
        return [str(exc)]

    try:
        parsed = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        return [f"frontmatter が strict YAML として解釈できません: {exc}"]

    if not isinstance(parsed, dict):
        return ["frontmatter が dict として解釈できません"]

    violations: list[str] = []
    for key in ("name", "description"):
        if key not in parsed:
            violations.append(f"frontmatter に '{key}' がありません")
        elif not isinstance(parsed[key], str):
            violations.append(f"'{key}' が文字列ではありません")
        elif not parsed[key].strip():
            violations.append(f"'{key}' が空です")

    if "description" in parsed and not _DESCRIPTION_DOUBLE_QUOTED.search(frontmatter):
        violations.append(
            'description が double-quoted string ではありません (CLAUDE.md 規約: description: "..." で書く)'
        )

    return violations


def lint_skill(skill_dir: Path) -> list[str]:
    """skill ディレクトリ 1 件を検証し、違反メッセージのリストを返す。"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return ["SKILL.md がありません"]
    return lint_frontmatter_text(skill_md.read_text(encoding="utf-8"))


def cmd_lint(args: argparse.Namespace) -> int:
    """`yt-skills lint [<skill>...]` — frontmatter を検証し違反があれば非ゼロ exit。"""
    from youtube_automation.cli.skills_sync import _asset_root

    root = _asset_root("skills")
    available = sorted(p.name for p in root.iterdir() if p.is_dir())

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
