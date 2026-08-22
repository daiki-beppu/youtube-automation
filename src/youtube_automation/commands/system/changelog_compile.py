"""Compile changelog fragments into the Unreleased section."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import ConfigError

_SECTION_ORDER = (
    "added",
    "changed",
    "deprecated",
    "removed",
    "fixed",
    "security",
    "migration",
)
_SECTION_NAMES = {section: section.title() for section in _SECTION_ORDER}
_FRAGMENT_PATTERN = re.compile(rf"^.+\.(?P<type>{'|'.join(_SECTION_ORDER)})\.md$")


def _load_fragments(fragments_dir: Path) -> dict[str, list[tuple[Path, str]]]:
    grouped = {section: [] for section in _SECTION_ORDER}
    if not fragments_dir.exists():
        return grouped

    for path in sorted(fragments_dir.glob("*.md")):
        if path.name.casefold() == "readme.md":
            continue
        match = _FRAGMENT_PATTERN.fullmatch(path.name)
        if match is None:
            raise ConfigError(f"不正な changelog fragment ファイル名です: {path.name}")
        body = path.read_text(encoding="utf-8").strip()
        lines = [line for line in body.splitlines() if line.strip()]
        if not lines or any(not line.startswith("- ") for line in lines):
            raise ConfigError(f"changelog fragment は '- ' で始まる bullet で記述してください: {path.name}")
        grouped[match.group("type")].append((path, "\n".join(lines)))
    return grouped


def _unreleased_bounds(changelog: str) -> tuple[int, int]:
    header = re.search(r"^## \[Unreleased\]\s*$", changelog, re.MULTILINE)
    if header is None:
        raise ConfigError("CHANGELOG.md に ## [Unreleased] がありません")
    start = header.end()
    next_version = re.search(r"^## \[.+\].*$", changelog[start:], re.MULTILINE)
    end = start + next_version.start() if next_version else len(changelog)
    return start, end


def _append_to_section(unreleased: str, section_type: str, bullets: str) -> str:
    heading = f"### {_SECTION_NAMES[section_type]}"
    match = re.search(rf"^{re.escape(heading)}\s*$", unreleased, re.MULTILINE)
    if match is None:
        insert_at = len(unreleased.rstrip())
        wanted_index = _SECTION_ORDER.index(section_type)
        for later_type in _SECTION_ORDER[wanted_index + 1 :]:
            later = re.search(
                rf"^### {re.escape(_SECTION_NAMES[later_type])}\s*$",
                unreleased,
                re.MULTILINE,
            )
            if later is not None:
                insert_at = later.start()
                break
        block = f"{heading}\n\n"
        if section_type == "migration":
            block += "サマリ:\n\n"
        block += f"{bullets}\n\n"
        prefix = unreleased[:insert_at].rstrip()
        suffix = unreleased[insert_at:].lstrip("\n")
        return f"{prefix}\n\n{block}{suffix}"

    next_heading = re.search(r"^### .+$", unreleased[match.end() :], re.MULTILINE)
    section_end = match.end() + next_heading.start() if next_heading else len(unreleased)
    section = unreleased[match.end() : section_end]
    if section_type == "migration":
        summary = re.search(r"^サマリ:\s*$", section, re.MULTILINE)
        if summary is None:
            insertion = f"\n\nサマリ:\n\n{bullets}\n"
            section = section.rstrip() + insertion
        else:
            summary_end = summary.end()
            next_label = re.search(r"^[^\s#-].*:\s*$", section[summary_end:], re.MULTILINE)
            insertion_at = summary_end + (next_label.start() if next_label else len(section[summary_end:]))
            section = section[:insertion_at].rstrip() + f"\n\n{bullets}\n" + section[insertion_at:]
    else:
        section = section.rstrip() + f"\n\n{bullets}\n"
    return unreleased[: match.end()] + section + unreleased[section_end:]


def compile_fragments(changelog_path: Path, fragments_dir: Path, *, dry_run: bool = False) -> str | None:
    """Compile fragments and return the resulting CHANGELOG text, or None when empty."""
    grouped = _load_fragments(fragments_dir)
    fragment_paths = [path for entries in grouped.values() for path, _ in entries]
    if not fragment_paths:
        return None

    original = changelog_path.read_text(encoding="utf-8")
    start, end = _unreleased_bounds(original)
    unreleased = original[start:end]
    for section_type in _SECTION_ORDER:
        entries = grouped[section_type]
        if entries:
            unreleased = _append_to_section(
                unreleased,
                section_type,
                "\n".join(body for _, body in entries),
            )
    compiled = original[:start] + unreleased.rstrip() + "\n\n" + original[end:].lstrip("\n")
    if not dry_run:
        changelog_path.write_text(compiled, encoding="utf-8")
        for path in fragment_paths:
            path.unlink()
    return compiled


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="changelog fragments を [Unreleased] へ集約します")
    parser.add_argument("--dry-run", action="store_true", help="ファイルを変更せず集約後の内容を表示します")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"), help="CHANGELOG ファイルのパス")
    parser.add_argument("--fragments-dir", type=Path, default=Path("changelog.d"), help="fragment ディレクトリのパス")
    return parser


def run(args: argparse.Namespace) -> int:
    compiled = compile_fragments(args.changelog, args.fragments_dir, dry_run=args.dry_run)
    if compiled is None:
        print("no fragments")
    elif args.dry_run:
        print(compiled, end="")
    else:
        print("changelog fragments compiled")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="changelog fragment compile failed")


if __name__ == "__main__":
    raise SystemExit(main())
