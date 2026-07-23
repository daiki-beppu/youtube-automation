"""``yt-captions-upload`` — 歌詞 SRT の生成と YouTube 字幕アップロード。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from youtube_automation.domains.suno.lyrics import load_suno_lyrics_entries
from youtube_automation.utils.captions import (
    generate_srt,
    parse_timestamp,
    parse_total_duration,
    parse_track_timestamps,
    upload_caption,
    write_srt,
)
from youtube_automation.utils.exceptions import AutomationError, ValidationError
from youtube_automation.utils.youtube_service import get_youtube


def _load_lyrics(path: Path) -> list[str]:
    if not path.is_file():
        raise ValidationError(f"歌詞ファイルが見つかりません: {path}")
    if path.suffix.lower() == ".json":
        return [entry.lyrics for entry in load_suno_lyrics_entries(path)]
    return [path.read_text(encoding="utf-8")]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-captions-upload",
        description="suno-lyrics.json と descriptions.md から SRT を生成し YouTube 字幕へ反映する",
    )
    parser.add_argument("--video-id", required=True, help="対象 YouTube video ID")
    parser.add_argument("--lyrics", required=True, type=Path, help="suno-lyrics.json（単曲は plain text も可）")
    parser.add_argument("--descriptions", required=True, type=Path, help="トラックリストを含む descriptions.md")
    parser.add_argument("--language", required=True, help="字幕言語（BCP-47。例: en / ja）")
    parser.add_argument("--name", default="Lyrics", help="YouTube 字幕トラック名（既定: Lyrics）")
    parser.add_argument("--output", type=Path, help="SRT 出力先（既定: <lyrics-dir>/captions.<language>.srt）")
    parser.add_argument("--end-time", help="最後の字幕終端 MM:SS / H:MM:SS（概要欄に総時間がない場合は必須）")
    parser.add_argument(
        "--existing",
        choices=("ask", "update", "skip"),
        default="ask",
        help="同一言語の既存字幕: ask（既定）/ update / skip",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="SRT の生成だけ行い API を呼ばない")
    mode.add_argument("--apply", action="store_true", help="SRT 生成後に YouTube 字幕へ反映する")
    return parser


def _confirm_update(item: dict) -> bool:
    snippet = item.get("snippet", {})
    current_name = snippet.get("name") or item.get("id") or "<unknown>"
    answer = input(f"同一言語の字幕 '{current_name}' が存在します。update しますか？ [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        descriptions_text = args.descriptions.read_text(encoding="utf-8")
        tracks = parse_track_timestamps(descriptions_text)
        total_duration_ms = parse_timestamp(args.end_time) if args.end_time else parse_total_duration(descriptions_text)
        if total_duration_ms is None:
            raise ValidationError("概要欄から総時間を取得できません。--end-time を指定してください")
        lyrics = _load_lyrics(args.lyrics)
        srt = generate_srt(lyrics, tracks, total_duration_ms)
        output = args.output or args.lyrics.parent / f"captions.{args.language}.srt"
        write_srt(output, srt)
        print(f"SRT generated: {output} ({srt.count(' --> ')} cues)")
        if args.dry_run:
            print("dry-run: YouTube API は呼び出していません")
            return 0
        result = upload_caption(
            get_youtube(),
            video_id=args.video_id,
            language=args.language,
            name=args.name,
            srt_path=output,
            existing_policy=args.existing,
            confirm_update=_confirm_update,
        )
        print(f"caption {result.action}: {result.caption_id or '-'}")
        return 0
    except (AutomationError, OSError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
