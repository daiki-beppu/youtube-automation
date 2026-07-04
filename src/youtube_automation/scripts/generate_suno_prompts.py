#!/usr/bin/env python3
"""Generate suno-prompts.md from config/skills/suno.yaml + suno-patterns.yaml."""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

from youtube_automation.scripts.suno_artifacts import (
    DOCUMENTATION_DIRNAME,
    SUNO_LYRICS_JSON_FILENAME,
    SUNO_PATTERNS_FILENAME,
    SUNO_PROMPTS_JSON_FILENAME,
    SUNO_PROMPTS_MD_FILENAME,
)
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.skill_config import load_channel_override, load_skill_config
from youtube_automation.utils.suno_artifact_validation import (
    positive_integer_issue,
    require_instrumental_track_count,
    require_matching_suno_lyrics_names,
    require_unique_entry_names,
    suno_prompt_entry_names,
    surrounding_whitespace_issue,
)
from youtube_automation.utils.suno_effective_config import infer_suno_mode, resolve_suno_config
from youtube_automation.utils.suno_lyrics import load_suno_lyrics_by_name

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


def _style_line(tempo: str | None, effective_style: str) -> str:
    """Styles 欄の 1 行目（`<tempo>, <style>,`）を組み立てる共有部品.

    md 出力と JSON 出力で同一の文字列を使うことでドリフトを防ぐ。
    """
    parts = [tempo] if tempo else []
    parts.append(effective_style)
    return ", ".join(parts) + ","


@dataclass
class _ResolvedPattern:
    name_jp: str
    name_en: str
    style_label: str
    style_line: str
    entry_names: list[str]
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


def _entry_names_from_resolved(resolved: list[_ResolvedPattern]) -> list[str]:
    """`build_prompt_entries` と同一ロジックで最終的な entry.name のみを構築する.

    Suno UI Song Title 欄へ注入される値 (suno-helper 拡張は `entry.title ?? entry.name` を読む)
    の SSOT。`_resolve_prompts()` が scene variation と tracks_per_pattern を反映した
    展開済み entry_names を作る。
    """
    names: list[str] = []
    for p in resolved:
        names.extend(p.entry_names)
    return names


def _load_external_lyrics(lyrics_path: Path) -> dict[str, str]:
    """`suno-lyrics.json` から entry name -> lyrics を読み込む.

    `/suno-lyric` は lyrics 専任で、`/suno` がここで Style と結合する。
    vocal mode のファイル必須チェックは呼び出し元で行う。
    """
    return load_suno_lyrics_by_name(lyrics_path)


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


def _resolve_vocal_tracks_per_pattern(suno: dict) -> int:
    value = suno.get("tracks_per_pattern")
    issue = positive_integer_issue(value, "config/skills/suno.yaml::tracks_per_pattern")
    if issue is not None:
        raise ConfigError(issue)
    return cast(int, value)


def _expand_scenes_for_entries(scenes: list[str], tracks_per_pattern: int) -> list[str]:
    if tracks_per_pattern == 1:
        return scenes
    return [scene for scene in scenes for _ in range(tracks_per_pattern)]


