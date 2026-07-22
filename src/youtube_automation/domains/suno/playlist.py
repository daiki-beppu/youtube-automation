"""Suno playlist の曲名と suno-prompts.json entry title/name の突合検証.

/masterup の前段ゲート。playlist に別コレクションの曲が混入したまま
master 化される事故（前コレクション曲の紛れ込み・最新セット未完）を
fail-loud で検出する。

照合キーは `/suno-helper` が Suno UI の Song Title 欄へ注入する
`entry.title ?? entry.name`。Suno 側でタイトルは保持される前提だが、
空白ゆれ・Unicode 正規化差・大文字小文字は吸収する。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from youtube_automation.domains.suno.prompts import read_suno_prompt_entries
from youtube_automation.utils.exceptions import ValidationError

_WS_RE = re.compile(r"\s+")
_MAX_DISPLAY_TEXT_LEN = 200


def normalize_title(value: str) -> str:
    """タイトル照合キーを正規化する（NFKC + 空白圧縮 + casefold）."""
    text = unicodedata.normalize("NFKC", value)
    text = _WS_RE.sub(" ", text).strip()
    return text.casefold()


@dataclass(frozen=True)
class PlaylistVerificationResult:
    """突合結果。

    Attributes:
        matched: entry title/name（原文）→ playlist 内の一致曲数
        unknown_titles: どの entry にも一致しない playlist 曲名（混入疑い）
        missing_entries: playlist に 1 曲も現れない entry title/name（未生成疑い）
        underfilled_entries: 一致数が expected_clips_per_entry 未満の entry title/name
    """

    matched: Mapping[str, int]
    unknown_titles: tuple[str, ...]
    missing_entries: tuple[str, ...]
    underfilled_entries: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.unknown_titles and not self.missing_entries and not self.underfilled_entries


def load_entry_names(collection_dir: Path) -> list[str]:
    """suno-prompts.json から Song Title 欄に入る title/name の一覧を読み出す."""
    try:
        entries = read_suno_prompt_entries(collection_dir)
    except (OSError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    names: list[str] = []
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, Mapping):
            raise ValidationError(f"suno-prompts.json: entry {i} must be an object")
        name = entry.get("name")
        title = entry.get("title")
        if title is not None and not isinstance(title, str):
            raise ValidationError(f"suno-prompts.json: entry {i} title must be a string")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError(f"suno-prompts.json: entry {i} has no name")
        song_title = title if title is not None and title.strip() else name
        names.append(song_title.strip())
    if not names:
        raise ValidationError("suno-prompts.json に entry がありません")
    return names


def verify_playlist_titles(
    entry_names: Iterable[str],
    playlist_titles: Iterable[str],
    *,
    expected_clips_per_entry: int = 2,
) -> PlaylistVerificationResult:
    """playlist 曲名一覧を entry title/name と突合する.

    Args:
        entry_names: suno-prompts.json の entry title/name（原文）
        playlist_titles: playlist の曲名（原文）
        expected_clips_per_entry: entry あたりの期待 clip 数
            （1 Generate = 2 clip の既定運用は 2。再生成で増えた分は許容し、
            下回った entry だけ underfilled として報告する。0 以下で無効化）
    """
    originals = list(entry_names)
    lookup: dict[str, str] = {}
    for name in originals:
        key = normalize_title(name)
        if key in lookup:
            raise ValidationError(f"entry title/name が正規化後に衝突しています: {lookup[key]!r} / {name!r}")
        lookup[key] = name

    matched: dict[str, int] = {name: 0 for name in originals}
    unknown: list[str] = []
    for title in playlist_titles:
        key = normalize_title(title)
        target = lookup.get(key)
        if target is None:
            unknown.append(title.strip())
        else:
            matched[target] += 1

    missing = tuple(name for name, count in matched.items() if count == 0)
    underfilled: tuple[str, ...] = ()
    if expected_clips_per_entry > 0:
        underfilled = tuple(name for name, count in matched.items() if 0 < count < expected_clips_per_entry)
    return PlaylistVerificationResult(
        matched=matched,
        unknown_titles=tuple(unknown),
        missing_entries=missing,
        underfilled_entries=underfilled,
    )


def format_verification_report(result: PlaylistVerificationResult) -> str:
    """人間向けレポートを整形する（stdout 用）."""
    lines: list[str] = []
    lines.append("[yt-suno-verify-playlist] playlist × suno-prompts.json 突合結果")
    for name, count in result.matched.items():
        if count > 0:
            lines.append(f"  ✓ {format_display_text(name)}: {count} clip(s)")
    if result.unknown_titles:
        lines.append("  ❌ 混入疑い（どの entry にも一致しない曲）:")
        for title in result.unknown_titles:
            lines.append(f"     - {format_display_text(title)}")
    if result.missing_entries:
        lines.append("  ❌ 未生成疑い（playlist に存在しない entry）:")
        for name in result.missing_entries:
            lines.append(f"     - {format_display_text(name)}")
    if result.underfilled_entries:
        lines.append("  ⚠️ clip 不足（期待数未満の entry）:")
        for name in result.underfilled_entries:
            lines.append(f"     - {format_display_text(name)}")
    if result.ok:
        lines.append("  → OK")
    else:
        lines.append("  → NG: playlist を修正（混入除外 / 追補生成）してから /masterup を再実行してください")
    return "\n".join(lines)


def format_display_text(value: str) -> str:
    """外部由来 title/name を stdout 用に制御文字 escape する."""
    text = "".join(_escape_display_character(char) for char in value)
    if len(text) <= _MAX_DISPLAY_TEXT_LEN:
        return text
    return text[: _MAX_DISPLAY_TEXT_LEN - 3] + "..."


def _escape_display_character(char: str) -> str:
    """通常文字は保持し、制御文字だけ Python escape 表記へ変換する."""
    if char == "\n":
        return "\\n"
    if char == "\r":
        return "\\r"
    if char == "\t":
        return "\\t"
    if unicodedata.category(char)[0] == "C":
        return char.encode("unicode_escape").decode("ascii")
    return char
