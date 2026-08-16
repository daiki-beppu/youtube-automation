"""yt-skills lint — SKILL.md の軽量契約検証。

Issues #2096, #3749, #3750, #3751, #3793, #3799, #3802, #3803, #3804, #3805。

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
    10. 委譲深さが 1 以下である
    11. SKILL.md 本体が 400 行以下である
    12. 成果物ブロックと `書き込む` 宣言行が存在する
    13. skill-config の登録キーと config.default.yaml が双方向に一致する
    14. 下流に移行対応表の旧 skill-config が残っていない
    15. downstream 配布対象の skill が総数上限以下である
    16. 運用成果物 inventory の owner / schema / consumer / JSON+HTML pair が一致する
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

from youtube_automation.commands.system.skills_sync import _DEV_ONLY_SKILL_NAMES, _migrate_config
from youtube_automation.commands.system.skills_sync._delegation import DelegationGraph, format_path
from youtube_automation.configuration import skills as skill_config
from youtube_automation.domains.documents.operational_artifacts import lint_operational_artifacts
from youtube_automation.domains.skills.inventory import SkillInventory, SkillLintViolation, lint_skill_contract

_SKILL_MD_MAX_LINES: Final[int] = 400
_MAX_SKILL_COUNT: Final[int] = 19
_SKILL_MD_LINE_LIMIT_VIOLATION: Final[str] = "skill_md_line_limit_exceeded"
_DELEGATION_DEPTH_VIOLATION: Final[str] = "delegation_depth_exceeded"

# 2026-08-16 の `yt-skills delegation` は最大深さ 1 のため初期登録は 0 件。
# 深さ違反を段階的に解消する場合だけ (skill, violation type) を追加する。
_ALLOWLISTED_DELEGATION_DEPTH_VIOLATIONS: Final[frozenset[tuple[str, str]]] = frozenset()

# 統合前から上限を超えている skill は、現状より悪化させない範囲で段階的に是正する。
# channel-new は当初 450 行だったが既に上限内へ短縮されたため、猶予から除外済み。
_ALLOWLISTED_SKILL_MD_LINE_COUNTS: Final[dict[str, int]] = {
    "automation-release": 638,
    "loop-video": 410,
    "suno": 594,
}

_ALLOWLISTED_VIOLATIONS = frozenset(
    {
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
    key = (name, violation.identifier)
    if key in _ALLOWLISTED_VIOLATIONS or key in _ALLOWLISTED_DELEGATION_DEPTH_VIOLATIONS:
        return True
    if violation.identifier != _SKILL_MD_LINE_LIMIT_VIOLATION:
        return False
    allowed_line_count = _ALLOWLISTED_SKILL_MD_LINE_COUNTS.get(name)
    return allowed_line_count is not None and line_count <= allowed_line_count


def _lint_delegation_depth(graph: DelegationGraph, name: str) -> SkillLintViolation | None:
    path = graph.longest_path(name)
    if len(path) - 1 < 2:
        return None
    return SkillLintViolation(
        _DELEGATION_DEPTH_VIOLATION,
        f"委譲深さ 2 以上: {format_path(path)}",
    )


def _lint_skill_config_contract(inventory: SkillInventory) -> list[str]:
    python_keys = skill_config.SKILL_CONFIG_KEYS
    skill_only_keys = skill_config.SKILL_ONLY_CONFIG_KEYS
    registered = python_keys | skill_only_keys
    registered_default_owners = {
        skill_config.skill_config_default_relative_path(key.partition(".")[0]).parts[0] for key in registered
    }
    defaults = {
        skill_dir.name for skill_dir in inventory.skill_directories() if (skill_dir / "config.default.yaml").is_file()
    }

    violations = [
        f"{skill_config.skill_config_default_relative_path(key.partition('.')[0])} がありません（登録キー: {key}）"
        for key in sorted(registered)
        if not (
            inventory.skills_root / skill_config.skill_config_default_relative_path(key.partition(".")[0])
        ).is_file()
    ]
    violations.extend(
        f"{key}/config.default.yaml がどちらのキー集合にも登録されていません"
        for key in sorted(defaults - registered_default_owners)
    )
    violations.extend(
        f"{key} が SKILL_CONFIG_KEYS と SKILL_ONLY_CONFIG_KEYS の両方に登録されています"
        for key in sorted(python_keys & skill_only_keys)
    )
    return violations


def _lint_unmigrated_skill_configs(channel_dir: Path) -> list[str]:
    config_dir = channel_dir / "config" / "skills"
    return [
        f"config/skills/{source}.yaml は未移行です: "
        f"yt-skills migrate-config --channel-dir {channel_dir} --dry-run を実行してください"
        for source in sorted(_migrate_config.SKILL_CONFIG_MIGRATIONS)
        if (config_dir / f"{source}.yaml").is_file()
    ]


def _distributed_skill_names(inventory: SkillInventory) -> tuple[str, ...]:
    """Return real sync candidates, excluding dev-only and non-skill residue."""
    return tuple(
        skill_dir.name
        for skill_dir in inventory.skill_directories()
        if (skill_dir / "SKILL.md").is_file() and skill_dir.name not in _DEV_ONLY_SKILL_NAMES
    )


def _skill_count_violation(inventory: SkillInventory) -> str | None:
    count = len(_distributed_skill_names(inventory))
    if count <= _MAX_SKILL_COUNT:
        return None
    return (
        f"配布対象の skill が {count} 件です (上限 {_MAX_SKILL_COUNT} 件 — "
        "新しい skill を足すなら既存 skill の mode として畳めないかを先に検討してください)"
    )


def _operational_artifact_violations(root: Path, inventory: SkillInventory) -> list[str]:
    """Run the repository/wheel artifact ratchet, excluding minimal CLI fixtures."""
    repository_root = root.parents[1] if root.name == "skills" and root.parent.name == ".claude" else root
    is_repository = (repository_root / "pyproject.toml").is_file()
    is_wheel_assets = root.name == "_skills"
    if not is_repository and not is_wheel_assets:
        return []
    return lint_operational_artifacts(repository_root, inventory)


def cmd_lint(args: argparse.Namespace) -> int:
    """`yt-skills lint [<skill>...]` — skill 契約を検証し違反があれば非ゼロ exit。"""
    from youtube_automation.commands.system.skills_sync import _asset_root

    root = _asset_root("skills")
    inventory = SkillInventory(root)
    available = [path.name for path in inventory.skill_directories() if (path / "SKILL.md").is_file()]

    requested: list[str] = getattr(args, "skills", None) or []
    if requested:
        unknown = sorted(set(requested) - set(available))
        if unknown:
            print(f"error: 存在しない skill です: {', '.join(unknown)} (source: {root})")
            return 2
        targets = requested
    else:
        targets = available

    skill_config_violations = (
        [] if requested else [*_lint_skill_config_contract(inventory), *_lint_unmigrated_skill_configs(Path.cwd())]
    )
    skill_count_violation = None if requested else _skill_count_violation(inventory)
    artifact_violations = [] if requested else _operational_artifact_violations(root, inventory)
    for violation in skill_config_violations:
        print(f"skill-config: {violation}")
    if skill_count_violation is not None:
        print(skill_count_violation)
    for violation in artifact_violations:
        print(f"operational-artifacts: {violation}")

    graph = DelegationGraph.load(inventory)

    failed_skills: set[str] = set()
    for name in targets:
        skill_dir = root / name
        violations = lint_skill_contract(skill_dir)
        line_violation, line_count = _lint_skill_md_line_count(skill_dir)
        if line_violation is not None:
            violations.append(line_violation)
        delegation_depth_violation = _lint_delegation_depth(graph, name)
        if delegation_depth_violation is not None:
            violations.append(delegation_depth_violation)
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
    if skill_config_violations:
        print(f"lint 失敗: skill-config 契約に {len(skill_config_violations)} 件の違反があります (source: {root})")
        return 1
    if skill_count_violation is not None:
        print(f"lint 失敗: 配布対象 skill の総数上限を超えています (source: {root})")
        return 1
    if artifact_violations:
        print(f"lint 失敗: 運用成果物契約に {len(artifact_violations)} 件の違反があります (source: {root})")
        return 1
    print(f"lint 合格: {len(targets)} skill (source: {root})")
    return 0
