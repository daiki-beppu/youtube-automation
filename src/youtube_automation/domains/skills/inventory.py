"""Provider-neutral inventory and parsing for distributed skill documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

_FRONTMATTER_DELIMITER = "---"
_DESCRIPTION_DOUBLE_QUOTED = re.compile(r'^description:\s*"', re.MULTILINE)
_MARKDOWN_HEADING = re.compile(r"^(?P<marks>#{1,6})\s+\S")
_DESCRIPTION_FLAG = re.compile(r"(?<![\w-])--[a-z0-9]+(?:-[a-z0-9]+)*(?![a-z0-9-])")
_QUALIFIED_SKILL_ROUTE_BEFORE_FLAG = re.compile(r"/[a-z0-9]+(?:-[a-z0-9]+)*\s+$")
_VALUE_PLACEHOLDER = re.compile(r"\s*<[^>\n]+>")
_TABLE_FLAG = re.compile(r"^`(?P<flag>--[a-z0-9]+(?:-[a-z0-9]+)*)`$")
_TABLE_REFERENCE = re.compile(r"^`(?P<reference>[^`]+)`$")
_MODE_HEADING = "## モード判定"
_MODIFIER_HEADING = "## 修飾フラグ"
_ARTIFACTS_HEADING = "## 成果物"
_MAX_MODES = 5
_PURPOSE_VALUES: Final[frozenset[str]] = frozenset(
    {"準備する", "調べる", "決める", "進める", "作る", "公開する", "振り返る"}
)


@dataclass(frozen=True, slots=True)
class SkillLintViolation:
    """One categorized skill lint violation."""

    identifier: str
    message: str


@dataclass(frozen=True, slots=True)
class ArtifactDeclaration:
    """Files one skill declares as written and read."""

    writes: tuple[str, ...]
    reads: tuple[str, ...]


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

    if "purpose" not in parsed:
        violations.append("frontmatter に 'purpose' がありません")
    elif not isinstance(parsed["purpose"], str):
        violations.append("'purpose' は単一の文字列で指定してください")
    elif parsed["purpose"] not in _PURPOSE_VALUES:
        allowed = ", ".join(sorted(_PURPOSE_VALUES))
        violations.append(f"'purpose' が許容値ではありません: {parsed['purpose']} (許容値: {allowed})")
    return violations


def lint_skill(skill_dir: Path) -> list[str]:
    """Return skill contract violation messages for one skill directory."""
    return [violation.message for violation in lint_skill_contract(skill_dir)]


def lint_skill_contract(skill_dir: Path) -> list[SkillLintViolation]:
    """Return categorized contract violations for one skill directory."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [SkillLintViolation("skill_md_missing", "SKILL.md がありません")]

    text = skill_md.read_text(encoding="utf-8")
    frontmatter_violations = lint_frontmatter_text(text)
    if frontmatter_violations:
        return [SkillLintViolation("frontmatter", message) for message in frontmatter_violations]

    parsed = parse_frontmatter(text)
    if not isinstance(parsed, dict) or not isinstance(parsed["description"], str):
        raise AssertionError("lint_frontmatter_text accepted an invalid frontmatter shape")
    violations = _lint_artifact_contract(text)
    violations.extend(_lint_flag_contract(skill_dir, text, parsed["description"]))
    return violations


def _lint_artifact_contract(text: str) -> list[SkillLintViolation]:
    section = _optional_markdown_section(text, _ARTIFACTS_HEADING)
    if section is None:
        return [SkillLintViolation("artifacts_section_missing", "`## 成果物` ブロックがありません")]
    if _artifact_line(section, "書き込む") is None:
        return [SkillLintViolation("artifact_writes_missing", "`## 成果物` に `書き込む` 行がありません")]
    return []


def _artifact_line(section: str, label: str) -> str | None:
    prefix = f"- `{label}`:"
    for line in section.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _artifact_paths(section: str, label: str, *, required: bool = True) -> tuple[str, ...]:
    value = _artifact_line(section, label)
    if value is None:
        if required:
            raise ValueError(f"`## 成果物` に `{label}` 行がありません")
        return ()
    paths = tuple(re.findall(r"`([^`]+)`", value))
    return () if paths == ("なし",) else paths


