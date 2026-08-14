#!/usr/bin/env python3
"""Generate suno-prompts.md from config/skills/suno.yaml + suno-patterns.yaml."""

import argparse
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from youtube_automation.configuration.skills import load_channel_override, load_skill_config
from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.suno import prompt_resolution
from youtube_automation.domains.suno.downloaded.models import (
    DOCUMENTATION_DIRNAME,
    SUNO_PATTERNS_FILENAME,
    SUNO_PROMPTS_JSON_FILENAME,
    SUNO_PROMPTS_MD_FILENAME,
)
from youtube_automation.domains.suno.downloaded.validation import (
    suno_prompt_entry_names,
    surrounding_whitespace_issue,
)
from youtube_automation.domains.suno.lyrics import load_suno_lyrics_by_name
from youtube_automation.infrastructure.filesystem import write_text_files_transactionally

# ---------------------------------------------------------------------------
# Quality rules (#904): suno-bgm ベースの品質ガード
# ---------------------------------------------------------------------------

# Style text の 5 要素順序: ジャンル名 → 音響特性 → キー楽器 → リズム/ベース → テンポ
# 厳密な順序検証は不可能（自然言語のため）だが、テンポ語が先頭付近にある場合は警告する
_TEMPO_WORDS = frozenset({"very slow", "slow", "gentle", "moderate", "lively", "fast", "uptempo", "downtempo"})


def validate_style_char_limit(
    style_text: str, *, limit: int = prompt_resolution.DEFAULT_FULL_STYLE_CHAR_LIMIT
) -> list[str]:
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


def _style_line(tempo: str | None, effective_style: str, variation_descriptor: str) -> str:
    """Styles 欄の 1 行目（`<tempo>, <style>,`）を組み立てる共有部品.

    md 出力と JSON 出力で同一の文字列を使うことでドリフトを防ぐ。
    """
    parts = [tempo] if tempo else []
    parts.append(effective_style)
    if variation_descriptor:
        parts.append(variation_descriptor)
    return ", ".join(parts) + ","


def _variation_descriptor(entry_index: int, sequence: Sequence[str]) -> str:
    if entry_index == 0 or not sequence:
        return ""
    return sequence[(entry_index - 1) % len(sequence)]


@dataclass
class _ResolvedPattern:
    name_jp: str
    name_en: str
    style_label: str
    entry_names: list[str]
    style_lines: list[str]  # scenes と同じ長さ。entry ごとの Styles 第 1 行 (#1456)
    scenes: Sequence[str]
    lyrics_by_scene: list[str]  # scenes と同じ長さ。各値は rstrip 済み。歌詞が無ければ ""


