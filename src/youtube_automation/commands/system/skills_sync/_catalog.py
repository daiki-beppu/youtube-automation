"""Generate the purpose-based skill catalog."""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path
from typing import Final

from youtube_automation.domains.skills.inventory import SkillInventory

_PURPOSE_ORDER: Final[tuple[str, ...]] = (
    "準備する",
    "調べる",
    "決める",
    "進める",
    "作る",
    "公開する",
    "振り返る",
)
_CATALOG_PATH: Final[Path] = Path("docs/skill-catalog.md")


def _description_summary(description: str) -> str:
    normalized = " ".join(description.split())
    first, separator, _remainder = normalized.partition("。")
    return first + separator


def render_catalog(inventory: SkillInventory) -> str:
    """Render a deterministic Markdown catalog from skill frontmatter."""
    groups: dict[str, list[tuple[str, str]]] = {purpose: [] for purpose in _PURPOSE_ORDER}
    for skill_dir in inventory.skill_directories():
        frontmatter = inventory.frontmatter(skill_dir.name)
        if not isinstance(frontmatter, dict):
            raise ValueError(f"{skill_dir.name}: frontmatter が dict ではありません")
        name = frontmatter.get("name")
        description = frontmatter.get("description")
        purpose = frontmatter.get("purpose")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{skill_dir.name}: name が非空文字列ではありません")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{skill_dir.name}: description が非空文字列ではありません")
        if not isinstance(purpose, str) or purpose not in groups:
            raise ValueError(f"{skill_dir.name}: purpose が7語分類に含まれません: {purpose}")
        groups[purpose].append((name, _description_summary(description)))

    lines = [
        "# Skill catalog",
        "",
        "<!-- `uv run yt-skills catalog` により生成。手で編集しないでください。 -->",
        "",
        "PDCA 対応: 準備 = 準備する / Plan = 調べる → 決める / Do = 進める → 作る → 公開する / Check / Act = 振り返る",
        "",
    ]
    for purpose in _PURPOSE_ORDER:
        lines.extend((f"## {purpose}", ""))
        lines.extend(f"- `/{name}` — {summary}" for name, summary in sorted(groups[purpose]))
        lines.append("")
    return "\n".join(lines)


def _catalog_diff(actual: str, expected: str) -> str:
    return "".join(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=str(_CATALOG_PATH),
            tofile=f"generated:{_CATALOG_PATH}",
        )
    )


def cmd_catalog(args: argparse.Namespace) -> int:
    """Generate the catalog, or verify that the checked-in catalog is current."""
    from youtube_automation.commands.system.skills_sync import _asset_root, _editable_root

    inventory = SkillInventory(_asset_root("skills"))
    expected = render_catalog(inventory)
    output_path = _editable_root() / _CATALOG_PATH

    if args.check:
        actual = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
        if actual != expected:
            print(_catalog_diff(actual, expected), end="")
            return 1
        print(f"skill catalog は最新です: {_CATALOG_PATH}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(expected, encoding="utf-8")
    print(f"skill catalog を生成しました: {_CATALOG_PATH}")
    return 0
