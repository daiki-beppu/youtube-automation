"""アップロード preflight / metadata audit 共通の品質チェック関数群.

各関数は問題があれば人間向けの issue 文字列を返し、なければ None を返す。
呼び出し側は戻り値を集約して fail-loud するか、audit のリスト追加に使う。
"""

from __future__ import annotations

import re
from pathlib import Path

from youtube_automation.utils.youtube_tag import youtube_tag_chars

YT_TAG_CHAR_LIMIT = 500

_DESC_TAGS_RE = re.compile(r"## タグ（YouTube タグ欄）\s*\n+```\n(.*?)```", re.DOTALL)


def extract_descriptions_md_tags(desc_md: Path) -> list[str] | None:
    """`descriptions.md` の「タグ（YouTube タグ欄）」セクションからタグリストを抽出.

    実アップロード時 `_load_descriptions_md` がここを優先採用するため、preflight も
    本番と同じソースを検証する必要がある。ファイル不在 / セクション不在 / 空なら None。
    """
    if not desc_md.exists():
        return None
    m = _DESC_TAGS_RE.search(desc_md.read_text(encoding="utf-8"))
    if not m:
        return None
    raw = m.group(1).strip()
    tags = [t.strip() for t in raw.replace("\n", ",").split(",") if t.strip()]
    return tags or None


def check_tags_count(tags: list[str], min_count: int | None) -> str | None:
    """件数下限を満たさない場合 issue 文字列、満たせば None."""
    if min_count is None:
        return None
    if len(tags) < min_count:
        return f"tags count: {len(tags)} (min {min_count})"
    return None


def check_tags_yt_chars(tags: list[str], limit: int = YT_TAG_CHAR_LIMIT) -> str | None:
    """quotation 込み文字数が limit 超なら issue 文字列、満たせば None."""
    chars = youtube_tag_chars(tags)
    if chars > limit:
        return f"tags YT chars (quoted): {chars} / {limit}"
    return None


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def check_duration(
    seconds: float,
    min_sec: float | None,
    max_sec: float | None,
) -> str | None:
    """動画尺が target_duration の範囲外なら issue 文字列、満たせば None.

    両方 None なら無効化（None を返す）。
    """
    if min_sec is None and max_sec is None:
        return None
    actual = _format_duration(seconds)
    if min_sec is not None and seconds < min_sec:
        target = _target_label(min_sec, max_sec)
        return f"duration: {actual} (target {target})"
    if max_sec is not None and seconds > max_sec:
        target = _target_label(min_sec, max_sec)
        return f"duration: {actual} (target {target})"
    return None


def _target_label(min_sec: float | None, max_sec: float | None) -> str:
    if min_sec is not None and max_sec is not None:
        return f"{_format_duration(min_sec)}〜{_format_duration(max_sec)}"
    if min_sec is not None:
        return f"≥{_format_duration(min_sec)}"
    return f"≤{_format_duration(max_sec)}"  # type: ignore[arg-type]
