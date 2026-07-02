#!/usr/bin/env python3
"""suno-lyrics.json の曲間セクション重複を検出する（/suno-lyric の Validation 用）。

複数曲の vocal collection で `[Intro]` `[Pre-Chorus]` `[Bridge]` `[Extended Outro]`
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
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SECTION_TAG_RE = re.compile(r"^\[([^\]]+)\]\s*$")


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
        help="検査対象セクション名のカンマ区切り（例: 'Intro,Pre-Chorus,Bridge,Extended Outro'）。省略時は全セクション",
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


def find_cross_song_duplicates(entries: list[dict], target_sections: set[str] | None) -> list[dict]:
    """正規化本文が複数の曲に現れるグループを列挙する。

    グルーピングはセクション名ではなく本文で行う。これにより、ある曲の
    [Intro] と別の曲の [Outro] が同一、といったクロスタグ重複も検出できる。
    同一曲内の反復（Chorus 等）は曲名集合のサイズが 1 になるため除外される。
    """
    body_to_occurrences: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for entry in entries:
        name = entry.get("name", "(name 不明)")
        lyrics = entry.get("lyrics") or ""
        for tag, body in split_sections(lyrics):
            if not body:
                continue
            if target_sections is not None and tag.lower() not in target_sections:
                continue
            body_to_occurrences[body].append((name, tag))

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
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"NG: {path} を読み込めません: {error}", file=sys.stderr)
        return 2
    if not isinstance(entries, list):
        print(f"NG: {path} の root は配列である必要があります", file=sys.stderr)
        return 2

    target_sections: set[str] | None = None
    if args.sections:
        target_sections = {s.strip().lower() for s in args.sections.split(",") if s.strip()}

    duplicates = find_cross_song_duplicates(entries, target_sections)
    if not duplicates:
        scope = "全セクション" if target_sections is None else f"対象セクション {sorted(target_sections)}"
        print(f"OK: 曲間のセクション重複なし（{len(entries)} 曲、{scope}）")
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