def _resolve_prompts(patterns_path: Path) -> _ResolvedPrompts:
    """config + patterns.yaml を解決し、md / JSON 双方の共通中間表現を返す."""
    suno = load_skill_config("suno")
    # JSON 反映は channel override に明示されたキーのみ gating する (#900、A 案)。merged config では
    # default.yaml の既定値と区別できないため、override 単体を別途読む。
    override = load_channel_override("suno")
    advanced_json_fields = _build_advanced_json_fields(override)
    resolved_suno = resolve_suno_config(suno)

    genre_line = resolved_suno.genre_line
    mood_descriptors = suno.get("mood_descriptors", "")
    exclude_styles = resolved_suno.exclude_styles
    style_variants = suno.get("style_variants", {})
    style_influence = suno.get("style_influence", 50)
    weirdness = suno.get("weirdness", 50)

    base_parts = [genre_line]
    if mood_descriptors:
        base_parts.append(mood_descriptors)
    base_style = ", ".join(base_parts)

    with open(patterns_path) as f:
        data = yaml.safe_load(f)

    title = data.get("title", "Suno Prompts")
    patterns = data.get("patterns", [])

    mode = data.get("mode", infer_suno_mode(genre_line))
    is_vocal = mode == "vocal"
    tracks_per_pattern = _resolve_vocal_tracks_per_pattern(suno) if is_vocal else 1
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
    for pattern_index, pattern in enumerate(patterns, 1):
        tempo = pattern.get("tempo")
        style_key = pattern.get("style")
        name_jp = pattern["name_jp"]
        name_en = pattern["name_en"]
        _require_pattern_name_without_padding(patterns_path, pattern_index, "name_jp", name_jp)
        _require_pattern_name_without_padding(patterns_path, pattern_index, "name_en", name_en)

        # Per-pattern style variant override
        if style_key and style_key in style_variants:
            variant = style_variants[style_key]
            effective_style = variant["genre_line"]
            style_label = f" [{style_key}: {variant['name']}]"
        else:
            effective_style = base_style
            style_label = ""

        scenes = pattern["scenes"]
        entry_names = suno_prompt_entry_names(
            name_jp,
            name_en,
            len(scenes),
            tracks_per_pattern=tracks_per_pattern,
        )
        entry_scenes = _expand_scenes_for_entries(scenes, tracks_per_pattern)
        raw_lyrics = pattern.get("lyrics")
        fallback_lyrics = raw_lyrics.rstrip() if raw_lyrics else ""
        lyrics_by_scene = []
        for entry_name in entry_names:
            if has_external_lyrics:
                expected_external_lyrics_names.add(entry_name)
                lyrics_by_scene.append(external_lyrics.get(entry_name, ""))
            else:
                lyrics_by_scene.append(fallback_lyrics)

        resolved.append(
            _ResolvedPattern(
                name_jp=name_jp,
                name_en=name_en,
                style_label=style_label,
                style_line=_style_line(tempo, effective_style),
                entry_names=entry_names,
                scenes=entry_scenes,
                lyrics_by_scene=lyrics_by_scene,
            )
        )

    if has_external_lyrics:
        require_matching_suno_lyrics_names(
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
            require_instrumental_track_count(patterns_path, entries_count, tracks_per_collection)

    # 全曲ユニーク title: Suno UI Song Title 欄に注入される最終 name の重複を fail-loud で弾く。
    # インスト・ボーカル両モード一律で、後工程の同名 clip 追跡不能を生成時に弾く。
    require_unique_entry_names(patterns_path, _entry_names_from_resolved(resolved))

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

        for entry_name, scene, lyrics in zip(
            pattern.entry_names,
            pattern.scenes,
            pattern.lyrics_by_scene,
            strict=True,
        ):
            lines.append("")
            lines.append(f"### {entry_name}")
            lines.append("**Styles:**")
            lines.append("```")
            lines.append(pattern.style_line)
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

    `_resolve_prompts()` が作る展開済み entry_names 単位で出力する。
    複数 scene は `(Variation N)`、tracks_per_pattern > 1 は `(Take N)` を含む
    name になり、style は md の Styles ブロック（`<tempo>, <style>,` 行 + scene 行）
    と同一文字列を改行で結合する。

    品質ルール (#904):
    - 5 要素順序の簡易検証 (警告)
    - Style 文字数上限チェック (警告)
    - 禁止アーティスト名チェック (エラー)
    - auto_lyrics_structure による歌詞構造の自動補強
    """
    resolved = _resolve_prompts(patterns_path)
    suno = load_skill_config("suno")
    style_char_limit = suno.get("style_char_limit", 120)
    banned_artists = suno.get("banned_artists", [])
    auto_lyrics = suno.get("auto_lyrics_structure", False)

    report = QualityReport()

    # 5 要素順序チェックは genre_line（ユーザーが config に書く部分）を 1 回だけ検証する。
    # pattern.style_line の先頭は `_style_line` が tempo を置くため full_style では false positive になる。
    genre_line = suno.get("genre_line", "")
    if genre_line:
        report.warnings.extend(validate_5_element_order(genre_line))

    entries: list[dict] = []
    for pattern in resolved.patterns:
        for name, scene, lyrics_source in zip(
            pattern.entry_names,
            pattern.scenes,
            pattern.lyrics_by_scene,
            strict=True,
        ):
            full_style = f"{pattern.style_line}\n{scene}"

            # Quality rules: Style テキストの検証 (#904)
            # style_char_limit と banned_artists は完成形の full_style を検証する。
            # 5 要素順序チェックは genre_line（ユーザーが config に書く部分）を検証する。
            # pattern.style_line の先頭は `_style_line` が tempo を置くため、
            # full_style での先頭テンポ検知は false positive になる。
            report.warnings.extend(validate_style_char_limit(full_style, limit=style_char_limit))
            report.errors.extend(validate_banned_artists(full_style, banned_artists))

            # auto_lyrics_structure: 歌詞構造の自動補強 (#904)
            lyrics = lyrics_source if resolved.is_vocal else ""
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
