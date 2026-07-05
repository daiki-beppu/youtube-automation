#!/usr/bin/env python3
"""Generate suno-prompts.md from config/skills/suno.yaml + suno-patterns.yaml."""

import argparse
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from youtube_automation.scripts.suno_artifacts import (
    DOCUMENTATION_DIRNAME,
    SUNO_LYRICS_JSON_FILENAME,
    SUNO_PATTERNS_FILENAME,
    SUNO_PROMPTS_JSON_FILENAME,
    SUNO_PROMPTS_MD_FILENAME,
)
from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.skill_config import load_channel_override, load_skill_config
from youtube_automation.utils.suno_lyrics import load_suno_lyrics_by_name
from youtube_automation.utils.video_analyzer import VIDEO_ANALYSIS_DIRNAME

_TOP_GENRE_PHRASES = 8

# ---------------------------------------------------------------------------
# Quality rules (#904): suno-bgm ベースの品質ガード
# ---------------------------------------------------------------------------

# Style text の 5 要素順序: ジャンル名 → 音響特性 → キー楽器 → リズム/ベース → テンポ
# 厳密な順序検証は不可能（自然言語のため）だが、テンポ語が先頭付近にある場合は警告する
_TEMPO_WORDS = frozenset({"very slow", "slow", "gentle", "moderate", "lively", "fast", "uptempo", "downtempo"})


def validate_style_char_limit(style_text: str, *, limit: int = 120) -> list[str]:
    """Style テキストが文字数上限を超えていないか検証する.

    Returns: 警告メッセージのリスト (空なら問題なし)。
    """
    warnings_list: list[str] = []
    if len(style_text) > limit:
        warnings_list.append(f"Style text exceeds {limit} char limit ({len(style_text)} chars): {style_text[:80]}...")
    return warnings_list


def validate_banned_artists(style_text: str, banned_artists: list[str]) -> list[str]:
    """Style テキストに禁止アーティスト名が含まれていないか検証する.

    Returns: エラーメッセージのリスト (空なら問題なし)。
    """
    errors: list[str] = []
    lower_text = style_text.lower()
    for artist in banned_artists:
        if artist.lower() in lower_text:
            errors.append(f"Banned artist name found in Style text: '{artist}'")
    return errors


