#!/usr/bin/env python3
"""
YouTube メタデータ自動生成ユーティリティ
collections/ ディレクトリの構造を解析し、YouTube用メタデータを自動生成

Features:
- WAVファイル自動解析（afinfo使用）
- タイムスタンプ自動計算
- config/channel/*.json ベースのテンプレート適用
"""

import json
import logging
import re
import string
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import ValidationError

from .audio_formats import AUDIO_EXTS
from .skill_config import load_skill_config
from .time_utils import format_duration_display, format_duration_short, format_timestamp

logger = logging.getLogger(__name__)

# `pattern-b1-` のような variation 接尾辞も許容する（`_clean_track_title` のサニタイズ規約と同じ）。
# 末尾 `(?![a-z])` で `pattern-e-` のような範囲外文字は明示的に reject する。
_PATTERN_KEY_RE = re.compile(r"^\d+-pattern-([a-d])(?![a-z])", re.IGNORECASE)


def _extract_pattern_key(filename: str) -> str | None:
    """ファイル名から pattern_key（'a'|'b'|'c'|'d'）を抽出する。マッチしなければ None."""
    m = _PATTERN_KEY_RE.match(filename)
    if not m:
        return None
    return m.group(1).lower()


def _referenced_placeholders(template: str) -> set[str]:
    """format テンプレートが参照するフィールド名の集合を返す（`{a.b}` / `{a[0]}` は `a` に正規化）."""
    referenced: set[str] = set()
    for _literal, field_name, _spec, _conv in string.Formatter().parse(template):
        if field_name:
            referenced.add(field_name.split(".")[0].split("[")[0])
    return referenced


def format_title_template(template: str, values: Dict[str, str], *, context: str) -> str:
    """title テンプレートを整形する。未知プレースホルダは actionable な ValidationError にする.

    `str.format()` をそのまま呼ぶと、テンプレートが提供キー以外のプレースホルダ
    （例: `{adjective}`）を含むときに opaque な `KeyError` を送出し、upload 全体が
    深部でクラッシュする（#574）。本ヘルパーは事前に未知プレースホルダを検出し、
    「使用不可プレースホルダ名 + 許可キー一覧」を含む `ValidationError` に変換する。

    Args:
        template: format 文字列
        values: 許可キー → 値の dict（このキー集合のみ許容）
        context: エラーメッセージに添える文脈（どのテンプレートか）

    Raises:
        ValidationError: テンプレートが `values` に無いプレースホルダを含むとき。
    """
    allowed = set(values)
    unknown = _referenced_placeholders(template) - allowed
    if unknown:
        raise ValidationError(
            f"{context}: 使用できないプレースホルダ {sorted(unknown)} が含まれています。\n"
            f"→ 使用可能なキー: {sorted(allowed)}\n"
            f"→ テンプレート: {template}"
        )
    return template.format(**values)


@dataclass(frozen=True)
class SceneTitleViolation:
    """多言語タイトルの codepoint 超過違反（100 codepoint 上限）."""

    lang: str
    length: int
    title: str
    template: str


# ---------------------------------------------------------------------------
# Shorts 用 module-level helpers
# ---------------------------------------------------------------------------
# Shorts の description / localizations は 3 経路（`generate_shorts_metadata`,
# `bulk_update_short_localizations`, テストの parity 比較）から呼ばれるため、
# クラスメソッドではなく module-level helper にして単一の事実源にする
# （AI-NEW-shorts-localizations-DRY / AI-NEW-bulk-update-loc-L161 対応）。


def _format_short_duration_phrase(config) -> str:
    """`config.audio.target_duration_min` から「2 hours」等の文字列を組み立てる.

    `target_duration_min is None` のときは `round(min / 60)` で TypeError に
    ならないよう "Full collection" にフォールバックする（plan §152）。
    """
    target_min = config.audio.target_duration_min
    if target_min is None:
        return "Full collection"
    hours = round(target_min / 60)
    return f"{hours} hour" if hours == 1 else f"{hours} hours"


def build_short_description(
    config,
    *,
    collection_name: str,
    cc_video_url: str,
) -> str:
    """Shorts デフォルト description（fallback と default 両方で使う共通組み立て）.

    `cc_video_url` が空なら `♫` 行を含めない（plan 要件 #3 / アンチパターン #5）。
    末尾に `#Shorts` を必ず付ける（YouTube 検出最適化）。
    """
    duration_phrase = _format_short_duration_phrase(config)
    parts = [
        f"{collection_name} ({duration_phrase}) | {config.meta.channel_name}",
        "",
    ]
    if cc_video_url:
        parts.append(f"♫ Full → {cc_video_url}")
        parts.append("")
    parts.append("#Shorts")
    return "\n".join(parts)