def _lint_flag_contract(skill_dir: Path, text: str, description: str) -> list[SkillLintViolation]:
    description_flags = _extract_description_flags(description)
    mode_section = _optional_markdown_section(text, _MODE_HEADING)
    modifier_section = _optional_markdown_section(text, _MODIFIER_HEADING)

    if description_flags and mode_section is None and modifier_section is None:
        return [
            SkillLintViolation(
                "flag_tables_missing",
                "description に値なしフラグがありますが、## モード判定 / ## 修飾フラグの表がありません",
            )
        ]

    mode_entries = _extract_mode_entries(mode_section)
    mode_rows = tuple(flag for flag, _reference in mode_entries)
    modifier_rows = _extract_table_flags(modifier_section, ("modifier", "効果"))
    mode_flags = set(mode_rows)
    modifier_flags = set(modifier_rows)
    violations: list[SkillLintViolation] = []

    for flag in sorted(description_flags - mode_flags - modifier_flags):
        violations.append(
            SkillLintViolation(
                "description_flag_unregistered",
                f"description の {flag} がモード判定表にも修飾フラグ表にも未登録です",
            )
        )
    for flag in sorted(mode_flags & modifier_flags):
        violations.append(
            SkillLintViolation(
                "flag_membership_duplicate",
                f"{flag} がモード判定表と修飾フラグ表に重複所属しています",
            )
        )
    if len(mode_rows) > _MAX_MODES:
        violations.append(
            SkillLintViolation(
                "mode_limit_exceeded",
                f"mode は {_MAX_MODES} 個以下にしてください (現在: {len(mode_rows)} 個)",
            )
        )
    if mode_section is not None and not _states_exclusive_stop(mode_section):
        violations.append(
            SkillLintViolation(
                "mode_exclusivity_missing",
                "## モード判定に、2 個以上の同時指定を停止する旨がありません",
            )
        )
    violations.extend(_lint_mode_references(skill_dir, mode_entries))
    return violations


def _extract_description_flags(description: str) -> set[str]:
    flags: set[str] = set()
    for match in _DESCRIPTION_FLAG.finditer(description):
        if _QUALIFIED_SKILL_ROUTE_BEFORE_FLAG.search(description[: match.start()]) is not None:
            continue
        if _VALUE_PLACEHOLDER.match(description, match.end()) is None:
            flags.add(match.group())
    return flags


def _optional_markdown_section(text: str, heading: str) -> str | None:
    try:
        return extract_markdown_section(text, heading)
    except ValueError:
        return None


def _extract_table_flags(section: str | None, expected_header: tuple[str, str]) -> tuple[str, ...]:
    return tuple(flag for flag, _value in _extract_table_rows(section, expected_header))


def _extract_mode_entries(section: str | None) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    for flag, value in _extract_table_rows(section, ("mode", "読む reference")):
        match = _TABLE_REFERENCE.fullmatch(value)
        entries.append((flag, match.group("reference") if match is not None else value))
    return tuple(entries)


def _extract_table_rows(section: str | None, expected_header: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    if section is None:
        return ()
    lines = [line.strip() for line in section.splitlines()]
    header = f"| {expected_header[0]} | {expected_header[1]} |"
    try:
        header_index = lines.index(header)
    except ValueError:
        return ()

    rows: list[tuple[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        match = _TABLE_FLAG.fullmatch(cells[0])
        if match is not None:
            rows.append((match.group("flag"), cells[1]))
    return tuple(rows)


def _lint_mode_references(skill_dir: Path, mode_entries: tuple[tuple[str, str], ...]) -> list[SkillLintViolation]:
    violations: list[SkillLintViolation] = []
    modes_by_reference: dict[str, list[str]] = {}

    for flag, reference in mode_entries:
        modes_by_reference.setdefault(reference, []).append(flag)
        expected = f"references/{flag.removeprefix('--')}.md"
        if Path(reference).is_absolute():
            violations.append(
                SkillLintViolation(
                    "mode_reference_not_relative",
                    f"{flag} の reference は skill ディレクトリからの相対パスで書いてください: {reference}",
                )
            )
        elif not (skill_dir / reference).is_file():
            violations.append(
                SkillLintViolation(
                    "mode_reference_missing",
                    f"{flag} の reference が見つかりません: {reference}",
                )
            )
        if reference != expected:
            violations.append(
                SkillLintViolation(
                    "mode_reference_name_mismatch",
                    f"{flag} の reference がフラグ名と一致しません: {reference} (期待: {expected})",
                )
            )

    for reference, flags in modes_by_reference.items():
        if len(flags) > 1:
            violations.append(
                SkillLintViolation(
                    "mode_reference_shared",
                    f"mode ごとに別の reference が必要です: {', '.join(flags)} が {reference} を共有しています",
                )
            )
    return violations


def _states_exclusive_stop(section: str) -> bool:
    compact = re.sub(r"\s+", "", section)
    return "2個以上" in compact and "停止" in compact


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

    def artifacts(self, skill: str) -> ArtifactDeclaration:
        """Read one skill's declared artifact writes and reads."""
        section = self.section(skill, _ARTIFACTS_HEADING)
        return ArtifactDeclaration(
            writes=_artifact_paths(section, "書き込む"),
            reads=_artifact_paths(section, "読み込む", required=False),
        )

    def _is_worktree_store_entry(self, path: Path) -> bool:
        relative = path.relative_to(self.skills_root)
        if relative.parts[0] == ".worktrees":
            return True
        return relative.parts[0] == ".claude" and (path / "worktrees").is_dir()
