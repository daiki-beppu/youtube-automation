#!/usr/bin/env python3
"""suno-lyrics.json の曲間セクション重複を検出する（/suno-lyric の Validation 用）。

複数曲の vocal collection で `[Intro]` `[Pre-Chorus]` `[Bridge]` `[Extended Outro]` `[Outro]`
などのセクション本文が曲間で一言一句同一になっていないかを機械的に確認する。
同一曲内での `[Chorus]` / `[Final Chorus]` の反復は正常な曲構成として扱い、検出しない。

比較は正規化（小文字化 + 空白の畳み込み）後の完全一致のみ。言い換えによる
ニアミス重複はセルフチェック（SKILL.md::Validation）で人間 / Claude が確認する。

Usage:
    python check_lyric_duplication.py <collection>/20-documentation/suno-lyrics.json

Exit codes:
    0: 曲間重複なし
    1: 曲間重複あり（出力を完了扱いにせず、該当セクションを書き分け直す）
    2: 入力ファイルの読み込み・形式エラー
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_automation.utils.suno_lyrics import SunoLyricsEntry

SECTION_TAG_RE = re.compile(r"^\[([^\]]+)\]\s*$")
DEFAULT_TARGET_SECTIONS = ("Intro", "Pre-Chorus", "Bridge", "Extended Outro", "Outro")


def ensure_repo_src_on_path() -> None:
    for parent in Path(__file__).resolve().parents:
        src_dir = parent / "src"
        if (src_dir / "youtube_automation").is_dir():
            sys.path.insert(0, str(src_dir))
            return


def load_entries(path: Path) -> list[SunoLyricsEntry]:
    ensure_repo_src_on_path()
    from youtube_automation.utils.exceptions import ConfigError
    from youtube_automation.utils.suno_lyrics import load_suno_lyrics_entries

    try:
        return load_suno_lyrics_entries(path)
    except ConfigError as error:
        raise ValueError(str(error)) from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="suno-lyrics.json のセクション本文が曲間で完全一致していないか検出する。"
    )
    parser.add_argument(
        "lyrics_json",
        nargs="?",
        default="20-documentation/suno-lyrics.json",
        help="suno-lyrics.json のパス（default: 20-documentation/suno-lyrics.json）",
    )
    parser.add_argument(
        "--sections",
        default=None,
        help=("検査対象セクション名のカンマ区切り（default: 'Intro,Pre-Chorus,Bridge,Extended Outro,Outro'）"),
    )
    return parser.parse_args()


def normalize_body(lines: list[str]) -> str:
    """本文行を比較用に正規化する（小文字化 + 行内空白の畳み込み + 空行除去）。"""
    normalized = [" ".join(line.split()).lower() for line in lines]
    return "\n".join(line for line in normalized if line)


def split_sections(lyrics: str) -> list[tuple[str, str]]:
    """歌詞テキストを (セクション名, 正規化済み本文) のリストに分解する。"""
    sections: list[tuple[str, str]] = []
    current_tag: str | None = None
    current_lines: list[str] = []
    for line in lyrics.splitlines():
        match = SECTION_TAG_RE.match(line.strip())
        if match:
            if current_tag is not None:
                sections.append((current_tag, normalize_body(current_lines)))
            current_tag = match.group(1).strip()
            current_lines = []
        elif current_tag is not None:
            current_lines.append(line)
    if current_tag is not None:
        sections.append((current_tag, normalize_body(current_lines)))
    return sections


def parse_target_sections(raw_sections: str | None) -> set[str]:
    sections = raw_sections.split(",") if raw_sections is not None else DEFAULT_TARGET_SECTIONS
    target_sections = {section.strip().lower() for section in sections if section.strip()}
    if not target_sections:
        raise ValueError("--sections には 1 件以上の section 名を指定してください")
    return target_sections


def find_cross_song_duplicates(entries: list[SunoLyricsEntry], target_sections: set[str]) -> list[dict]:
    """正規化本文が複数の曲に現れるグループを列挙する。

    グルーピングはセクション名ではなく本文で行う。これにより、ある曲の
    [Intro] と別の曲の [Outro] が同一、といったクロスタグ重複も検出できる。
    同一曲内の反復（Chorus 等）は曲名集合のサイズが 1 になるため除外される。
    """
    body_to_occurrences: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for entry in entries:
        for tag, body in split_sections(entry.lyrics):
            if not body:
                continue
            if tag.lower() not in target_sections:
                continue
            body_to_occurrences[body].append((entry.name, tag))

    duplicates = []
    for body, occurrences in body_to_occurrences.items():
        songs = sorted({name for name, _ in occurrences})
        if len(songs) < 2:
            continue
        tags = sorted({tag for _, tag in occurrences})
        duplicates.append({"body": body, "songs": songs, "tags": tags})
    duplicates.sort(key=lambda d: (-len(d["songs"]), d["body"]))
    return duplicates


def main() -> int:
    args = parse_args()
    path = Path(args.lyrics_json)
    try:
        entries = load_entries(path)
    except OSError as error:
        print(f"NG: {path} を読み込めません: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"NG: {error}", file=sys.stderr)
        return 2

    try:
        target_sections = parse_target_sections(args.sections)
    except ValueError as error:
        print(f"NG: {error}", file=sys.stderr)
        return 2
    duplicates = find_cross_song_duplicates(entries, target_sections)
    if not duplicates:
        print(f"OK: 曲間のセクション重複なし（{len(entries)} 曲、対象セクション {sorted(target_sections)}）")
        return 0

    print(f"NG: 曲間でセクション本文が完全一致するグループを {len(duplicates)} 件検出しました")
    for index, dup in enumerate(duplicates, start=1):
        first_line = dup["body"].splitlines()[0]
        tags = ", ".join(f"[{tag}]" for tag in dup["tags"])
        print(f"\n[{index}] {tags} — {len(dup['songs'])} 曲で同一")
        print(f"    text: {first_line} ...")
        shown = dup["songs"][:5]
        rest = len(dup["songs"]) - len(shown)
        suffix = f" ほか {rest} 曲" if rest > 0 else ""
        print(f"    songs: {', '.join(shown)}{suffix}")
    print(
        "\n該当セクションを曲ごとの scene / persona に合わせて書き分け直してから再実行してください"
        "（SKILL.md::Validation 参照）"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
