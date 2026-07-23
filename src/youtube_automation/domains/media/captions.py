"""歌詞からの SRT 生成。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.domains.metadata.descriptions import extract_descriptions_md_section
from youtube_automation.utils.exceptions import ValidationError

_TIMESTAMP_RE = re.compile(r"^(?P<timestamp>(?:\d{1,2}:)?\d{1,2}:\d{2})\s+(?P<title>.+?)\s*$")
_TOTAL_DURATION_RE = re.compile(r"\btracks?\s*,\s*(?P<duration>(?:\d{1,2}:)?\d{1,2}:\d{2})\b", re.IGNORECASE)
_SECTION_TAG_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")


@dataclass(frozen=True)
class TrackTimestamp:
    """概要欄トラックリストの 1 行。"""

    start_ms: int
    title: str


def parse_timestamp(value: str) -> int:
    """``MM:SS`` / ``H:MM:SS`` をミリ秒へ変換する。"""

    parts = value.strip().split(":")
    if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
        raise ValidationError(f"不正なタイムスタンプです: {value}")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = (int(part) for part in parts)
    else:
        hours, minutes, seconds = (int(part) for part in parts)
        if minutes >= 60:
            raise ValidationError(f"不正なタイムスタンプです: {value}")
    if seconds >= 60:
        raise ValidationError(f"不正なタイムスタンプです: {value}")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000


def parse_track_timestamps(descriptions_text: str) -> list[TrackTimestamp]:
    """descriptions.md の Complete Collection 概要欄からトラック開始時刻を読む。"""

    description = extract_descriptions_md_section(descriptions_text, "Complete Collection 概要欄")
    source = description if description is not None else descriptions_text
    tracks: list[TrackTimestamp] = []
    for line in source.splitlines():
        match = _TIMESTAMP_RE.match(line.strip())
        if match:
            tracks.append(
                TrackTimestamp(
                    start_ms=parse_timestamp(match.group("timestamp")),
                    title=match.group("title").strip(),
                )
            )
    if not tracks:
        raise ValidationError("descriptions.md にタイムスタンプ付きトラック行がありません")
    starts = [track.start_ms for track in tracks]
    if starts != sorted(set(starts)):
        raise ValidationError("トラック開始時刻は昇順かつ重複なしである必要があります")
    return tracks


def parse_total_duration(descriptions_text: str) -> int | None:
    """Complete Collection 概要欄の ``N tracks, H:MM:SS`` から総時間を読む。"""

    description = extract_descriptions_md_section(descriptions_text, "Complete Collection 概要欄")
    source = description if description is not None else descriptions_text
    match = _TOTAL_DURATION_RE.search(source)
    return parse_timestamp(match.group("duration")) if match else None


def lyric_lines(lyrics: str) -> list[str]:
    """Suno のセクションタグと空行を除き、表示対象の歌詞行を返す。"""

    return [line.strip() for line in lyrics.splitlines() if line.strip() and not _SECTION_TAG_RE.match(line)]


def _format_srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def generate_srt(
    lyrics_by_track: Sequence[str],
    track_starts: Sequence[int | TrackTimestamp],
    total_duration_ms: int,
) -> str:
    """各トラック区間を歌詞行へ均等配分して SRT を生成する。

    音声アライメントは行わない。各区間の終端は次トラックの開始時刻、最後だけ
    ``total_duration_ms`` とし、整数補間した境界を共有することで重複を防ぐ。
    """

    starts = [item.start_ms if isinstance(item, TrackTimestamp) else item for item in track_starts]
    if len(lyrics_by_track) != len(starts):
        raise ValidationError(f"歌詞エントリ数 ({len(lyrics_by_track)}) とトラック数 ({len(starts)}) が一致しません")
    if not starts:
        raise ValidationError("1 件以上のトラックが必要です")
    if any(not isinstance(start, int) or start < 0 for start in starts):
        raise ValidationError("トラック開始時刻は 0 以上の整数ミリ秒で指定してください")
    if starts != sorted(set(starts)):
        raise ValidationError("トラック開始時刻は昇順かつ重複なしである必要があります")
    if type(total_duration_ms) is not int or total_duration_ms < 0:
        raise ValidationError("総時間は 0 以上の整数ミリ秒で指定してください")
    if total_duration_ms < starts[-1]:
        raise ValidationError("総時間は最後のトラック開始時刻以降である必要があります")

    cues: list[tuple[int, int, str]] = []
    ends = [*starts[1:], total_duration_ms]
    for track_index, (lyrics, start, end) in enumerate(zip(lyrics_by_track, starts, ends, strict=True), 1):
        lines = lyric_lines(lyrics)
        if not lines:
            raise ValidationError(f"トラック {track_index} に表示可能な歌詞行がありません")
        duration = end - start
        if duration < 0 or (0 < duration < len(lines)) or (duration == 0 and len(lines) != 1):
            raise ValidationError(f"トラック {track_index} の区間が歌詞行数より短すぎます")
        boundaries = [start + duration * i // len(lines) for i in range(len(lines) + 1)]
        cues.extend((boundaries[i], boundaries[i + 1], line) for i, line in enumerate(lines))

    blocks = [
        f"{index}\n{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n{text}"
        for index, (start, end, text) in enumerate(cues, 1)
    ]
    return "\n\n".join(blocks) + "\n"


def write_srt(path: Path, content: str) -> Path:
    """SRT を UTF-8 で出力する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