def _duration_filter_from_config(suno: dict) -> dict:
    raw = suno.get("duration_filter", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("config/skills/suno.yaml::duration_filter must be a mapping")
    min_sec = raw.get("min_sec", 60)
    max_sec = raw.get("max_sec", 300)
    if (
        isinstance(min_sec, bool)
        or isinstance(max_sec, bool)
        or not isinstance(min_sec, (int, float))
        or not isinstance(max_sec, (int, float))
        or not math.isfinite(min_sec)
        or not math.isfinite(max_sec)
    ):
        raise ConfigError("config/skills/suno.yaml::duration_filter min_sec/max_sec must be finite numeric")
    if min_sec < 0 or max_sec < 0 or min_sec > max_sec:
        raise ConfigError("config/skills/suno.yaml::duration_filter must satisfy 0 <= min_sec <= max_sec")
    return {"min_sec": min_sec, "max_sec": max_sec}


@dataclass
class _GeneratedPrompts:
    title: str
    is_vocal: bool
    style_influence: int
    weirdness: int
    exclude_styles: str
    full_style_char_limit: int
    # channel override に明示設定された More Options フィールドのみを保持する (#900)。
    # collection スコープ: 全 entry に同じ値が載る。未設定キーは dict に含めない。
    advanced_json_fields: Mapping[str, object]
    patterns: list[_ResolvedPattern]


def _entry_names_from_resolved(resolved: list[_ResolvedPattern]) -> list[str]:
    """`build_prompt_entries` と同一ロジックで最終的な entry.name のみを構築する.

    Suno UI Song Title 欄へ注入される値 (suno-helper 拡張は `entry.title ?? entry.name` を読む)
    の SSOT。`_resolve_prompts()` が scene variation を反映した entry_names を作る。
    """
    names: list[str] = []
    for p in resolved:
        names.extend(p.entry_names)
    return names


def _require_pattern_name_without_padding(
    patterns_path: Path,
    pattern_index: int,
    field_name: str,
    value: str,
) -> None:
    issue = surrounding_whitespace_issue(
        source_name=SUNO_PATTERNS_FILENAME,
        field_path=f"patterns[{pattern_index}].{field_name}",
        value=value,
    )
    if issue is not None:
        raise ConfigError(f"{patterns_path}: {issue}")


def _resolve_prompts(patterns_path: Path) -> _GeneratedPrompts:
    resolution = prompt_resolution.resolve_from_path(
        patterns_path,
        skill_config_loader=load_skill_config,
        channel_override_loader=load_channel_override,
        lyrics_loader=load_suno_lyrics_by_name,
    )
    resolved: list[_ResolvedPattern] = []
    expected_external_lyrics_names: set[str] = set()
    entry_index = 0
    for pattern_index, pattern in enumerate(resolution.patterns, 1):
        tempo = pattern.get("tempo")
        style_key = pattern.get("style")
        name_jp = pattern["name_jp"]
        name_en = pattern["name_en"]
        _require_pattern_name_without_padding(patterns_path, pattern_index, "name_jp", name_jp)
        _require_pattern_name_without_padding(patterns_path, pattern_index, "name_en", name_en)

        variant = prompt_resolution.resolve_style_variant(resolution, style_key)
        has_explicit_variant = variant is not None
        if variant is not None:
            effective_style = variant["genre_line"]
            style_label = f" [{style_key}: {variant['name']}]"
        else:
            effective_style = resolution.base_style
            style_label = ""

        scenes = pattern["scenes"]
        entry_names = suno_prompt_entry_names(name_jp, name_en, len(scenes))
        entry_scenes = scenes
        raw_lyrics = pattern.get("lyrics")
        fallback_lyrics = raw_lyrics.rstrip() if raw_lyrics else ""
        lyrics_by_scene = []
        style_lines = []
        for entry_name in entry_names:
            if resolution.has_external_lyrics:
                expected_external_lyrics_names.add(entry_name)
                lyrics_by_scene.append(resolution.external_lyrics.get(entry_name, ""))
            else:
                lyrics_by_scene.append(fallback_lyrics)

            descriptor = ""
            if resolution.style_variation.enabled and not has_explicit_variant:
                descriptor = _variation_descriptor(entry_index, resolution.style_variation.sequence)
            style_lines.append(_style_line(tempo, effective_style, descriptor))
            # Explicit variants keep their override style but still reserve the YAML entry position.
            entry_index += 1

        resolved.append(
            _ResolvedPattern(
                name_jp=name_jp,
                name_en=name_en,
                style_label=style_label,
                entry_names=entry_names,
                style_lines=style_lines,
                scenes=entry_scenes,
                lyrics_by_scene=lyrics_by_scene,
            )
        )

    entry_names = _entry_names_from_resolved(resolved)
    prompt_resolution.validate_generated_prompts(
        resolution,
        entry_names=entry_names,
        entries_count=sum(len(pattern.scenes) for pattern in resolved),
        expected_external_lyrics_names=expected_external_lyrics_names,
    )

    return _GeneratedPrompts(
        title=resolution.title,
        is_vocal=resolution.is_vocal,
        style_influence=resolution.style_influence,
        weirdness=resolution.weirdness,
        exclude_styles=resolution.exclude_styles,
        full_style_char_limit=resolution.full_style_char_limit,
        advanced_json_fields=resolution.advanced_json_fields,
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

        for entry_name, scene, lyrics, style_line in zip(
            pattern.entry_names,
            pattern.scenes,
            pattern.lyrics_by_scene,
            pattern.style_lines,
            strict=True,
        ):
            lines.append("")
            lines.append(f"### {entry_name}")
            lines.append("**Styles:**")
            lines.append("```")
            lines.append(style_line)
            lines.append(scene)
            lines.append("```")

            if resolved.exclude_styles:
                lines.append("")
                lines.append("**Exclude Styles:**")
                lines.append("```")
                lines.append(resolved.exclude_styles)
                lines.append("```")

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

    `_resolve_prompts()` が作る entry_names 単位で出力する。
    複数 scene は `(Variation N)` を含む name になり、style は md の
    Styles ブロック（`<tempo>, <style>,` 行 + scene 行）と同一文字列を
    改行で結合する。

    品質ルール (#904):
    - 5 要素順序の簡易検証 (警告)
    - Style 文字数上限チェック (警告)
    - 禁止アーティスト名チェック (エラー)
    - auto_lyrics_structure による歌詞構造の自動補強

    Style 重複検証 (#1456): 全 entry の Style 文が完全一致する組があれば警告する
    """
    resolved = _resolve_prompts(patterns_path)
    suno = load_skill_config("suno")
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
        for name, scene, lyrics_source, style_line in zip(
            pattern.entry_names,
            pattern.scenes,
            pattern.lyrics_by_scene,
            pattern.style_lines,
            strict=True,
        ):
            full_style = f"{style_line}\n{scene}"

            # Quality rules: Style テキストの検証 (#904)
            # full_style_char_limit と banned_artists は完成形の full_style を検証する。
            # 5 要素順序チェックは genre_line（ユーザーが config に書く部分）を検証する。
            # Styles 第 1 行の先頭は `_style_line` が tempo を置くため、
            # full_style での先頭テンポ検知は false positive になる。
            report.warnings.extend(validate_style_char_limit(full_style, limit=resolved.full_style_char_limit))
            report.errors.extend(validate_banned_artists(full_style, banned_artists))

            # auto_lyrics_structure: 歌詞構造の自動補強 (#904)
            lyrics = lyrics_source
            if auto_lyrics:
                lyrics = apply_auto_lyrics_structure(lyrics, is_vocal=resolved.is_vocal)

            entry = {
                "name": name,
                "style": full_style,
                "lyrics": lyrics,
            }
            # More Options 3 フィールド (#900)。channel override に明示されたキーのみ collection
            # スコープで全 entry に載せる。0 の falsy 値も有効値なので無条件に反映する
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

    entries = build_prompt_entries(patterns_path)
    markdown = generate(patterns_path)
    payload = {
        "entries": entries,
        "duration_filter": _duration_filter_from_config(load_skill_config("suno")),
    }

    md_path = patterns_path.parent / SUNO_PROMPTS_MD_FILENAME
    json_path = patterns_path.parent / SUNO_PROMPTS_JSON_FILENAME
    write_text_files_transactionally(
        {
            md_path: markdown,
            json_path: json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        }
    )
    print(f"Generated: {md_path}")
    print(f"Generated: {json_path}")


if __name__ == "__main__":
    main()