def build_short_localizations(
    config,
    *,
    collection_name: str,
    theme: str,
    cc_video_url: str,
) -> Dict[str, Dict[str, str]]:
    """Shorts 用 localizations を生成する（`generate_shorts_metadata` / bulk_update 共通）.

    - `short_title_template` を持たない言語は skip（plan 要件 #5）.
    - `short_description_template` が無い言語は `build_short_description` フォールバック.
    - `theme` を必須引数にして、bulk_update が theme 抜き(`""`) で初回 upload の
      タイトルを破壊する事故（AI-NEW-bulk-update-loc-L161）を構造的に防ぐ.
    """
    loc_config = config.localizations.data
    if not loc_config:
        return {}

    channel_name = config.meta.channel_name
    default_tagline = config.meta.tagline
    localizations: Dict[str, Dict[str, str]] = {}

    for lang in loc_config.get("supported_languages", []):
        lang_data = loc_config.get("languages", {}).get(lang, {})
        title_tpl = lang_data.get("short_title_template")
        if not title_tpl:
            continue

        loc_title = title_tpl.format(
            theme=theme,
            channel_name=channel_name,
            collection_name=collection_name,
        )

        desc_data = lang_data.get("description", {}) or {}
        tagline = desc_data.get("tagline", default_tagline)
        desc_tpl = lang_data.get("short_description_template")
        if desc_tpl:
            loc_desc = desc_tpl.format(
                collection_name=collection_name,
                channel_name=channel_name,
                cc_video_url=cc_video_url,
                tagline=tagline,
            )
        else:
            loc_desc = build_short_description(
                config,
                collection_name=collection_name,
                cc_video_url=cc_video_url,
            )

        localizations[lang] = {
            "title": loc_title,
            "description": loc_desc[:5000],
        }
    return localizations


def validate_scene_phrases(
    scene_phrases: Dict[str, str],
    config,
    scene_emoji: str = "",
) -> List[SceneTitleViolation]:
    """scene_phrases を localizations の全言語で試算し、100 codepoint 超過を一括検出する.

    `/video-description` など `workflow-state.json` への書き込み前に呼ぶことで、
    アップロード時 preflight まで超過発覚を遅らせず、全言語分をまとめて検査できる.

    Args:
        scene_phrases: {"en": ..., "ja": ..., ...} コレクション別の感情フレーズ翻訳
        config: `load_config()` の戻り値

    Returns:
        違反のリスト。空なら全言語 100 codepoint 以内.

    Raises:
        ValueError: scene_phrases が一部言語で欠落している場合、または
            `localizations.json` に `title_template` が無い言語がある場合.
    """
    loc_config = config.localizations.data
    supported = loc_config.get("supported_languages", [])

    missing_langs = [lang for lang in supported if not scene_phrases.get(lang)]
    if missing_langs:
        raise ValueError(
            "scene_phrases に翻訳が不足しています。"
            f"不足言語: {missing_langs}\n"
            "→ コレクションの workflow-state.json に "
            "`scene_phrases: {en: ..., ja: ..., ...}` を populate してください。\n"
            "→ 既存例: collections/live/20260322-rjn-city-collection/workflow-state.json"
        )

    desc_metadata = config.content.descriptions.metadata
    best_for_line = desc_metadata.get("best_for", "Study, Focus, Late Night")

    violations: List[SceneTitleViolation] = []
    for lang in supported:
        lang_data = loc_config["languages"].get(lang, {})
        title_tpl = lang_data.get("title_template")
        if not title_tpl:
            raise ValueError(f"localizations.json: language '{lang}' に title_template が無い")
        activities = lang_data.get("activities", best_for_line)
        scene = scene_phrases[lang]
        title = format_title_template(
            title_tpl,
            {"scene_phrase": scene, "activities": activities, "scene_emoji": scene_emoji},
            context=f"localizations.json: language '{lang}' の title_template",
        )
        if len(title) > 100:
            violations.append(
                SceneTitleViolation(
                    lang=lang,
                    length=len(title),
                    title=title,
                    template=title_tpl,
                )
            )
    return violations


def format_scene_title_violations(violations: List[SceneTitleViolation]) -> str:
    """違反リストを人間可読な複数行テキストに整形する（CLI / エラーメッセージ共通）."""
    return "\n".join(f"  - [{v.lang}] {v.length} codepoints (+{v.length - 100}): {v.title}" for v in violations)


