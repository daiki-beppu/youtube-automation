"""Hatch build hook for selecting downstream-distributed skills."""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Map production skills individually so development-only skills stay upstream."""

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        del version
        skills_root = Path(self.root) / ".claude" / "skills"
        dev_only = frozenset(self.config["dev-only-skills"])
        destination_root = "youtube_automation/_skills" if self.target_name == "wheel" else ".claude/skills"
        force_include = build_data["force_include"]
        assert isinstance(force_include, dict)

        for skill_dir in sorted(skills_root.iterdir()):
            if skill_dir.is_dir() and skill_dir.name not in dev_only:
                force_include[str(skill_dir)] = f"{destination_root}/{skill_dir.name}"
