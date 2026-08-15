"""Provider-neutral inventory and parsing for distributed skill documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_FRONTMATTER_DELIMITER = "---"
_DESCRIPTION_DOUBLE_QUOTED = re.compile(r'^description:\s*"', re.MULTILINE)
_MARKDOWN_HEADING = re.compile(r"^(?P<marks>#{1,6})\s+\S")


def extract_frontmatter(text: str) -> str:
    """Return the YAML frontmatter block from a SKILL.md document."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        raise ValueError("SKILL.md が frontmatter デリミタ '---' で始まっていません")
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONTMATTER_DELIMITER:
            return "\n".join(lines[1:index])
    raise ValueError("frontmatter の閉じデリミタ '---' が見つかりません")


def parse_frontmatter(text: str) -> object:
    """Parse SKILL.md frontmatter with strict YAML semantics."""
    return _parse_frontmatter_block(extract_frontmatter(text))


def _parse_frontmatter_block(frontmatter: str) -> object:
    return yaml.safe_load(frontmatter)


def lint_frontmatter_text(text: str) -> list[str]:
    """Return frontmatter contract violations for one SKILL.md document."""
    try:
        frontmatter = extract_frontmatter(text)
        parsed = _parse_frontmatter_block(frontmatter)
    except ValueError as exc:
        return [str(exc)]
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
    """Return frontmatter contract violations for one skill directory."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return ["SKILL.md がありません"]
    return lint_frontmatter_text(skill_md.read_text(encoding="utf-8"))


def extract_markdown_section(text: str, heading: str) -> str:
    """Return the body below an exact heading through the next peer heading."""
    heading_match = _MARKDOWN_HEADING.match(heading)
    if heading_match is None:
        raise ValueError(f"Markdown 見出しではありません: {heading}")
    target_level = len(heading_match.group("marks"))
    lines = text.splitlines(keepends=True)
    start: int | None = None
    for index, line in enumerate(lines):
        if line.rstrip("\r\n") == heading:
            start = index + 1
            break
    if start is None:
        raise ValueError(f"`{heading}` セクションが見つかりません")

    end = len(lines)
    for index in range(start, len(lines)):
        match = _MARKDOWN_HEADING.match(lines[index])
        if match is not None and len(match.group("marks")) <= target_level:
            end = index
            break
    return "".join(lines[start:end])


@dataclass(frozen=True, slots=True)
class SkillInventory:
    """Query skill documents from a repository or an installed asset root."""

    root: Path

    @property
    def skills_root(self) -> Path:
        repository_skills = self.root / ".claude" / "skills"
        return repository_skills if repository_skills.is_dir() else self.root

    def skill_directories(self) -> tuple[Path, ...]:
        """List immediate skill directories while excluding nested worktree stores."""
        if not self.skills_root.is_dir():
            return ()
        directories = (
            path for path in self.skills_root.iterdir() if path.is_dir() and not self._is_worktree_store_entry(path)
        )
        return tuple(sorted(directories, key=lambda path: path.name))

    def skill_directory(self, skill: str) -> Path:
        """Resolve one skill directory from its inventory name."""
        return self.skills_root / skill

    def frontmatter(self, skill: str) -> object:
        """Read and parse one skill's frontmatter."""
        text = (self.skill_directory(skill) / "SKILL.md").read_text(encoding="utf-8")
        return parse_frontmatter(text)

    def section(self, skill: str, heading: str) -> str:
        """Read one skill and extract an exact Markdown heading section."""
        text = (self.skill_directory(skill) / "SKILL.md").read_text(encoding="utf-8")
        return extract_markdown_section(text, heading)

    def resolve_reference(self, skill: str, reference: str) -> Path:
        """Resolve a local reference path relative to its skill directory."""
        path_text = reference.split("#", maxsplit=1)[0]
        if not path_text:
            raise ValueError("reference path が空です")
        path = Path(path_text)
        if path.is_absolute():
            raise ValueError(f"reference path は相対パスである必要があります: {reference}")
        return (self.skill_directory(skill) / path).resolve()

    def reference_exists(self, skill: str, reference: str) -> bool:
        """Return whether a resolved skill reference points to a file."""
        return self.resolve_reference(skill, reference).is_file()

    def _is_worktree_store_entry(self, path: Path) -> bool:
        relative = path.relative_to(self.skills_root)
        if relative.parts[0] == ".worktrees":
            return True
        return relative.parts[0] == ".claude" and (path / "worktrees").is_dir()