def validate_5_element_order(style_text: str) -> list[str]:
    """Style テキストの 5 要素順序を簡易検証する.

    テンポ語がスタイルテキストの先頭 1/3 以内に出現する場合、5 要素順序
    （ジャンル名 → 音響特性 → キー楽器 → リズム/ベース → テンポ）に
    違反している可能性があると警告する。

    Returns: 警告メッセージのリスト (空なら問題なし)。
    """
    warnings_list: list[str] = []
    lower_text = style_text.lower()
    # テンポ語がテキスト先頭 1/3 以内にあるか
    threshold = max(len(lower_text) // 3, 10)
    for tempo_word in _TEMPO_WORDS:
        idx = lower_text.find(tempo_word)
        if idx != -1 and idx < threshold:
            warnings_list.append(
                f"Tempo word '{tempo_word}' appears early in Style text (position {idx}). "
                f"5-element order: genre -> acoustics -> key instrument -> rhythm/bass -> tempo"
            )
            break
    return warnings_list


def apply_auto_lyrics_structure(lyrics: str, *, is_vocal: bool) -> str:
    """auto_lyrics_structure が有効な場合、歌詞構造を自動補強する.

    - インストモード: 先頭に [Instrumental] がなければ追加、末尾に [Extended Outro] がなければ追加
    - ボーカルモード: 末尾セクションが [Outro] / [Extended Outro] でなければ [Extended Outro] を追加
    """
    if not lyrics:
        if not is_vocal:
            return "[Instrumental]\n\n[Extended Outro]"
        return lyrics

    stripped = lyrics.strip()

    if not is_vocal:
        # インストモード: [Instrumental] を先頭に、[Extended Outro] を末尾に
        if "[Instrumental]" not in stripped and "[instrumental]" not in stripped.lower():
            stripped = "[Instrumental]\n\n" + stripped
        if not re.search(r"\[Extended Outro\]", stripped, re.IGNORECASE):
            stripped = stripped + "\n\n[Extended Outro]"
        return stripped

    # ボーカルモード: 末尾に [Outro] / [Extended Outro] がなければ追加
    if not re.search(r"\[(Extended )?Outro\]\s*$", stripped, re.IGNORECASE):
        # 末尾に何かテキストがあるか確認
        last_bracket = stripped.rfind("[")
        if last_bracket != -1:
            last_tag = stripped[last_bracket:].split("]")[0] + "]" if "]" in stripped[last_bracket:] else ""
            if last_tag.lower() not in ("[outro]", "[extended outro]"):
                stripped = stripped + "\n\n[Extended Outro]"
        else:
            stripped = stripped + "\n\n[Extended Outro]"
    return stripped


@dataclass
class QualityReport:
    """品質ルール検証の結果をまとめるレポート."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


def _split_csv(value: str) -> list[str]:
    return [p.strip() for p in str(value).split(",") if p.strip()]


def _collect_video_analysis_presets() -> tuple[str, str]:
    """全 slug の video_analysis JSON から `suno_preset` を集約して fallback 値を返す。"""
    try:
        base = channel_dir() / "data" / VIDEO_ANALYSIS_DIRNAME
    except ConfigError:
        return "", ""
    if not base.exists():
        return "", ""

    genre_counter: Counter[str] = Counter()
    exclude_seen: dict[str, None] = {}

    for slug_dir in sorted(base.iterdir()):
        if not slug_dir.is_dir():
            continue
        for f in sorted(slug_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            preset = data.get("suno_preset")
            if not isinstance(preset, dict):
                continue
            for phrase in _split_csv(preset.get("genre_line", "")):
                genre_counter[phrase] += 1
            for phrase in _split_csv(preset.get("exclude_styles", "")):
                exclude_seen.setdefault(phrase, None)

    top_genre = ", ".join(p for p, _ in genre_counter.most_common(_TOP_GENRE_PHRASES))
    return top_genre, ", ".join(exclude_seen)


def _style_line(tempo: str | None, effective_style: str, variation_descriptor: str) -> str:
    """Styles 欄の 1 行目を組み立てる共有部品."""
    parts = [tempo] if tempo else []
    parts.append(effective_style)
    if variation_descriptor:
        parts.append(variation_descriptor)
    return ", ".join(parts) + ","


def _build_variation_sequence(pools: Mapping[str, list[str]]) -> list[str]:
    """`style_variation.pools` から descriptor の割り当て列を構築する."""
    axes = [pools[name] for name in sorted(pools) if pools[name]]
    if not axes:
        return []
    sequence: list[str] = []
    for i in range(max(len(axis) for axis in axes)):
        for axis in axes:
            if i < len(axis):
                sequence.append(str(axis[i]))
    return sequence


def _variation_descriptor(entry_index: int, sequence: list[str]) -> str:
    """コレクション内の entry 通し番号に対する descriptor を返す."""
    if entry_index == 0 or not sequence:
        return ""
    return sequence[(entry_index - 1) % len(sequence)]


@dataclass(frozen=True)
class _ResolvedStyleVariation:
    enabled: bool
    sequence: list[str]


def _resolve_style_variation(raw: object) -> _ResolvedStyleVariation:
    if raw is None:
        raise ConfigError("suno.style_variation は mapping である必要があります: None")
    if not isinstance(raw, Mapping):
        raise ConfigError(f"suno.style_variation は mapping である必要があります: {raw!r}")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError(f"suno.style_variation.enabled は bool である必要があります: {enabled!r}")

    pools_raw = raw.get("pools", {})
    if pools_raw is None:
        raise ConfigError("suno.style_variation.pools は mapping である必要があります: None")
    if not isinstance(pools_raw, Mapping):
        raise ConfigError(f"suno.style_variation.pools は mapping である必要があります: {pools_raw!r}")

    pools: dict[str, list[str]] = {}
    for axis, descriptors_raw in pools_raw.items():
        if not isinstance(axis, str) or not axis.strip():
            raise ConfigError(f"suno.style_variation.pools の axis 名は非空文字列である必要があります: {axis!r}")
        if not isinstance(descriptors_raw, list):
            raise ConfigError(
                f"suno.style_variation.pools.{axis} は list[str] である必要があります: {descriptors_raw!r}"
            )
        descriptors: list[str] = []
        for descriptor in descriptors_raw:
            if not isinstance(descriptor, str) or not descriptor.strip():
                raise ConfigError(
                    f"suno.style_variation.pools.{axis} の descriptor は非空文字列である必要があります: {descriptor!r}"
                )
            descriptors.append(descriptor)
        pools[axis] = descriptors

    return _ResolvedStyleVariation(enabled=enabled, sequence=_build_variation_sequence(pools) if enabled else [])


@dataclass
class _ResolvedPattern:
    name_jp: str
    name_en: str
    style_label: str
    style_lines: list[str]  # scenes と同じ長さ。entry ごとの Styles 第 1 行 (#1456)
    scenes: list[str]
    lyrics_by_scene: list[str]  # scenes と同じ長さ。各値は rstrip 済み。歌詞が無ければ ""


# suno-prompts.json へ wire する More Options の key 一覧 (#900, vocal_gender 追加)。
# JSON への反映は **channel override (config/skills/suno.yaml) に明示設定されたキーのみ**。
# config.default.yaml 同梱の既定値 (style_influence: 50 等) は JSON には載せない
# (= 「何も足さない既存 collection は name/style/lyrics の 3 キーちょうど」の後方互換を守るため)。
# MD 出力は従来どおり merged 値 (既定込み) を表示する。
# vocal_gender は suno-helper 拡張が Suno UI Voice section の Male / Female ボタン押下に使う
# (拡張型契約: "male" | "female" | "neutral" | "auto")。空文字は「未指定」として JSON 出力から省く
# (_build_advanced_json_fields の skip ロジック参照)。
_ADVANCED_JSON_KEYS = ("style_influence", "weirdness", "exclude_styles", "vocal_gender")


def _build_advanced_json_fields(override: dict) -> dict:
    """channel override から JSON 反映用 advanced フィールド dict を構築する (#900)。

    - override に明示されたキーのみ含める (default.yaml の既定値は無視、#900 の A 案)
    - vocal_gender は "" を「未指定」として skip する (拡張型契約と一貫させる)
    - 他キー (style_influence: 0 / weirdness: 0 / exclude_styles: "") は明示設定なら値そのまま wire
      (0 などの falsy 境界値が脱落しない契約は #900 で pin 済み)
    """
    out: dict = {}
    for key in _ADVANCED_JSON_KEYS:
        if key not in override:
            continue
        value = override[key]
        if key == "vocal_gender" and value == "":
            continue
        out[key] = value
    return out


@dataclass
class _ResolvedPrompts:
    title: str
    is_vocal: bool
    style_influence: int
    weirdness: int
    exclude_styles: str
    # channel override に明示設定された More Options フィールドのみを保持する (#900)。
    # collection スコープ: 全 entry に同じ値が載る。未設定キーは dict に含めない。
    advanced_json_fields: dict
    patterns: list[_ResolvedPattern]


def _validate_instrumental_track_count(
    yaml_path: Path,
    entries_count: int,
    tracks_per_collection: int,
) -> None:
    """インストモードで yaml の entry 数が ceil(tracks_per_collection / 2) と一致するか fail-loud で検証する.

    Suno は 1 リクエスト = 2 clip 生成するため、最終 clip 数 `tracks_per_collection` を満たすには
    yaml `patterns:` 配列の `scenes` 行数の合計 (= 連続生成の entry 数) が `ceil(N/2)` と
    一致する必要がある。ズレを silent に通すと運用上「曲数不足」「曲数過剰」に気付けないため、
    新運用 (tracks_per_collection を明示指定) では fail-loud にして AI / operator に修正を促す。
    """
    expected = math.ceil(tracks_per_collection / 2)
    if entries_count == expected:
        return
    raise ConfigError(
        f"インストモード: tracks_per_collection={tracks_per_collection} から "
        f"ceil({tracks_per_collection}/2)={expected} 個の entry が必要ですが、"
        f"{yaml_path.name} には {entries_count} 個あります "
        f"(`patterns:` 配列の `scenes` 行数の合計)。"
    )


def _entry_names_from_resolved(resolved: list[_ResolvedPattern]) -> list[str]:
    """`build_prompt_entries` と同一ロジックで最終的な entry.name のみを構築する.

    Suno UI Song Title 欄へ注入される値 (suno-helper 拡張は `entry.title ?? entry.name` を読む)
    の SSOT。複数 scene を持つ pattern は `(Variation N)` 付与でユニーク化される (#854 由来)。
    """
    names: list[str] = []
    for p in resolved:
        base_name = f"{p.name_jp} — {p.name_en}"
        multi = len(p.scenes) > 1
        for j in range(1, len(p.scenes) + 1):
            names.append(f"{base_name} (Variation {j})" if multi else base_name)
    return names


def _validate_unique_titles(yaml_path: Path, entry_names: list[str]) -> None:
    """全 entry の最終 name (Suno UI Song Title 欄に注入される値) が重複していないか fail-loud で検証する.

    重複は (1) Suno Library で同名 clip が並んで識別不能になる、(2) `/suno-helper` の進捗 phase で
    どの entry の clip か追跡しにくくなる、(3) `/masterup` のリネーム時に衝突する、といった運用問題を
    起こすため yaml レベルで弾く。インストモードは entry が独立した世界観を持つ前提で AI が固有の
    `name_jp` / `name_en` を毎回設計する必要があり、ボーカルモードは pattern 間で重複しないことが
    自明設計なので両モードで一律検証する (Variation 付与済みの後の name が比較対象)。
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in entry_names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if not duplicates:
        return
    raise ConfigError(
        f"全曲のタイトル (entry name) はユニークでなければなりません。"
        f"{yaml_path.name} で以下が重複しています: {', '.join(sorted(duplicates))}"
    )


def _load_external_lyrics(lyrics_path: Path) -> dict[str, str]:
    """`suno-lyrics.json` から entry name -> lyrics を読み込む.

    `/suno-lyric` は lyrics 専任で、`/suno` がここで Style と結合する。
    vocal mode のファイル必須チェックは呼び出し元で行う。
    """
    return load_suno_lyrics_by_name(lyrics_path)


def _validate_external_lyrics_names(
    *,
    lyrics_path: Path,
    expected_names: set[str],
    actual_names: set[str],
) -> None:
    """`suno-lyrics.json` と最終 prompt entry name の完全一致を検証する."""
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    if not missing and not extra:
        return

    details = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if extra:
        details.append("extra: " + ", ".join(extra))
    joined_details = "; ".join(details)
    raise ConfigError(
        f"{SUNO_LYRICS_JSON_FILENAME} names must match prompt entry names: {lyrics_path} ({joined_details})"
    )


def _resolve_prompts(patterns_path: Path) -> _ResolvedPrompts:
    """config + patterns.yaml を解決し、md / JSON 双方の共通中間表現を返す."""
    suno = load_skill_config("suno")
    # JSON 反映は channel override に明示されたキーのみ gating する (#900、A 案)。merged config では
    # default.yaml の既定値と区別できないため、override 単体を別途読む。
    override = load_channel_override("suno")
    advanced_json_fields = _build_advanced_json_fields(override)
    fb_genre, fb_exclude = _collect_video_analysis_presets()

    genre_line = suno.get("genre_line", "") or fb_genre
    mood_descriptors = suno.get("mood_descriptors", "")
    exclude_styles = suno.get("exclude_styles", "") or fb_exclude
    style_variants = suno.get("style_variants", {})
    style_influence = suno.get("style_influence", 50)
    weirdness = suno.get("weirdness", 50)

    style_variation = _resolve_style_variation(suno.get("style_variation"))

    base_parts = [genre_line]
    if mood_descriptors:
        base_parts.append(mood_descriptors)
    base_style = ", ".join(base_parts)

    with open(patterns_path) as f:
        data = yaml.safe_load(f)

    title = data.get("title", "Suno Prompts")
    patterns = data.get("patterns", [])

    vocal_keywords = ("vocals", "vocal", "singing", "rap", "sings", "sung")
    auto_vocal = any(kw in genre_line.lower() for kw in vocal_keywords)
    mode = data.get("mode", "vocal" if auto_vocal else "instrumental")
    is_vocal = mode == "vocal"
    external_lyrics_path = patterns_path.parent / SUNO_LYRICS_JSON_FILENAME
    has_external_lyrics = is_vocal and external_lyrics_path.exists()
    if is_vocal and not has_external_lyrics:
        raise ConfigError(
            f"{SUNO_LYRICS_JSON_FILENAME} is required for vocal mode. "
            f"Run /suno-lyric first and write: {external_lyrics_path}"
        )
    external_lyrics = _load_external_lyrics(external_lyrics_path) if is_vocal else {}

    resolved: list[_ResolvedPattern] = []
    expected_external_lyrics_names: set[str] = set()
    entry_index = 0
    for pattern in patterns:
        tempo = pattern.get("tempo")
        style_key = pattern.get("style")

        # Per-pattern style variant override
        has_explicit_variant = bool(style_key and style_key in style_variants)
        if has_explicit_variant:
            variant = style_variants[style_key]
            effective_style = variant["genre_line"]
            style_label = f" [{style_key}: {variant['name']}]"
        else:
            effective_style = base_style
            style_label = ""

        scenes = pattern["scenes"]
        raw_lyrics = pattern.get("lyrics")
        fallback_lyrics = raw_lyrics.rstrip() if raw_lyrics else ""
        base_name = f"{pattern['name_jp']} — {pattern['name_en']}"
        multi = len(scenes) > 1
        lyrics_by_scene = []
        style_lines = []
        for j in range(1, len(scenes) + 1):
            entry_name = f"{base_name} (Variation {j})" if multi else base_name
            if has_external_lyrics:
                expected_external_lyrics_names.add(entry_name)
                lyrics_by_scene.append(external_lyrics.get(entry_name, ""))
            else:
                lyrics_by_scene.append(fallback_lyrics)

            descriptor = ""
            if style_variation.enabled and not has_explicit_variant:
                descriptor = _variation_descriptor(entry_index, style_variation.sequence)
            style_lines.append(_style_line(tempo, effective_style, descriptor))
            # Explicit variants keep their override style but still reserve the YAML entry position.
            entry_index += 1

        resolved.append(
            _ResolvedPattern(
                name_jp=pattern["name_jp"],
                name_en=pattern["name_en"],
                style_label=style_label,
                style_lines=style_lines,
                scenes=scenes,
                lyrics_by_scene=lyrics_by_scene,
            )
        )

    if has_external_lyrics:
        _validate_external_lyrics_names(
            lyrics_path=external_lyrics_path,
            expected_names=expected_external_lyrics_names,
            actual_names=set(external_lyrics),
        )

    # インストモードのみ: yaml `tracks:` (コレクション上書き) > config `tracks_per_collection` の順で曲数を解決し、
    # ceil(N/2) と yaml の entry 数 (scene 行数の合計) が一致するか fail-loud で検証する。
    # ボーカルモードは曲数定義が異なるため (1 prompt = 1 ベストを選曲、別途整理予定) 検証しない。
    # tracks_per_collection が未指定の旧運用は silent skip して後方互換を保つ。
    if not is_vocal:
        tracks_override = data.get("tracks")
        tracks_per_collection = tracks_override if tracks_override is not None else suno.get("tracks_per_collection")
        if tracks_per_collection is not None:
            entries_count = sum(len(p.scenes) for p in resolved)
            _validate_instrumental_track_count(patterns_path, entries_count, tracks_per_collection)

    # 全曲ユニーク title: Suno UI Song Title 欄に注入される最終 name の重複を fail-loud で弾く。
    # インスト・ボーカル両モード一律 (詳細は `_validate_unique_titles` の docstring 参照)。
    _validate_unique_titles(patterns_path, _entry_names_from_resolved(resolved))

    return _ResolvedPrompts(
        title=title,
        is_vocal=is_vocal,
        style_influence=style_influence,
        weirdness=weirdness,
        exclude_styles=exclude_styles,
        advanced_json_fields=advanced_json_fields,
        patterns=resolved,
    )


def generate(patterns_path: Path) -> str:
    resolved = _resolve_prompts(patterns_path)

    lines = [
        f"# Suno Prompts — {resolved.title}",
        "",
        "## SunoAI 推奨設定",
        "",
        "| パラメータ | 値 |",
        "|-----------|-----|",
        "| Mode | Custom |",
        f"| Weirdness | {resolved.weirdness}% |",
        f"| Style Influence | {resolved.style_influence}% |",
        f"| Instrumental | {'OFF（ボーカルモード）' if resolved.is_vocal else 'ON（インストモード）'} |",
        f"| Lyrics | {'各パターンの Lyrics 欄を投入' if resolved.is_vocal else '(空)'} |",
        "",
        "---",
    ]

    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    for i, pattern in enumerate(resolved.patterns):
        label = labels[i] if i < len(labels) else str(i + 1)

        lines.append("")
        lines.append(f"## Pattern {label}: {pattern.name_jp} — {pattern.name_en}{pattern.style_label}")

        for j, scene in enumerate(pattern.scenes, 1):
            lines.append("")
            lines.append(f"### Variation {j}")
            lines.append("**Styles:**")
            lines.append("```")
            lines.append(pattern.style_lines[j - 1])
            lines.append(scene)
            lines.append("```")

            if resolved.exclude_styles:
                lines.append("")
                lines.append("**Exclude Styles:**")
                lines.append("```")
                lines.append(resolved.exclude_styles)
                lines.append("```")

            lyrics = pattern.lyrics_by_scene[j - 1]
            if resolved.is_vocal and lyrics:
                lines.append("")
                lines.append("**Lyrics:**")
                lines.append("```")
                lines.append(lyrics)
                lines.append("```")

        lines.append("")
        lines.append("---")

    return "\n".join(lines) + "\n"


def build_prompt_entries(patterns_path: Path) -> list[dict]:
    """拡張へ配信する `[{name, style, lyrics}]` を md と同じ部品から派生させる.

    scene 単位で 1 entry に分割し、複数 scene を持つ pattern には
    name に ` (Variation N)` を付与する。style は md の Styles ブロック
    （`<tempo>, <style>,` 行 + scene 行）と同一文字列を改行で結合する。

    品質ルール (#904):
    - 5 要素順序の簡易検証 (警告)
    - Style 文字数上限チェック (警告)
    - 禁止アーティスト名チェック (エラー)
    - auto_lyrics_structure による歌詞構造の自動補強

    Style 重複検証 (#1456): 全 entry の Style 文が完全一致する組があれば警告する
    """
    resolved = _resolve_prompts(patterns_path)
    suno = load_skill_config("suno")
    style_char_limit = suno.get("style_char_limit", 120)
    banned_artists = suno.get("banned_artists", [])
    auto_lyrics = suno.get("auto_lyrics_structure", False)

    report = QualityReport()

    # 5 要素順序チェックは genre_line（ユーザーが config に書く部分）を 1 回だけ検証する。
    # Styles 第 1 行の先頭は `_style_line` が tempo を置くため full_style では false positive になる。
    genre_line = suno.get("genre_line", "")
    if genre_line:
        report.warnings.extend(validate_5_element_order(genre_line))

    entries: list[dict] = []
    for pattern in resolved.patterns:
        base_name = f"{pattern.name_jp} — {pattern.name_en}"
        multi = len(pattern.scenes) > 1
        for j, scene in enumerate(pattern.scenes, 1):
            name = f"{base_name} (Variation {j})" if multi else base_name
            full_style = f"{pattern.style_lines[j - 1]}\n{scene}"

            # Quality rules: Style テキストの検証 (#904)
            # style_char_limit と banned_artists は完成形の full_style を検証する。
            # 5 要素順序チェックは genre_line（ユーザーが config に書く部分）を検証する。
            # Styles 第 1 行の先頭は `_style_line` が tempo を置くため、
            # full_style での先頭テンポ検知は false positive になる。
            report.warnings.extend(validate_style_char_limit(full_style, limit=style_char_limit))
            report.errors.extend(validate_banned_artists(full_style, banned_artists))

            # auto_lyrics_structure: 歌詞構造の自動補強 (#904)
            lyrics = pattern.lyrics_by_scene[j - 1] if resolved.is_vocal else ""
            if auto_lyrics:
                lyrics = apply_auto_lyrics_structure(lyrics, is_vocal=resolved.is_vocal)

            entry = {
                "name": name,
                "style": full_style,
                "lyrics": lyrics,
            }
            # More Options 3 フィールド (#900)。channel override に明示されたキーのみ collection
            # スコープで全 entry に載せる。0 や "" の falsy 値も有効値なので無条件に反映する
            # (gating は resolve 段で `key in override` 済み)。
            entry.update(resolved.advanced_json_fields)
            entries.append(entry)

    style_counts = Counter(entry["style"] for entry in entries)
    for style_text, count in style_counts.items():
        if count > 1:
            duplicated_names = ", ".join(e["name"] for e in entries if e["style"] == style_text)
            report.warnings.append(
                f"Duplicate Style text across {count} entries ({duplicated_names}): {style_text.splitlines()[0]}"
            )

    # Quality report: エラーがあれば fail-loud、警告は stderr に出力
    if report.has_warnings:
        for w in report.warnings:
            print(f"[WARN] {w}", file=sys.stderr)
    if report.has_errors:
        raise ConfigError("品質ルール違反を検出しました:\n" + "\n".join(f"  - {e}" for e in report.errors))

    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Generate suno-prompts.md from config/skills/suno.yaml + suno-patterns.yaml",
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="collection path or patterns.yaml path (default: CWD/20-documentation/suno-patterns.yaml)",
    )
    args = parser.parse_args()

    path = args.path or Path.cwd()
    patterns_path = path if path.is_file() else path / DOCUMENTATION_DIRNAME / SUNO_PATTERNS_FILENAME

    if not patterns_path.exists():
        parser.error(f"{patterns_path} not found")

    md_path = patterns_path.parent / SUNO_PROMPTS_MD_FILENAME
    md_path.write_text(generate(patterns_path))
    print(f"Generated: {md_path}")

    json_path = patterns_path.parent / SUNO_PROMPTS_JSON_FILENAME
    entries = build_prompt_entries(patterns_path)
    json_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated: {json_path}")


if __name__ == "__main__":
    main()
