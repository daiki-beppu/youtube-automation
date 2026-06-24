"""アップロード preflight / metadata audit 共通の品質チェック関数群.

各関数は問題があれば人間向けの issue 文字列を返し、なければ None を返す。
呼び出し側は戻り値を集約して fail-loud するか、audit のリスト追加に使う。
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from youtube_automation.utils.youtube_tag import parse_youtube_tags, youtube_tag_chars

YT_TAG_CHAR_LIMIT = 500
REQUIRED_LOCALIZATION_LANGUAGES = ("ja", "en", "de")
LOW_CPM_LOCALIZATION_LANGUAGES = ("ko", "es", "pt", "zh-CN")

_DESC_TAGS_RE = re.compile(r"## タグ（YouTube タグ欄）\s*\n+```\n(.*?)```", re.DOTALL)

# v1〜v9 もしくは末尾のロマン数字 (I/II/III/IV/V/VI/VII/VIII) を検出する。
# chapter 名末尾にこれが現れる場合、1 パターンを複数バリエーションに展開した事故とみなす。
_VARIATION_SUFFIX_RE = re.compile(r"\b(I{1,3}|IV|V|VI{0,3}|v[1-9])\b\s*$")

# --- タイトル鋳型準拠チェック（#602）の既定値 ----------------------------------
# いずれもチャンネル config (`content.json::title.template_check`) で上書き可能。
# ハードコードではなく「config 未設定チャンネル向けの汎用フォールバック」。
DEFAULT_TITLE_SEPARATOR = " | "
# RHS（セパレータ以降）が満たすべき鋳型。既定は `N Hours of ...` 系。
DEFAULT_TITLE_RHS_PATTERN = r"^\d+\s+Hours?\s+of\s+\S.*$"
# 巻数表記（コレクション名の公開タイトル流用事故）の検出パターン。LHS に対して適用。
DEFAULT_TITLE_VOLUME_PATTERNS = (
    r"\bVol\.?\s*\d+",  # Vol.2 / Vol 2 / Vol2
    r"\bPart\s*\d+",  # Part 2
    r"#\s*\d+",  # #2
    r"\bVol\.?\s*[IVXLCDM]+\b",  # Vol. II
    r"\b(?:I{2,3}|IV|VI{0,3}|IX|X)\b\s*$",  # 末尾ローマ数字 (II〜X)
)


def check_chapter_count(ts_count: int, chapter_max: int) -> str | None:
    """chapter 件数が上限超過なら issue 文字列、範囲内なら None."""
    if ts_count > chapter_max:
        return f"too many timestamps: {ts_count} (> chapter_max={chapter_max})"
    return None


def check_chapter_variation_suffix(ts_lines: list[str]) -> str | None:
    """chapter 名末尾にパターン展開接尾辞（v1〜v9 / I〜VIII）を含むなら issue 文字列.

    1 パターン = 1 chapter の事故展開を検出する。なければ None。
    """
    hits = [line for line in ts_lines if _VARIATION_SUFFIX_RE.search(line)]
    if hits:
        return f"chapter names contain variation suffix (v1〜v9 / I〜VIII): {len(hits)} lines"
    return None


def check_title_template_compliance(
    title: str,
    existing_titles: Collection[str] = (),
    title_template_cfg: Mapping[str, object] | None = None,
) -> str | None:
    """公開タイトルがチャンネルの TTP 鋳型に準拠しているか検証する (#602).

    検出した逸脱を `; ` で連結した理由文字列を返し、問題なければ None を返す:

    - **鋳型形式**: セパレータ（既定 ` | `）で LHS/RHS に分割でき、RHS が
      チャンネル鋳型（既定 `N Hours of ...`）に一致するか
    - **巻数表記**: LHS に `Vol.` / `Vol N` / `Part N` / ローマ数字巻数 / `#N` を
      含まないか（コレクション名＝内部管理ラベルの公開タイトル流用事故を検出）
    - **RHS 重複**: 既存 live タイトル群と RHS（セパレータ以降）が完全一致しないか
    - **ジャンル核語彙**（任意）: `core_vocabulary` 設定時、LHS にいずれかを含むか

    鋳型語彙・パターンは `title_template_cfg`（チャンネル config 由来）から導出し、
    未指定キーは既定値にフォールバックする。`title_template_cfg["template"]` に
    セパレータを含まないチャンネル（` | ` 鋳型を使わない）では適用せず None を返す
    （後方互換・誤検出防止のための自動 opt-in）。
    """
    cfg: Mapping[str, object] = title_template_cfg or {}
    separator = str(cfg.get("separator") or DEFAULT_TITLE_SEPARATOR)
    rhs_pattern = str(cfg.get("rhs_pattern") or DEFAULT_TITLE_RHS_PATTERN)
    volume_patterns = cfg.get("volume_patterns") or DEFAULT_TITLE_VOLUME_PATTERNS
    core_vocabulary = cfg.get("core_vocabulary") or ()

    # 鋳型がセパレータ運用でないチャンネルには適用しない（template から自動判定）。
    template = str(cfg.get("template") or "")
    if template and separator not in template:
        return None

    normalized = title.strip()
    parts = normalized.split(separator)
    if len(parts) != 2:
        return f"鋳型形式逸脱: '{separator.strip()}' で LHS/RHS に分割できません: {normalized!r}"
    lhs, rhs = parts[0].strip(), parts[1].strip()

    issues: list[str] = []

    if not re.match(rhs_pattern, rhs):
        issues.append(f"RHS が鋳型に一致しません（要 /{rhs_pattern}/）: {rhs!r}")

    vol_hit = _first_pattern_hit(lhs, volume_patterns)
    if vol_hit:
        issues.append(f"巻数表記を検出: {vol_hit!r}（コレクション名の公開タイトル流用を疑ってください）")

    if _has_duplicate_full_title(normalized, existing_titles):
        issues.append(f"タイトル全体が既存 live タイトルと完全重複: {normalized!r}")

    if core_vocabulary and not _contains_any_vocab(lhs, core_vocabulary):
        issues.append(f"LHS に鋳型語彙 {list(core_vocabulary)} が含まれません: {lhs!r}")

    return "; ".join(issues) if issues else None


def _first_pattern_hit(text: str, patterns: Sequence[str] | Collection[str]) -> str | None:
    for pattern in patterns:
        m = re.search(str(pattern), text)
        if m:
            return m.group(0).strip()
    return None


def _has_duplicate_full_title(title: str, existing_titles: Collection[str]) -> bool:
    if not title:
        return False
    return any(title == str(other).strip() for other in existing_titles)


def _contains_any_vocab(text: str, vocabulary: Collection[str]) -> bool:
    return any(re.search(rf"\b{re.escape(str(word))}\b", text, re.IGNORECASE) for word in vocabulary)


def check_required_localization_languages(
    supported_languages: Collection[str],
    *,
    required: Collection[str] = REQUIRED_LOCALIZATION_LANGUAGES,
) -> str | None:
    missing = _ordered_intersection(required, set(required) - set(supported_languages))
    if missing:
        return f"required localization languages missing: {', '.join(missing)}"
    return None


def check_low_cpm_localization_languages(
    supported_languages: Collection[str],
    *,
    low_cpm: Collection[str] = LOW_CPM_LOCALIZATION_LANGUAGES,
) -> str | None:
    included = _ordered_intersection(low_cpm, set(supported_languages) & set(low_cpm))
    if included:
        return f"low CPM localization languages included: {', '.join(included)}"
    return None


def _ordered_intersection(order: Collection[str], values: set[str]) -> list[str]:
    return [lang for lang in order if lang in values]


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
    tags = parse_youtube_tags(raw)
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
