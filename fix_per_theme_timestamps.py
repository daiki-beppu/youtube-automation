#!/usr/bin/env python3
"""Fix per-variation timestamp regression in descriptions.md.

For each collection in TARGET_COLLECTIONS, rewrite the
"## Complete Collection 概要欄" code block so that the timestamp
section has one chapter per pattern (theme) instead of one chapter
per variation (v1〜v6).

Steps per collection:
1. Read pattern names from suno-prompts.md (## Pattern X: 日本語 — English Name)
2. List 02-Individual-music/*.mp3 in lexicographic order
3. Extract pattern letter (a/b/c/d) from filename like 'XX-pattern-Y-...'
4. Compute each track's master-timeline start with 3-second crossfade
5. For each pattern, take the start time of its first track
6. Replace the existing timestamp lines (those matching ^\\d{1,2}:\\d{2})
   with the new per-theme lines while preserving surrounding text.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

CROSSFADE_SEC = 3
ROOT = Path(__file__).resolve().parent.parent
COLLECTIONS_DIR = ROOT / "collections" / "live"

TARGET_COLLECTIONS = [
    "20260328-rjn-last-platform-collection",
    "20260330-rjn-rainy-studio-collection",
    "20260331-rjn-dorm-window-collection",
    "20260331-rjn-library-after-hours-collection",
    "20260401-rjn-rain-nest-collection",
    "20260404-rjn-empty-gallery-collection",
    "20260404-rjn-parking-garage-collection",
]


def parse_patterns(suno_prompts_md: Path) -> dict[str, str]:
    """Return {'a': 'After the Last Visitor', 'b': '...', ...}"""
    text = suno_prompts_md.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(
        r"^## Pattern ([A-D]):\s*[^—]+—\s*([^\[\n]+?)\s*\[",
        text,
        flags=re.MULTILINE,
    ):
        letter = m.group(1).lower()
        name = m.group(2).strip()
        out[letter] = name
    return out


def get_duration(mp3: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(mp3),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def fmt_timestamp(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def compute_pattern_starts(
    music_dir: Path, patterns: dict[str, str]
) -> list[tuple[str, int]]:
    """Return list of (pattern_name_en, start_seconds) ordered by appearance."""
    files = sorted(p for p in music_dir.glob("*.mp3"))
    if not files:
        raise RuntimeError(f"no mp3 in {music_dir}")

    cumulative = 0.0
    seen: dict[str, int] = {}  # pattern letter → first start_sec
    file_letter_re = re.compile(r"^\d+-pattern-([a-d])\b", re.IGNORECASE)

    for idx, f in enumerate(files):
        m = file_letter_re.match(f.name)
        if not m:
            raise RuntimeError(f"unexpected file name: {f.name}")
        letter = m.group(1).lower()
        # start time of this track in master = cumulative
        if letter not in seen:
            seen[letter] = int(round(cumulative))
        dur = get_duration(f)
        cumulative += dur
        if idx < len(files) - 1:
            cumulative -= CROSSFADE_SEC  # next track overlaps by 3s

    # order patterns by their first appearance
    ordered = sorted(seen.items(), key=lambda kv: kv[1])
    result = []
    for letter, start_sec in ordered:
        if letter not in patterns:
            raise RuntimeError(
                f"pattern letter '{letter}' not in suno-prompts.md patterns "
                f"({sorted(patterns)})"
            )
        result.append((patterns[letter], start_sec))
    return result


def replace_timestamps_in_description(
    descriptions_md: Path, new_lines: list[str]
) -> str:
    """Return new content of descriptions.md with timestamps replaced.

    Strategy: locate the ``` fenced block right after
    '## Complete Collection 概要欄'. Within it, find the contiguous
    run of lines matching ^\\d{1,2}:\\d{2} and replace it with new_lines.
    """
    text = descriptions_md.read_text(encoding="utf-8")
    fence_re = re.compile(
        r"(## Complete Collection 概要欄\s*\n+```\n)(.*?)(```)",
        re.DOTALL,
    )
    m = fence_re.search(text)
    if not m:
        raise RuntimeError(f"no Complete Collection fence in {descriptions_md}")

    body = m.group(2)
    lines = body.split("\n")
    ts_re = re.compile(r"^\d{1,2}:\d{2}")
    start = end = None
    for i, line in enumerate(lines):
        if ts_re.match(line.strip()):
            if start is None:
                start = i
            end = i
        elif start is not None and end is not None and i > end:
            # contiguous run ended
            break
    if start is None:
        raise RuntimeError(f"no timestamp lines in {descriptions_md}")

    new_body_lines = lines[:start] + new_lines + lines[end + 1 :]
    new_body = "\n".join(new_body_lines)
    return text[: m.start(2)] + new_body + text[m.end(2) :]


def process(collection: str, *, dry_run: bool) -> None:
    col_dir = COLLECTIONS_DIR / collection
    suno = col_dir / "20-documentation" / "suno-prompts.md"
    music = col_dir / "02-Individual-music"
    desc = col_dir / "20-documentation" / "descriptions.md"
    if not (suno.exists() and music.exists() and desc.exists()):
        print(f"  ✗ skip (missing files): {collection}")
        return

    patterns = parse_patterns(suno)
    pattern_starts = compute_pattern_starts(music, patterns)

    new_lines = [f"{fmt_timestamp(s)} {name}" for name, s in pattern_starts]

    print(f"\n=== {collection} ===")
    for line in new_lines:
        print(f"  {line}")

    new_text = replace_timestamps_in_description(desc, new_lines)
    if dry_run:
        return
    desc.write_text(new_text, encoding="utf-8")
    print("  ✅ wrote")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--only",
        help="comma-separated substring filter, e.g. 'empty-gallery'",
    )
    args = p.parse_args()

    targets = TARGET_COLLECTIONS
    if args.only:
        substrs = [s.strip() for s in args.only.split(",") if s.strip()]
        targets = [c for c in targets if any(s in c for s in substrs)]

    for col in targets:
        try:
            process(col, dry_run=args.dry_run)
        except Exception as e:
            print(f"  ❌ {col}: {e}")


if __name__ == "__main__":
    main()
