#!/usr/bin/env python3
"""[Deprecated / historical] テーマ単位のみのタイムスタンプ書き戻しスクリプト.

`TARGET_COLLECTIONS` にハードコードされた 2026-03/04 のコレクション群を対象に、
`## Complete Collection 概要欄` のタイムスタンプ行をパターン単位（テーマのみ）に
書き換える単発移行スクリプト。3 秒固定クロスフェード（CROSSFADE_SEC）も pipeline
本流（masterup 1.0 秒）と異なる固有値で、純粋に当時の状態を再現するためのもの。

**現行フォーマット（概要欄タイムスタンプ）は「テーマ見出し + 個別楽曲」が正となり、
本スクリプトが出力する「テーマ単位のみ」フォーマットは廃止された**。
新規コレクションには `metadata_generator.generate_timestamps()` /
`format_timestamps_text()`（テーマ見出し付き楽曲単位）を使うこと。

本スクリプトは過去の生成結果を再現する用途でのみ残置している。新規追加・呼び出し
増設は行わない。CLI entry `yt-fix-timestamps` も互換のために維持しているのみ。

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

from youtube_automation.utils.config import channel_dir

CROSSFADE_SEC = 3
COLLECTIONS_DIR = channel_dir() / "collections" / "live"

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
            "--",
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


def compute_pattern_starts(music_dir: Path, patterns: dict[str, str]) -> list[tuple[str, int]]:
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
            raise RuntimeError(f"pattern letter '{letter}' not in suno-prompts.md patterns ({sorted(patterns)})")
        result.append((patterns[letter], start_sec))
    return result


def replace_timestamps_in_description(descriptions_md: Path, new_lines: list[str]) -> str:
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
