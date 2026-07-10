"""アップロード preflight / metadata audit 共通の品質チェック関数群.

各関数は問題があれば人間向けの issue 文字列を返し、なければ None を返す。
呼び出し側は戻り値を集約して fail-loud するか、audit のリスト追加に使う。
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from youtube_automation.utils.descriptions_md import (
    build_descriptions_md_parse_diagnostics,
    extract_descriptions_md_section,
    missing_descriptions_md_headings,
)
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.placeholders import is_placeholder_value
from youtube_automation.utils.thumbnail_references import (
    plan_ttp_reference_assignments,
    resolve_configured_benchmark_references,
)
from youtube_automation.utils.youtube_tag import parse_youtube_tags, youtube_tag_chars

YT_TAG_CHAR_LIMIT = 500
YOUTUBE_TITLE_MAX_CODEPOINTS = 100
REQUIRED_LOCALIZATION_LANGUAGES = ("ja", "en", "de")
LOW_CPM_LOCALIZATION_LANGUAGES = ("ko", "es", "pt", "zh-CN")

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
SUNO_DEFAULT_STYLE_CHAR_LIMIT = 120
THUMBNAIL_COMPOSITION_REQUIRED_KEYS = (
    "environment",
    "character_size",
    "character_pose",
    "allowed_actions",
    "ng_actions",
    "background",
)


def requires_scene_phrases(supported_languages: Sequence[str]) -> bool:
    """チャンネルが workflow-state.json.scene_phrases を必要とするかどうか (#1470).

    scene_phrases は多言語 localizations のタイトル生成にのみ使われるため、
    `supported_languages` が 1 言語以下のチャンネルでは不要。populate
    （`yt-populate-scene-phrases` の no-op 判定）と検証側（preflight /
    metadata audit / localizations 生成）はこの判定を共有する。
    """
    return len(set(supported_languages)) > 1


def check_chapter_count(ts_count: int, chapter_max: int) -> str | None:
    """chapter 件数が上限超過なら issue 文字列、範囲内なら None."""
    if ts_count > chapter_max:
        return f"too many timestamps: {ts_count} (> chapter_max={chapter_max})"
    return None


def check_title_codepoint_limit(title: str) -> str | None:
    """YouTube タイトル上限超過なら issue 文字列、範囲内なら None."""
    length = len(title)
    if length > YOUTUBE_TITLE_MAX_CODEPOINTS:
        return f"タイトルが {length} codepoint。YouTube 制限 {YOUTUBE_TITLE_MAX_CODEPOINTS} を超過。\n  {title}"
    return None


def check_descriptions_md_parseability(desc_md: Path, *, allowed_root: Path | None = None) -> str | None:
    """既存 ``descriptions.md`` が共通 parser で読めない場合に診断文字列を返す."""
    if allowed_root is not None:
        root = allowed_root.resolve(strict=False)
        resolved = desc_md.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            return (
                f"{desc_md}: descriptions.md が channel_dir 外を指しています。"
                "リンク先を channel_dir 配下に直してください"
            )
    if desc_md.is_symlink() and not desc_md.exists():
        return f"{desc_md}: descriptions.md の symlink が壊れています。リンク先を修正してください"
    if not desc_md.exists():
        return None
    if not desc_md.is_file():
        return f"{desc_md}: descriptions.md が通常ファイルではありません。/video-description で再生成してください"
    try:
        text = desc_md.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"{desc_md}: descriptions.md を読み取れません: {exc}"
    missing = missing_descriptions_md_headings(text)
    if not missing:
        return None
    return f"{desc_md}: descriptions.md parse failed\n{build_descriptions_md_parse_diagnostics(text, missing)}"


def check_suno_genre_line_char_limit(suno_cfg: Mapping[str, object]) -> str | None:
    """``config/skills/suno.yaml::genre_line`` が Suno Style 欄制限内か検証する."""
    genre_line = str(suno_cfg.get("genre_line") or "").strip()
    if not genre_line:
        return None
    limit = SUNO_DEFAULT_STYLE_CHAR_LIMIT
    if len(genre_line) <= limit:
        return None
    return (
        "config/skills/suno.yaml::genre_line が Suno Style 欄の文字数上限を超過: "
        f"{len(genre_line)} / {limit}。5-Element Order に沿って要素を絞ってください"
    )


def check_thumbnail_skill_config(channel_dir: Path, thumbnail_cfg: Mapping[str, object]) -> list[str]:
    """thumbnail skill-config の初期セットアップ漏れを検出する."""
    image_generation = _as_mapping(thumbnail_cfg.get("image_generation"))
    gemini = _as_mapping(image_generation.get("gemini"))
    generation_mode = str(gemini.get("generation_mode") or "single_step").strip()

    issues: list[str] = []
    if generation_mode == "single_step":
        single_step = _as_mapping(gemini.get("single_step"))
        max_attempts = _positive_int(single_step.get("max_attempts"), default=1)
        rotate = _bool(single_step.get("rotate"), default=True)
        reference_images = _as_mapping(gemini.get("reference_images"))
        resolved_refs = resolve_configured_benchmark_references(channel_dir, reference_images.get("default"))
        has_reference_count_issue = False
        missing_refs: list[str] = []
        if resolved_refs.placeholders or (not resolved_refs.references and not resolved_refs.invalid_reasons):
            issues.append(
                "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default "
                "が未設定/空/TBD です。/channel-new（再生成モード）で benchmark サムネ参照を設定してください"
            )
        elif resolved_refs.references:
            unique_refs = list(dict.fromkeys(resolved_refs.references))
            if len(unique_refs) < max_attempts:
                has_reference_count_issue = True
                issues.append(
                    "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default "
                    f"が必要枚数未満です (max_attempts={max_attempts}, unique_references={len(unique_refs)})"
                )
            missing_refs = [str(ref) for ref in unique_refs if not ref.exists()]
            if missing_refs:
                sample = ", ".join(missing_refs[:3])
                suffix = f" ほか {len(missing_refs) - 3} 件" if len(missing_refs) > 3 else ""
                issues.append(
                    "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default "
                    f"に存在しない参照画像があります: {sample}{suffix}"
                )
        if resolved_refs.invalid_reasons:
            sample = ", ".join(resolved_refs.invalid_reasons[:3])
            suffix = (
                f" ほか {len(resolved_refs.invalid_reasons) - 3} 件" if len(resolved_refs.invalid_reasons) > 3 else ""
            )
            issues.append(
                "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default "
                f"の参照パスが不正です: {sample}{suffix}"
            )
        if resolved_refs.references and not (
            missing_refs or resolved_refs.invalid_reasons or has_reference_count_issue
        ):
            benchmark_root = channel_dir / "data" / "thumbnail_compare" / "benchmark"
            try:
                plan_ttp_reference_assignments(
                    resolved_refs.references,
                    max_attempts,
                    rotate,
                    benchmark_root=benchmark_root,
                )
            except ConfigError as exc:
                issues.append(
                    "config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default "
                    f"が single_step TTP 生成契約を満たしていません: {exc}"
                )

    composition_rules = _as_mapping(gemini.get("composition_rules"))
    missing_composition = [
        key for key in THUMBNAIL_COMPOSITION_REQUIRED_KEYS if _is_placeholder(composition_rules.get(key))
    ]
    if missing_composition:
        issues.append(
            "config/skills/thumbnail.yaml::image_generation.gemini.composition_rules "
            "に未設定/TBD の主要項目があります: " + ", ".join(missing_composition)
        )
    return issues


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
    未指定・null・空リストの `volume_patterns` は既定値にフォールバックする。
    コレクション単位の opt-in は JSON で表せない空 tuple を内部的に渡し、巻数表記の
    照合だけを省略する。`title_template_cfg["template"]` にセパレータを含まない
    チャンネル（` | ` 鋳型を使わない）では適用せず None を返す（後方互換・誤検出防止
    のための自動 opt-in）。
    """
    cfg: Mapping[str, object] = title_template_cfg or {}
    separator = str(cfg.get("separator") or DEFAULT_TITLE_SEPARATOR)
    rhs_pattern = str(cfg.get("rhs_pattern") or DEFAULT_TITLE_RHS_PATTERN)
    configured_volume_patterns = cfg.get("volume_patterns")
    volume_patterns = (
        ()
        if isinstance(configured_volume_patterns, tuple) and not configured_volume_patterns
        else configured_volume_patterns or DEFAULT_TITLE_VOLUME_PATTERNS
    )
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


def check_title_duplicate_warnings(
    title: str,
    existing_titles: Collection[str] = (),
    title_template_cfg: Mapping[str, object] | None = None,
    *,
    min_suffix_chars: int = 16,
) -> list[str]:
    """企画/タイトル決定段階で使う重複 warning を返す.

    upload preflight の fail-loud 判定とは分離し、早い段階で「過去タイトルと似すぎる」
    候補を人間が見直せるようにする。検出対象:

    - タイトル全体の完全一致
    - `separator` 以降（RHS / タイトル後半）の完全一致
    - separator を持たないタイトル同士の長い末尾一致
    """
    normalized = _normalize_title_for_compare(title)
    if not normalized:
        return []

    cfg: Mapping[str, object] = title_template_cfg or {}
    separator = str(cfg.get("separator") or DEFAULT_TITLE_SEPARATOR)
    rhs = _title_rhs(normalized, separator)

    warnings: list[str] = []
    seen: set[str] = set()
    for existing in existing_titles:
        existing_norm = _normalize_title_for_compare(str(existing))
        if not existing_norm:
            continue

        msg: str | None = None
        if normalized.casefold() == existing_norm.casefold():
            msg = f"タイトル全体が既存タイトルと完全一致: {existing_norm!r}"
        else:
            existing_rhs = _title_rhs(existing_norm, separator)
            if rhs and existing_rhs and rhs.casefold() == existing_rhs.casefold():
                msg = f"タイトル後半が既存タイトルと一致: {rhs!r} (既存: {existing_norm!r})"
            else:
                suffix = _matching_suffix(normalized, existing_norm, min_chars=min_suffix_chars)
                if suffix:
                    msg = f"タイトル末尾が既存タイトルと一致: {suffix!r} (既存: {existing_norm!r})"

        if msg and msg not in seen:
            warnings.append(msg)
            seen.add(msg)
    return warnings


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


def _normalize_title_for_compare(title: str) -> str:
    return " ".join(title.strip().split())


def _title_rhs(title: str, separator: str) -> str:
    if not separator or separator not in title:
        return ""
    parts = title.split(separator, 1)
    return parts[1].strip() if len(parts) == 2 else ""


def _matching_suffix(a: str, b: str, *, min_chars: int) -> str:
    a_fold = a.casefold()
    b_fold = b.casefold()
    max_len = min(len(a_fold), len(b_fold))
    match_len = 0
    for i in range(1, max_len + 1):
        if a_fold[-i] != b_fold[-i]:
            break
        match_len = i
    if match_len < min_chars:
        return ""
    suffix = a[-match_len:].strip()
    return suffix if len(suffix) >= min_chars else ""


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


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return default


def _bool(value: object, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _is_placeholder(value: object) -> bool:
    return is_placeholder_value(value)


def extract_descriptions_md_tags(desc_md: Path) -> list[str] | None:
    """`descriptions.md` の「タグ（YouTube タグ欄）」セクションからタグリストを抽出.

    実アップロード時 `_load_descriptions_md` がここを優先採用するため、preflight も
    本番と同じソースを検証する必要がある。ファイル不在 / セクション不在 / 空なら None。
    """
    if not desc_md.exists():
        return None
    raw = extract_descriptions_md_section(desc_md.read_text(encoding="utf-8"), "タグ（YouTube タグ欄）")
    if raw is None:
        return None
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
