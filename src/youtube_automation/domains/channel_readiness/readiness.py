"""Pure TTP exception policy and channel readiness result contract."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessResult:
    status: str
    message: str
    next_action: dict[str, object] | None = None


def _line_mentions_ttp_skip(line: str) -> bool:
    lower_line = line.lower()
    if "スキップ" in line or "skip" in lower_line:
        return True
    if "未反映" not in line and "未適用" not in line:
        return False
    return not _line_declares_no_unapplied_items(line)


def _line_declares_no_unapplied_items(line: str) -> bool:
    lower_line = line.lower()
    return ("なし" in line or "none" in lower_line) and "ただし" not in line and "but" not in lower_line


def _line_mentions_approved_exception(line: str) -> bool:
    lower_line = line.lower()
    return "ユーザー承認済み例外" in line or "approved exception" in lower_line


def approved_ttp_exceptions(seed_text: str) -> tuple[set[str], list[str]]:
    return _validate_approved_ttp_exception_blocks(_approved_ttp_exception_blocks(seed_text))


def _approved_ttp_exception_blocks(seed_text: str) -> list[tuple[str, set[int]]]:
    lines = seed_text.splitlines()
    blocks: list[tuple[str, set[int]]] = []
    for line_number, line in enumerate(lines):
        if not _line_mentions_approved_exception(line):
            continue
        heading_match = re.match(r"^\s*(#{1,6})\s+", line)
        if not heading_match:
            blocks.append((line, {line_number}))
            continue

        heading_level = len(heading_match.group(1))
        block_lines = [line]
        block_line_numbers = {line_number}
        for following_number in range(line_number + 1, len(lines)):
            following_line = lines[following_number]
            following_heading = re.match(r"^\s*(#{1,6})\s+", following_line)
            if following_heading and len(following_heading.group(1)) <= heading_level:
                break
            block_lines.append(following_line)
            block_line_numbers.add(following_number)
        blocks.append(("\n".join(block_lines), block_line_numbers))
    return blocks


def _approved_exception_error(block: str, categories: set[str]) -> str | None:
    """Return the first missing approval requirement in its established priority order."""
    lower_block = block.lower()
    if not categories:
        return "ユーザー承認済み例外に対象 category が未記録"
    if not any(_line_mentions_ttp_skip(line) for line in block.splitlines()):
        return "ユーザー承認済み例外に具体的な未反映 / スキップ内容が未記録"
    if not _approved_exception_has_reason(block):
        return "ユーザー承認済み例外に進める理由が未記録"
    if "thumbnail" in categories and "/thumbnail" not in lower_block:
        return "thumbnail のユーザー承認済み例外に後続 /thumbnail が未記録"
    if "music" in categories and "/music --prompt" not in lower_block:
        return "music のユーザー承認済み例外に後続 /music --prompt が未記録"
    if "duration" in categories and not any(
        command in lower_block for command in ("/benchmark", "/channel-research --benchmark")
    ):
        return "duration のユーザー承認済み例外に後続 /channel-research --benchmark が未記録"

    return None


def _validate_approved_ttp_exception_blocks(
    blocks: list[tuple[str, set[int]]],
) -> tuple[set[str], list[str]]:
    exceptions: set[str] = set()
    missing: list[str] = []
    for block, _ in blocks:
        lower_block = block.lower()
        categories: set[str] = set()
        if "thumbnail" in lower_block or "サムネ" in block:
            categories.add("thumbnail")
        if "music" in lower_block or "suno" in lower_block or "曲構造" in block or "音楽" in block:
            categories.add("music")
        if "duration" in lower_block or "動画尺" in block:
            categories.add("duration")

        error = _approved_exception_error(block, categories)
        if error is not None:
            missing.append(error)
            continue

        exceptions.update(categories)
    return exceptions, missing


def _approved_exception_has_reason(line: str) -> bool:
    lower_line = line.lower()
    return "ため" in line or "理由" in line or "because" in lower_line or "進める" in line