class BAHMetadataGenerator:
    """メタデータ生成クラス（config/channel/*.json 駆動）"""

    def __init__(self, collection_path: str):
        """
        初期化

        Args:
            collection_path (str): コレクションディレクトリのパス
        """
        self.config = load_config()
        self._masterup_config = load_skill_config("masterup")
        self._crossfade_sec = float(self._masterup_config.get("audio", {}).get("crossfade_duration", 1.0))
        self._video_description_config = load_skill_config("video-description")
        self.collection_path = Path(collection_path)
        self.collection_name = self._extract_collection_name()
        self.bit_depth = self.config.content.genre.style
        self.tracks = []

    def _extract_collection_name(self) -> str:
        """ディレクトリ名からコレクション名を抽出"""
        dir_name = self.collection_path.name

        # 日付・ステータス・プレフィックスを除去
        # 例: "20250907-live-16bit-village-town-ver2" → "Village Town ver.2"
        pattern = r"^\d{8}-\w+-(?:\d+bit-)?(.+)$"
        match = re.match(pattern, dir_name)

        if match:
            name_part = match.group(1)
            # ハイフンをスペースに、大文字化
            clean_name = name_part.replace("-", " ").title()
            # "Ver" を "ver." に修正
            clean_name = re.sub(r"\bVer(\d)", r"ver.\1", clean_name)
            return clean_name

        return dir_name

    def analyze_audio_files(self) -> List[Dict]:
        """
        音声ファイル解析

        Returns:
            List[Dict]: 楽曲情報リスト
        """
        audio_dir = self.collection_path / "02-Individual-music"

        if not audio_dir.exists():
            logger.warning(f"音声ディレクトリが見つかりません（Lyria コレクション?）: {audio_dir}")
            return []

        tracks = []
        skipped: list[tuple[str, str]] = []
        current_time = 0
        crossfade = self._crossfade_sec

        # 音声ファイルを取得（AUDIO_EXTS で許容形式を共有、数字順にソート）
        wav_files = sorted([f for f in audio_dir.iterdir() if f.suffix.lower() in AUDIO_EXTS])

        for wav_file in wav_files:
            try:
                # afinfo コマンドで楽曲長を取得
                duration = self._get_audio_duration(wav_file)

                if duration <= 0:
                    reason = "再生時間が 0 秒（ファイル破損または afinfo 解析失敗の可能性）"
                    logger.warning(f"トラックをスキップ: {wav_file.name} — {reason}")
                    skipped.append((wav_file.name, reason))
                    continue

                # タイトル清浄化
                title = self._clean_track_title(wav_file.stem)

                # タイムスタンプ計算（2曲目以降はクロスフェード分だけ前倒し）
                start_time = current_time
                end_time = current_time + duration

                tracks.append(
                    {
                        "filename": wav_file.name,
                        "title": title,
                        "duration": duration,
                        "start_time": start_time,
                        "end_time": end_time,
                        "timestamp": self._format_timestamp(start_time),
                        "pattern_key": _extract_pattern_key(wav_file.name),
                    }
                )

                current_time = int(end_time - crossfade)

            except Exception as e:
                reason = f"ファイル解析エラー: {e}"
                logger.warning(f"トラックをスキップ: {wav_file.name} — {reason}")
                skipped.append((wav_file.name, reason))
                continue

        if skipped:
            logger.warning(
                f"⚠️  {len(skipped)}/{len(wav_files)} トラックがスキップされました:"
            )
            for name, reason in skipped:
                logger.warning(f"  - {name}: {reason}")

        if len(tracks) != len(wav_files):
            logger.warning(
                f"⚠️  入力 {len(wav_files)} ファイル → 出力 {len(tracks)} タイムスタンプ"
                f"（{len(wav_files) - len(tracks)} 件欠落）"
            )

        self.tracks = tracks
        # LLM がリネームした表示名が workflow-state.json に永続化されていれば再ロード時にも反映する
        self._apply_persisted_display_names()
        logger.info(f"楽曲解析完了: {len(tracks)}曲")
        return tracks

    def _get_audio_duration(self, wav_file: Path) -> int:
        """
        afinfo コマンドで音声ファイルの長さを取得

        Args:
            wav_file (Path): WAVファイルパス

        Returns:
            int: 長さ（秒）
        """
        try:
            result = subprocess.run(
                ["afinfo", str(wav_file)],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )

            # "estimated duration: XXX.XXX seconds" を抽出
            for line in result.stdout.split("\n"):
                if "estimated duration" in line:
                    duration_str = line.split(":")[1].strip().split()[0]
                    return int(float(duration_str))

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError) as e:
            logger.warning(f"afinfo エラー {wav_file.name}: {e}")

        return 0

    def _clean_track_title(self, filename: str) -> str:
        """
        ファイル名から楽曲タイトルを清浄化

        Args:
            filename (str): ファイル名

        Returns:
            str: 清浄化されたタイトル
        """
        title = filename

        # プレフィックス削除 ("8bit ")
        title = re.sub(r"^8bit\s+", "", title, flags=re.IGNORECASE)

        # 番号プレフィックス削除 ("01-", "02-" 等)
        title = re.sub(r"^\d{2}-", "", title)

        # パターンプレフィックス削除 ("pattern-a1-", "pattern-b-", "pattern-c2-" 等)
        title = re.sub(r"^pattern-[a-z]\d?-", "", title, flags=re.IGNORECASE)

        # サフィックス削除 ("(Remix)", "(Extended)" 等)
        title = re.sub(r"\s*\([^)]+\)\s*$", "", title)

        # アンダースコア・ハイフンをスペースに
        title = title.replace("_", " ").replace("-", " ")

        # 余分なスペース削除
        title = " ".join(title.split())

        # タイトルケース変換（冠詞・前置詞は小文字維持、先頭語は常に大文字）
        SMALL_WORDS = {"a", "an", "the", "at", "by", "in", "of", "on", "to", "and", "but", "or", "for", "nor"}
        words = title.title().split()
        for i, word in enumerate(words):
            if i > 0 and word.lower() in SMALL_WORDS:
                words[i] = word.lower()
        title = " ".join(words)

        return title

    def _format_timestamp(self, seconds: int) -> str:
        """秒数をYouTubeチャプター形式のタイムスタンプに変換（MM:SS または H:MM:SS）"""
        return format_timestamp(seconds)

    # ─── タイムスタンプ生成 ─────────────────────────────

    def generate_timestamps(self) -> list[dict]:
        """テーマ見出し + 楽曲行の構造化タイムスタンプを生成する。

        ファイル名規約 `\\d+-pattern-[a-d]` から検出した pattern_key の切り替わりごとに
        `theme_header` 行を挿入する。pattern_key が無いトラック群はフラットに並べる。

        戻り値: `list[{"type": "theme_header"|"track", "timestamp": str, "title": str}]`。
        トラックが無ければ空リスト。

        self.tracks が未 populate のときは 02-Individual-music/ の存在を見て
        analyze_audio_files() を実行する。
        """
        if not self.tracks:
            audio_dir = self.collection_path / "02-Individual-music"
            if audio_dir.exists() and any(audio_dir.iterdir()):
                self.analyze_audio_files()
        if not self.tracks:
            return []

        theme_names = self._load_theme_display_names()
        out: list[dict] = []
        last_pattern: str | None = None
        for track in self.tracks:
            pattern = track.get("pattern_key")
            if pattern and pattern != last_pattern:
                label = theme_names.get(pattern, f"Pattern {pattern.upper()}")
                out.append({"type": "theme_header", "timestamp": track["timestamp"], "title": label})
                last_pattern = pattern
            out.append({"type": "track", "timestamp": track["timestamp"], "title": track["title"]})
        return out

    def format_timestamps_text(self) -> str:
        """タイムスタンプを YouTube 概要欄用テキストに整形.

        テーマ見出し行は `section_headers.theme_inline.{prefix,suffix}` の装飾を適用。
        デフォルトは `"── "` / `" ──"` で、`section_headers.theme_inline` を上書きすれば
        チャンネル別に変更できる。

        YouTube のチャプター仕様は timestamps が strictly ascending である必要があるため、
        テーマ見出し行には **leading timestamp を載せない**（直後の楽曲行と同秒になると
        chapter list 全体が無効化される）。
        """
        timestamps = self.generate_timestamps()
        if not timestamps:
            return ""
        section_headers = self._video_description_config.get("section_headers", {})
        theme_inline = section_headers.get("theme_inline", {}) or {}
        prefix = theme_inline.get("prefix", "── ")
        suffix = theme_inline.get("suffix", " ──")
        lines = []
        for ts in timestamps:
            if ts["type"] == "theme_header":
                lines.append(f"{prefix}{ts['title']}{suffix}")
            else:
                lines.append(f"{ts['timestamp']} {ts['title']}")
        return "\n".join(lines)

    # ─── テーマ表示名・重複検知・リネーム永続化 ────────────────

    def _load_theme_display_names(self) -> Dict[str, str]:
        """workflow-state.json から pattern 表示名を解決する.

        優先順位:
        1. `planning.music.patterns[<letter>].display_name`（そのまま採用）
        2. `planning.music.patterns[<letter>].name`（`Pattern X: <name>` に整形）
        3. 解決不能 → 呼び出し元で `Pattern X` フォールバック
        """
        paths = CollectionPaths(self.collection_path)
        ws_path = paths.workflow_state_path
        result: Dict[str, str] = {}
        if not ws_path.exists():
            return result
        try:
            with open(ws_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            return result
        patterns = ((state.get("planning") or {}).get("music") or {}).get("patterns") or {}
        for letter, data in patterns.items():
            key = str(letter).lower()
            if not isinstance(data, dict):
                continue
            if data.get("display_name"):
                result[key] = data["display_name"]
            elif data.get("name"):
                result[key] = f"Pattern {key.upper()}: {data['name']}"
        return result

    def detect_duplicate_track_titles(self) -> Dict[str, List[int]]:
        """同名トラックを検出する（case-insensitive）.

        戻り値: `{正規化タイトル: [self.tracks 内の index, ...]}`. 重複が無ければ空 dict。
        SKILL.md 側はこの結果から LLM リネームの要否を判断する。
        """
        groups: Dict[str, List[int]] = {}
        display: Dict[str, str] = {}
        for idx, track in enumerate(self.tracks):
            title = track.get("title", "")
            key = title.casefold()
            groups.setdefault(key, []).append(idx)
            display.setdefault(key, title)
        return {display[k]: idxs for k, idxs in groups.items() if len(idxs) > 1}

    def _apply_persisted_display_names(self) -> None:
        """workflow-state.json の `track_display_names` を self.tracks に適用する.

        `analyze_audio_files()` 終端と、SKILL.md からの再ロード時に呼ばれる。
        対応する filename が無いキーは無視する（後方互換）。
        """
        paths = CollectionPaths(self.collection_path)
        ws_path = paths.workflow_state_path
        if not ws_path.exists():
            return
        try:
            with open(ws_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        name_map = state.get("track_display_names") or {}
        if not isinstance(name_map, dict) or not name_map:
            return
        for track in self.tracks:
            persisted = name_map.get(track.get("filename"))
            if persisted:
                track["title"] = persisted

    def apply_track_display_names(self, name_map: Dict[int, str]) -> None:
        """LLM が決定したリネーム結果を反映する.

        Args:
            name_map: `{self.tracks 内の index: 新表示名}`.

        Side effects:
            - `self.tracks[i]["title"]` を上書き
            - `workflow-state.json` の `track_display_names` キーに
              `{filename: display_name}` 形式で永続化（既存キーは保持）
        """
        if not name_map:
            return

        filename_map: Dict[str, str] = {}
        for idx, new_title in name_map.items():
            if idx < 0 or idx >= len(self.tracks):
                raise IndexError(f"apply_track_display_names: index {idx} は range 外（tracks={len(self.tracks)}）")
            self.tracks[idx]["title"] = new_title
            filename = self.tracks[idx].get("filename")
            if filename:
                filename_map[filename] = new_title

        if not filename_map:
            return

        paths = CollectionPaths(self.collection_path)
        ws_path = paths.workflow_state_path
        state: Dict = {}
        if ws_path.exists():
            try:
                with open(ws_path, "r", encoding="utf-8") as f:
                    state = json.load(f) or {}
            except (json.JSONDecodeError, OSError):
                state = {}
        existing = state.get("track_display_names") or {}
        if not isinstance(existing, dict):
            existing = {}
        existing.update(filename_map)
        state["track_display_names"] = existing
        ws_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ─── タイトル生成（2026リブランド） ─────────────────

    def _extract_theme_name(self) -> str:
        """コレクションのテーマ名を抽出

        優先順位: workflow-state.json の collection_name → _extract_collection_name() から "Collection" 除去
        """
        paths = CollectionPaths(self.collection_path)
        workflow_state_path = paths.workflow_state_path
        if workflow_state_path.exists():
            try:
                with open(workflow_state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("collection_name"):
                    name = state["collection_name"]
                    name = re.sub(r"\s+Collection$", "", name, flags=re.IGNORECASE)
                    return name
            except (json.JSONDecodeError, KeyError):
                pass

        name = self.collection_name
        name = re.sub(r"\s+Collection$", "", name, flags=re.IGNORECASE)
        return name

    def _get_activity(self) -> str:
        """タイトル用アクティビティキーワードを取得

        優先順位: workflow-state.json の title_activity → config のテーママッチング → デフォルト
        """
        paths = CollectionPaths(self.collection_path)
        workflow_state_path = paths.workflow_state_path
        if workflow_state_path.exists():
            try:
                with open(workflow_state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("title_activity"):
                    return state["title_activity"]
            except (json.JSONDecodeError, KeyError):
                pass

        theme = self._extract_theme_name()
        return self.config.content.title.activity_for_theme(theme)

    def _generate_title(self, total_seconds: int) -> str:
        """channel_config のテンプレートでタイトルを生成（100文字制限）"""
        theme = self._extract_theme_name()
        activity = self._get_activity()
        duration_display = format_duration_display(total_seconds)
        duration_short = format_duration_short(total_seconds)

        # jazzgak. TTP 形式: theme_scenes から scene_phrase と activities を取得
        theme_scenes = self.config.content.title.theme_scenes
        scene_phrase = ""
        scene_emoji = ""
        activities = activity
        if theme_scenes:
            theme_lower = theme.lower()
            for keyword, scene_data in theme_scenes.items():
                if keyword in theme_lower:
                    scene_phrase = scene_data.get("scene", "")
                    scene_emoji = scene_data.get("scene_emoji", "")
                    activities = scene_data.get("activities", activity)
                    break

        # workflow-state.json の planning.scene_emoji を優先採用（コレクション固有の絵文字）
        ws_scene_emoji = self._load_scene_emoji()
        if ws_scene_emoji:
            scene_emoji = ws_scene_emoji

        title = format_title_template(
            self.config.content.title.template,
            {
                "style": self.config.content.genre.style.title(),
                "theme": theme,
                "activity": activity,
                "activities": activities,
                "scene_phrase": scene_phrase,
                "scene_emoji": scene_emoji,
                "duration_display": duration_display,
                "duration_short": duration_short,
            },
            context="content.json: title.template",
        )
        # YouTube タイトル制限: 100 codepoint。
        # 過去事例: silent な title[:100] スライスでサロゲート文字接頭辞 +
        # 長い scene_phrase の組み合わせがアップロード時に切られ、
        # scene phrase 部分がまるごと消える事故が起きた。
        # silent slice せず、超過時は呼び出し元で短縮対応するよう例外を投げる。
        if len(title) > 100:
            raise ValueError(
                f"生成したタイトルが {len(title)} codepoint と 100 を超過: "
                f"\n  {title}\n"
                f"→ config/channel/content.json の title.theme_scenes[{theme}].scene を"
                f"短く書き直してください"
            )
        return title

    def _load_scene_phrases(self) -> Dict[str, str]:
        """workflow-state.json から scene_phrases を読み込み"""
        paths = CollectionPaths(self.collection_path)
        ws_path = paths.workflow_state_path
        if ws_path.exists():
            try:
                with open(ws_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                return state.get("scene_phrases", {})
            except (json.JSONDecodeError, KeyError):
                pass
        return {}

    def _load_scene_emoji(self) -> str:
        """workflow-state.json から planning.scene_emoji を読み込み"""
        paths = CollectionPaths(self.collection_path)
        ws_path = paths.workflow_state_path
        if ws_path.exists():
            try:
                with open(ws_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                return state.get("planning", {}).get("scene_emoji", "")
            except (json.JSONDecodeError, KeyError):
                pass
        return ""

    def generate_localizations(
        self,
        english_title: str,
        timestamp_body: str,
        scene_phrases: Dict[str, str] = None,
        scene_emoji: str = "",
    ) -> Dict:
        """各言語のローカライズされたタイトル・説明文を生成（jazzgak. TTP ハイブリッド方式）

        Args:
            english_title: 英語デフォルトタイトル（フォールバック用）
            timestamp_body: タイムスタンプ部分（全言語共通、ヘッダーなし）
            scene_phrases: {"ja": "雨の街の夜...", ...} コレクション別の感情フレーズ翻訳

        Returns:
            YouTube API 用 localizations 辞書
        """
        localizations = {}
        loc_config = self.config.localizations.data
        scene_phrases = scene_phrases or {}

        # 英語固定パーツ（config/channel/content.json の descriptions.metadata から取得）
        desc_metadata = self.config.content.descriptions.metadata
        genre_line = desc_metadata.get("genre", "Jazz")
        vibe_line = desc_metadata.get("vibe", "Rainy night, Cozy")
        best_for_line = desc_metadata.get("best_for", "Study, Focus, Late Night")
        usage_lines = "\n".join(
            [
                "• Original AI composition",
                "• Free for personal & non-commercial use",
                "• For commercial use, check the platform's AI content policy",
                "• Redistribution prohibited",
            ]
        )

        # 欠落チェック + 100 codepoint 超過を全言語まとめて検出する
        # （従来は 1 言語ずつ fail していたため多言語対応チャンネルで再アップロードを繰り返していた）
        violations = validate_scene_phrases(scene_phrases, self.config, scene_emoji=scene_emoji)
        if violations:
            raise ValueError(
                f"localizations の {len(violations)} 言語でタイトルが 100 codepoint を超過:\n"
                f"{format_scene_title_violations(violations)}\n"
                "→ workflow-state.json の該当 scene_phrases を短縮してください"
            )

        for lang in loc_config["supported_languages"]:
            lang_data = loc_config["languages"].get(lang, {})
            desc_data = lang_data.get("description", {})

            # --- タイトル ---（validate_scene_phrases 済みなので必須キーは揃っている前提）
            scene = scene_phrases[lang]
            title_tpl = lang_data["title_template"]
            activities = lang_data.get("activities", best_for_line)
            loc_title = format_title_template(
                title_tpl,
                {"scene_phrase": scene, "activities": activities, "scene_emoji": scene_emoji},
                context=f"localizations.json: language '{lang}' の title_template",
            )

            # --- 概要欄（ハイブリッド方式）---
            opening_poem = desc_data.get("opening_poem", "")
            cta = desc_data.get("cta_subscribe", self.config.meta.cta_subscribe)
            tagline = desc_data.get("tagline", self.config.meta.tagline)
            hashtags = desc_data.get("hashtags", self.config.content.descriptions.hashtag_line)

            section_headers = self._video_description_config.get("section_headers", {})
            track_list_header = section_headers.get("track_list", "")
            usage_header = section_headers.get("usage_attribution", "")
            channel_link_header = section_headers.get("channel_link_template", "🔗 {channel_name}:").format(
                channel_name=self.config.meta.channel_name
            )

            desc_parts = []
            if opening_poem:
                desc_parts.append(opening_poem)
                desc_parts.append("")
            desc_parts.extend(
                [
                    f"- Genre : {genre_line}",
                    f"- Vibe : {vibe_line}",
                    f"- Best for : {best_for_line}",
                    "",
                    track_list_header,
                    timestamp_body,
                    "",
                    usage_header,
                    usage_lines,
                    "",
                    channel_link_header,
                    cta,
                    tagline,
                    "",
                    hashtags,
                ]
            )
            loc_desc = "\n".join(desc_parts)[:5000]

            localizations[lang] = {
                "title": loc_title,
                "description": loc_desc,
            }

        return localizations

    def generate_complete_collection_metadata(self, title_override: str | None = None) -> Dict:
        """
        Complete Collection 用メタデータ生成

        Args:
            title_override: 最終タイトルが既に確定している場合に渡す。`descriptions.md` の
                `## タイトル案` が最終タイトルを供給する経路では、本来捨てられる中間タイトル
                生成（`_generate_title` = `title.template.format(...)`）をスキップする。
                これにより `title.template` が未知プレースホルダを含んでいても upload 全体が
                `KeyError`/`ValidationError` で巻き込まれない（#574）。

        Returns:
            Dict: YouTube アップロード用メタデータ
        """
        if not self.tracks:
            self.analyze_audio_files()

        crossfade = self._crossfade_sec
        total_duration = sum(track["duration"] for track in self.tracks) - max(0, len(self.tracks) - 1) * crossfade

        # タイトル生成（2026リブランド）。
        # title_override がある（descriptions.md で最終タイトルが確定する）場合は
        # 中間タイトル生成をスキップし、未知プレースホルダ由来のクラッシュを避ける。
        title = title_override if title_override else self._generate_title(total_duration)

        # 説明文生成
        description_parts = []

        # ヘッダーを新タイトルと一致させる
        header = f"🎵 {title}"
        description_parts.append(header)
        description_parts.append("")

        timestamp_body = self.format_timestamps_text()
        if timestamp_body:
            description_parts.append(timestamp_body)

        # config から説明文パーツを構築
        perfect_for_lines = "\n".join(f"• {item}" for item in list(self.config.content.descriptions.perfect_for))

        section_headers = self._video_description_config.get("section_headers", {})
        usage_header = section_headers.get("usage_attribution", "")
        perfect_for_header = section_headers.get("perfect_for", "")
        channel_link_header = section_headers.get("channel_link_template", "🔗 {channel_name}:").format(
            channel_name=self.config.meta.channel_name
        )
        usage_lines_cfg = self._video_description_config.get("usage_attribution_lines", [])

        description_parts.extend(
            [
                "",
                self.config.content.descriptions.render_opening(),
                self.config.content.descriptions.sub_opening,
                "",
                usage_header,
                *usage_lines_cfg,
                "",
                f"{perfect_for_header}\n{perfect_for_lines}",
                "",
                channel_link_header,
                self.config.meta.cta_subscribe,
                self.config.meta.tagline,
                "",
                self.config.content.descriptions.hashtag_line,
            ]
        )

        # ローカライゼーション生成
        scene_phrases = self._load_scene_phrases()
        scene_emoji = self._load_scene_emoji()
        self._last_scene_phrases = scene_phrases
        localizations = self.generate_localizations(title, timestamp_body, scene_phrases, scene_emoji=scene_emoji)

        return {
            "title": title,
            "description": "\n".join(description_parts),
            "tags": self._generate_tags(),
            "category_id": self.config.youtube.api.category_id,
            "privacy_status": self.config.youtube.api.privacy_status,
            "language": self.config.youtube.api.language,
            "localizations": localizations,
        }

    def _generate_tags(self) -> List[str]:
        """YouTube タグ生成（config/channel/content.json 駆動）"""
        return self.config.content.tags.for_collection(self.collection_name)

    # ─── Shorts 用メタデータ ────────────────────────────

    def _load_theme(self) -> str:
        """workflow-state.json から `theme` キーを読み込む（無ければ空文字）.

        Shorts のタグ・ローカライズ展開で `tags.themes[<theme>]` 参照に使うため、
        既存 `_extract_theme_name`（collection_name 派生）ではなく `workflow-state.json`
        の `theme` キーを優先する（テーマ別 tag を引くキーが workflow-state 側で
        確定している前提）。
        """
        paths = CollectionPaths(self.collection_path)
        ws_path = paths.workflow_state_path
        if ws_path.exists():
            try:
                with open(ws_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                return state.get("theme", "") or ""
            except (json.JSONDecodeError, KeyError):
                pass
        return ""

    def generate_shorts_metadata(self, cc_video_url: str) -> Dict:
        """Shorts 用メタデータを生成する.

        Args:
            cc_video_url: 紐づく Complete Collection の YouTube URL。
                空文字を渡すと CC リンク行を skip（例外は投げない、plan 要件 #3）。

        Returns:
            {title, description, tags, category_id, privacy_status, language, localizations}

        Raises:
            ValueError: 生成タイトルが 100 codepoint を超過したとき（silent slice 禁止、
                plan 補足設計判断 §153）。
        """
        channel_name = self.config.meta.channel_name
        theme = self._load_theme()

        # タイトル: 旧版踏襲 "{collection_name} ✦ {channel_name} #Shorts"
        title = f"{self.collection_name} ✦ {channel_name} #Shorts"
        if len(title) > 100:
            raise ValueError(
                f"生成した Shorts タイトルが {len(title)} codepoint と 100 を超過: "
                f"{title}\n"
                "→ コレクションディレクトリ名（_extract_collection_name 経路）を短縮してください"
            )

        # description: 共通組み立て（fallback と同じロジックを再利用）
        description = build_short_description(
            self.config,
            collection_name=self.collection_name,
            cc_video_url=cc_video_url,
        )

        # tags: ["Shorts"] + base + themes.get(theme, []) を [:50] でスライス
        # 順序は保持し、重複除去はしない（先勝ち）。plan 要件 #4-a/b/c/d 補足設計判断 §154。
        tag_list: List[str] = ["Shorts"]
        tag_list.extend(self.config.content.tags.base)
        tag_list.extend(self.config.content.tags.themes.get(theme, []))
        tag_list = tag_list[:50]

        localizations = build_short_localizations(
            self.config,
            collection_name=self.collection_name,
            theme=theme,
            cc_video_url=cc_video_url,
        )

        return {
            "title": title,
            "description": description,
            "tags": tag_list,
            "category_id": self.config.youtube.api.category_id,
            "privacy_status": "public",
            "language": self.config.youtube.api.language,
            "localizations": localizations,
        }

    def generate_metadata_report(self) -> str:
        """
        メタデータ生成レポート作成

        Returns:
            str: レポート文字列
        """
        if not self.tracks:
            self.analyze_audio_files()

        crossfade = self._crossfade_sec
        total_duration = sum(track["duration"] for track in self.tracks) - max(0, len(self.tracks) - 1) * crossfade

        report_parts = [
            f"📊 {self.config.meta.channel_name} メタデータ生成レポート",
            "=" * 60,
            f"🎵 コレクション: {self.collection_name}",
            f"🎼 ビット深度: {self.bit_depth}",
            f"📁 パス: {self.collection_path}",
            f"🎶 楽曲数: {len(self.tracks)}曲",
            f"⏱️  総再生時間: {self._format_timestamp(total_duration)}",
            f"📅 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "🎵 楽曲一覧:",
        ]

        for i, track in enumerate(self.tracks, 1):
            duration_formatted = self._format_timestamp(track["duration"])
            report_parts.append(f"  {i:02d}. {track['timestamp']} {track['title']} ({duration_formatted})")

        return "\n".join(report_parts)


def main():
    """メイン関数 - スタンドアロン実行用"""
    import sys

    if len(sys.argv) != 2:
        print("使用法: python metadata_generator.py <collection_directory>")
        sys.exit(1)

    collection_path = sys.argv[1]

    try:
        config = load_config()
        generator = BAHMetadataGenerator(collection_path)

        print(f"🎵 {config.meta.channel_name} - メタデータ生成テスト")
        print("=" * 60)

        # レポート生成
        report = generator.generate_metadata_report()
        print(report)

        print("\n" + "=" * 60)
        print("✅ メタデータ生成テスト完了")

    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
