"""Skill delegation graph parsing, cycle detection, and reporting."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass

from youtube_automation.domains.skills.inventory import SkillInventory

_DECLARATION = re.compile(r"^- `委譲先`:\s*(?P<value>.+)$", re.MULTILINE)
_SKILL_REFERENCE = re.compile(r"`/(?P<name>[a-z][a-z0-9-]*)`")


@dataclass(frozen=True, slots=True)
class DelegationGraph:
    """Delegation declarations loaded from one skill inventory."""

    edges: dict[str, tuple[str, ...]]
    missing: tuple[str, ...]

    @classmethod
    def load(cls, inventory: SkillInventory) -> DelegationGraph:
        edges: dict[str, tuple[str, ...]] = {}
        missing: list[str] = []
        for skill_dir in inventory.skill_directories():
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                missing.append(skill_dir.name)
                edges[skill_dir.name] = ()
                continue
            match = _DECLARATION.search(skill_md.read_text(encoding="utf-8"))
            if match is None:
                missing.append(skill_dir.name)
                edges[skill_dir.name] = ()
                continue
            edges[skill_dir.name] = tuple(
                dict.fromkeys(reference.group("name") for reference in _SKILL_REFERENCE.finditer(match.group("value")))
            )
        return cls(edges=edges, missing=tuple(missing))

    def cycles(self) -> tuple[tuple[str, ...], ...]:
        """Return each directed cycle once, with a repeated closing node."""
        found: set[tuple[str, ...]] = set()

        def visit(node: str, path: tuple[str, ...]) -> None:
            for target in self.edges.get(node, ()):
                if target not in self.edges:
                    continue
                if target in path:
                    cycle = path[path.index(target) :]
                    rotations = tuple(cycle[index:] + cycle[:index] for index in range(len(cycle)))
                    canonical = min(rotations)
                    found.add((*canonical, canonical[0]))
                    continue
                visit(target, (*path, target))

        for skill in sorted(self.edges):
            visit(skill, (skill,))
        return tuple(sorted(found))

    def longest_path(self, skill: str) -> tuple[str, ...]:
        """Return a deterministic longest simple path beginning at ``skill``."""

        def walk(node: str, visited: frozenset[str]) -> tuple[str, ...]:
            candidates = []
            for target in self.edges.get(node, ()):
                if target in visited:
                    candidates.append((target,))
                else:
                    candidates.append((target, *walk(target, visited | {target})))
            return max(candidates, key=len, default=())

        return (skill, *walk(skill, frozenset({skill})))


def format_path(path: tuple[str, ...]) -> str:
    return " -> ".join(f"/{skill}" for skill in path)


def cmd_delegation(_args: argparse.Namespace) -> int:
    """Print delegation depths for every bundled skill."""
    from youtube_automation.commands.system.skills_sync import _asset_root

    graph = DelegationGraph.load(SkillInventory(_asset_root("skills")))
    rows = [(skill, graph.longest_path(skill)) for skill in sorted(graph.edges)]
    name_width = max((len("skill"), *(len(skill) for skill, _path in rows)))
    print(f"{'skill':<{name_width}}  深さ  経路")
    for skill, path in rows:
        print(f"{skill:<{name_width}}  {len(path) - 1:>4}  {format_path(path)}")
    maximum = max((len(path) - 1 for _skill, path in rows), default=0)
    delegated = sum(bool(targets) for targets in graph.edges.values())
    print(f"最大深さ: {maximum} / 委譲を持つ skill: {delegated} 件 / 循環: {len(graph.cycles())} 件")
    return 0
