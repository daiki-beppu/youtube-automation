#!/usr/bin/env python3
"""
YouTube メタデータ自動生成ユーティリティ
collections/ ディレクトリの構造を解析し、YouTube用メタデータを自動生成

Features:
- 音声ファイル自動解析（afinfo / ffprobe 使用）
- タイムスタンプ自動計算
- config/channel/*.json ベースのテンプレート適用
"""

import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import yaml

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.adapters.media import CollectionPaths, probe_duration
from youtube_automation.core.adapters.runtime import (
    format_duration_display,
    format_duration_short,
    format_timestamp,
)
from youtube_automation.core.errors import ValidationError, WorkflowStateError, WorkflowStateSectionTypeError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read_or_none as read_workflow_state_or_none
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.media.audio_adjustments import apply_track_order, read_audio_adjustments
from youtube_automation.domains.media.audio_formats import AUDIO_EXTS
from youtube_automation.domains.metadata.descriptions import (
    build_complete_collection_description,
    build_short_description,
)
from youtube_automation.domains.metadata.localizations import (
    _validate_and_format_scene_titles,
    build_short_localizations,
    format_scene_title_violations,
    validate_localizations_title_templates,
)
from youtube_automation.domains.metadata.tags import (
    build_collection_tags,
    build_short_tags,
)
from youtube_automation.domains.metadata.titles import (
    _extract_extra_variation,
    _extract_pattern_key,
    build_collection_title,
    build_short_title,
)
from youtube_automation.domains.uploads.preflight import requires_scene_phrases

logger = logging.getLogger(__name__)


def _read_workflow_state_lenient(workflow_state_path: Path) -> WorkflowState | None:
    """既存の best-effort reader 用に owner の失敗を空 state へ変換する。"""
    try:
        return read_workflow_state_or_none(workflow_state_path)
    except WorkflowStateError:
        return None


class BAHMetadataGenerator:
    """メタデータ生成クラス（config/channel/*.json 駆動）"""

    def __init__(self, collection_path: str):
        """
        初期化

        Args:
            collection_path (str): コレクションディレクトリのパス
        """
        self.config = load_config()
        current_channel_dir = channel_dir()
        self._masterup_config = load_skill_config("masterup", channel_dir=current_channel_dir)
        self._crossfade_sec = float(self._masterup_config.get("audio", {}).get("crossfade_duration", 1.0))
        self._video_description_config = load_skill_config("video", channel_dir=current_channel_dir)["describe"]
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
        current_time = 0.0
        crossfade = self._crossfade_sec

        # 音声ファイルを取得（AUDIO_EXTS で許容形式を共有、数字順にソート）
        wav_files = sorted([f for f in audio_dir.iterdir() if f.suffix.lower() in AUDIO_EXTS])
        adjustments = read_audio_adjustments(self.collection_path / "20-documentation/audio-adjustments.json")
        wav_files = apply_track_order(wav_files, adjustments.order)

        for wav_file in wav_files:
            try:
                duration = self._get_audio_duration(wav_file)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError, OSError) as e:
                reason = f"ファイル解析エラー: {e}"
                logger.warning(f"トラックをスキップ: {wav_file.name} — {reason}")
                skipped.append((wav_file.name, reason))
                continue

            if duration <= 0:
                reason = "再生時間が 0 秒（ファイル破損または afinfo 解析失敗の可能性）"
                logger.warning(f"トラックをスキップ: {wav_file.name} — {reason}")
                skipped.append((wav_file.name, reason))
                continue

            title = self._clean_track_title(wav_file.stem)
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

            current_time = end_time - crossfade

        if skipped:
            logger.warning(f"⚠️  {len(skipped)}/{len(wav_files)} トラックがスキップされました:")
            for name, reason in skipped:
                logger.warning(f"  - {name}: {reason}")

        if len(tracks) != len(wav_files):
            logger.warning(
                f"⚠️  入力 {len(wav_files)} ファイル → 出力 {len(tracks)} タイムスタンプ"
                f"（{len(wav_files) - len(tracks)} 件欠落）"
            )

        self.tracks = tracks
        self._apply_suno_pattern_track_names()
        # LLM がリネームした表示名が workflow-state.json に永続化されていれば再ロード時にも反映する
        self._apply_persisted_display_names()
        logger.info(f"楽曲解析完了: {len(tracks)}曲")
        return tracks

    def _get_audio_duration(self, wav_file: Path) -> float:
        """
        afinfo / ffprobe で音声ファイルの長さを取得

        Args:
            wav_file (Path): 音声ファイルパス

        Returns:
            float: 長さ（秒）

        Raises:
            subprocess.CalledProcessError: afinfo が非ゼロ終了した場合
            subprocess.TimeoutExpired: afinfo がタイムアウトした場合
            ValueError: duration 文字列の数値変換に失敗した場合
            IndexError: afinfo 出力のパースに失敗した場合
        """
        afinfo_error: Exception | None = None
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
                    afinfo_duration = float(duration_str)
                    if afinfo_duration > 0:
                        return max(1.0, afinfo_duration)
                    break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError, OSError) as e:
            afinfo_error = e

        duration = probe_duration(wav_file)
        if duration is not None and duration > 0:
            return max(1.0, duration)

        if afinfo_error is not None:
            raise afinfo_error

        logger.warning(f"音声 duration を取得できませんでした: {wav_file.name}")
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

        # 同じ曲の clip variant を番号込みの別タイトルとして扱わない
        title = re.sub(r"^\d{2,}[ab]-", "", title, flags=re.IGNORECASE)

        # 番号プレフィックス削除 ("01-", "02-" 等)
        title = re.sub(r"^\d{2}-", "", title)

        # パターンプレフィックス削除 ("pattern-a1-", "pattern-b-", "pattern-c2-" 等)
        title = re.sub(r"^pattern-[a-z]\d*-", "", title, flags=re.IGNORECASE)

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

    def _format_timestamp(self, seconds: int | float) -> str:
        """秒数をYouTubeチャプター形式のタイムスタンプに変換（MM:SS または H:MM:SS）"""
        return format_timestamp(int(seconds))

    # ─── タイムスタンプ生成 ─────────────────────────────

    def generate_timestamps(self, loops: int = 1) -> list[dict]:
        """テーマ見出し + 楽曲行の構造化タイムスタンプを生成する。

        ファイル名規約 `\\d+-pattern-[a-d]` から検出した pattern_key の切り替わりごとに
        `theme_header` 行を挿入する。pattern_key が無いトラック群はフラットに並べる。

        Args:
            loops: master のループ回数（`yt-generate-master --loop N` /
                `--target-duration` のループ展開と同じ回数）。2 以上を指定すると
                トラック列を N 回繰り返し、2 周目以降の開始秒は 1 周目と同じ
                クロスフェード算術（`current + duration - crossfade`）で
                連続計算する。既定 1（従来挙動）。

        戻り値: `list[{"type": "theme_header"|"track", "timestamp": str, "title": str, "loop": int}]`。
        トラックが無ければ空リスト。`loop` は 1 始まりの周回番号。
        2 周目以降のタイトルは 1 周目と同一なので、チャプター名をユニークにしたい
        チャンネルでは呼び出し側（LLM リネーム / track_display_names）で装飾する。

        self.tracks が未 populate のときは 02-Individual-music/ の存在を見て
        analyze_audio_files() を実行する。
        """
        if loops < 1:
            raise ValueError(f"loops must be >= 1: {loops}")
        if not self.tracks:
            audio_dir = self.collection_path / "02-Individual-music"
            if audio_dir.exists() and any(audio_dir.iterdir()):
                self.analyze_audio_files()
        if not self.tracks:
            return []

        theme_names = self._load_theme_display_names()
        crossfade = self._crossfade_sec
        out: list[dict] = []
        current_time = 0.0
        for loop_index in range(1, loops + 1):
            last_pattern: str | None = None
            for track in self.tracks:
                # 1 周目は analyze_audio_files() が保存した timestamp をそのまま使い
                # 従来挙動と完全一致させる。2 周目以降は同じ算術で連続計算する。
                timestamp = track["timestamp"] if loop_index == 1 else self._format_timestamp(current_time)
                pattern = track.get("pattern_key")
                if pattern and pattern != last_pattern:
                    label = theme_names.get(pattern, f"Pattern {pattern.upper()}")
                    out.append({"type": "theme_header", "timestamp": timestamp, "title": label, "loop": loop_index})
                    last_pattern = pattern
                out.append({"type": "track", "timestamp": timestamp, "title": track["title"], "loop": loop_index})
                current_time = current_time + track["duration"] - crossfade
        return out

    def format_timestamps_text(self, loops: int = 1) -> str:
        """タイムスタンプを YouTube 概要欄用テキストに整形.

        テーマ見出し行は `section_headers.theme_inline.{prefix,suffix}` の装飾を適用。
        デフォルトは `"── "` / `" ──"` で、`section_headers.theme_inline` を上書きすれば
        チャンネル別に変更できる。

        Args:
            loops: master のループ回数。`generate_timestamps(loops=N)` に委譲し、
                全ループ分のチャプターを展開する。既定 1（従来挙動）。

        YouTube のチャプター仕様は timestamps が strictly ascending である必要があるため、
        テーマ見出し行には **leading timestamp を載せない**（直後の楽曲行と同秒になると
        chapter list 全体が無効化される）。
        """
        timestamps = self.generate_timestamps(loops=loops)
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
        state = _read_workflow_state_lenient(ws_path)
        try:
            planning = state.planning if state is not None else None
            music = planning.music if planning is not None else None
            patterns = music.patterns if music is not None else None
        except WorkflowStateError:
            return result
        patterns = patterns or {}
        for letter, data in patterns.items():
            key = str(letter).lower()
            if not isinstance(data, dict):
                continue
            if data.get("display_name"):
                result[key] = data["display_name"]
            elif data.get("name"):
                result[key] = f"Pattern {key.upper()}: {data['name']}"
        return result

    def _load_suno_pattern_name_en(self) -> Dict[str, str]:
        """20-documentation/suno-patterns.yaml から pattern_key -> name_en を解決する.

        `yt-generate-suno` と同じく `patterns:` 配列順を A/B/C... に対応させる。
        複数 scene を持つ pattern は `a1`, `a2` の variation key も同じ `name_en` に
        紐づけ、`pattern-d2-...` のようなファイル名から参照できるようにする。
        """
        patterns_path = CollectionPaths(self.collection_path).docs_dir / "suno-patterns.yaml"
        if not patterns_path.exists():
            return {}

        try:
            with open(patterns_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            return {}

        patterns = data.get("patterns") or []
        if not isinstance(patterns, list):
            return {}

        labels = "abcdefghijklmnopqrstuvwxyz"
        result: Dict[str, str] = {}
        for i, pattern in enumerate(patterns):
            if i >= len(labels) or not isinstance(pattern, dict):
                continue
            name_en = str(pattern.get("name_en") or "").strip()
            if not name_en:
                continue
            base_key = labels[i]
            result[base_key] = name_en
            scenes = pattern.get("scenes") or []
            if isinstance(scenes, list):
                for j, _scene in enumerate(scenes, 1):
                    result[f"{base_key}{j}"] = name_en
        return result

    @staticmethod
    def _prefix_track_title(prefix: str, title: str) -> str:
        """既存 title の情報を残しながら、読みやすい prefix を付ける."""
        prefix = " ".join(prefix.split())
        title = " ".join(title.split())
        if not prefix:
            return title
        if not title or title.casefold() == prefix.casefold() or title.casefold().startswith(f"{prefix.casefold()} - "):
            return title or prefix
        return f"{prefix} - {title}"

    def _apply_suno_pattern_track_names(self) -> None:
        """suno-patterns.yaml の name_en をトラック表示名のプレフィックスに適用する."""
        pattern_names = self._load_suno_pattern_name_en()
        theme = self._extract_theme_name()

        for track in self.tracks:
            filename = track.get("filename", "")
            title = track.get("title", "")
            prefix = ""

            pattern_key = track.get("pattern_key")
            if pattern_key:
                prefix = pattern_names.get(pattern_key) or pattern_names.get(pattern_key[:1], "")
            else:
                extra_variation = _extract_extra_variation(filename)
                if extra_variation and theme:
                    extra_title = f"{theme} Extra V{extra_variation}"
                    if title.casefold() == f"extra v{extra_variation}".casefold():
                        track["title"] = extra_title
                        continue
                    prefix = extra_title

            if prefix:
                track["title"] = self._prefix_track_title(prefix, title)

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
        state = _read_workflow_state_lenient(ws_path)
        try:
            name_map = state.track_display_names if state is not None else None
        except WorkflowStateError:
            return
        if not name_map:
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

        Raises:
            ValidationError: 既存 workflow-state.json が破損・読取不能な場合
                （既存 state の消失を防ぐため上書きせず中断する）
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

        def persist_display_names(state: WorkflowState) -> None:
            existing = state.get("track_display_names") or {}
            if not isinstance(existing, dict):
                existing = {}
            existing.update(filename_map)
            state["track_display_names"] = existing

        try:
            update_workflow_state(ws_path, persist_display_names)
        except WorkflowStateError as error:
            cause = error.__cause__
            if isinstance(cause, OSError) and "could not be written" in str(error):
                raise cause from error
            if "root must be an object" in str(error):
                raise ValidationError("workflow-state.json の root は object である必要があります") from error
            if isinstance(cause, json.JSONDecodeError):
                raise ValidationError(f"workflow-state.json のパースに失敗: {cause}") from error
            raise ValidationError(f"workflow-state.json を読めません: {error}") from error

    # ─── タイトル生成（2026リブランド） ─────────────────

    def _extract_theme_name(self) -> str:
        """コレクションのテーマ名を抽出

        優先順位: workflow-state.json の collection_name → _extract_collection_name() から "Collection" 除去
        """
        paths = CollectionPaths(self.collection_path)
        workflow_state_path = paths.workflow_state_path
        state = _read_workflow_state_lenient(workflow_state_path)
        try:
            configured_name = state.collection_name if state is not None else None
        except WorkflowStateError:
            configured_name = None
        if configured_name:
            name = configured_name
            name = re.sub(r"\s+Collection$", "", name, flags=re.IGNORECASE)
            return name

        name = self.collection_name
        name = re.sub(r"\s+Collection$", "", name, flags=re.IGNORECASE)
        return name

    def _get_activity(self) -> str:
        """タイトル用アクティビティキーワードを取得

        優先順位: workflow-state.json の title_activity → config のテーママッチング → デフォルト
        """
        paths = CollectionPaths(self.collection_path)
        workflow_state_path = paths.workflow_state_path
        state = _read_workflow_state_lenient(workflow_state_path)
        try:
            title_activity = state.title_activity if state is not None else None
        except WorkflowStateError:
            title_activity = None
        if title_activity:
            return title_activity

        theme = self._extract_theme_name()
        return self.config.content.title.activity_for_theme(theme)

    def _generate_title(self, total_seconds: int | float) -> str:
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

        return build_collection_title(
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

    def _load_scene_phrases(self) -> Dict[str, str]:
        """workflow-state.json から scene_phrases を読み込み"""
        state = self._load_workflow_state()
        return state.scene_phrases or {}

    def _load_workflow_state(self) -> WorkflowState:
        """workflow-state.json を読み込む。存在しない場合は空 document を返す。"""
        paths = CollectionPaths(self.collection_path)
        ws_path = paths.workflow_state_path
        try:
            state = read_workflow_state_or_none(ws_path)
        except WorkflowStateError as error:
            if "root must be an object" in str(error):
                raise ValidationError(
                    f"workflow-state.json の root は object である必要があります: {ws_path}"
                ) from error
            if isinstance(error, WorkflowStateSectionTypeError) and error.section in {"planning", "scene_phrases"}:
                raise ValidationError(f"workflow-state.json::{error.section} は object である必要があります") from error
            raise ValidationError(f"workflow-state.json を読み込めません: {ws_path}: {error}") from error
        return state if state is not None else WorkflowState({})

    def _load_scene_emoji(self) -> str:
        """workflow-state.json から planning.scene_emoji を読み込み"""
        state = self._load_workflow_state()
        planning = state.planning
        if planning is None:
            return ""
        try:
            return planning.scene_emoji or ""
        except WorkflowStateError as error:
            raise ValidationError("workflow-state.json::planning.scene_emoji は string である必要があります") from error

    def generate_localizations(
        self,
        english_title: str,
        timestamp_body: str,
        scene_phrases: Dict[str, str] | None = None,
        scene_emoji: str = "",
        *,
        duration_seconds: int | float,
    ) -> Dict:
        """各言語のローカライズされたタイトル・説明文を生成（jazzgak. TTP ハイブリッド方式）

        単一言語チャンネルでは YouTube snippet 側がデフォルト言語のタイトル・概要欄を
        持つため、localizations は生成せず空 dict を返す.

        Args:
            english_title: 英語デフォルトタイトル（フォールバック用）
            timestamp_body: タイムスタンプ部分（全言語共通、ヘッダーなし）
            scene_phrases: {"ja": "雨の街の夜...", ...} コレクション別の感情フレーズ翻訳
            duration_seconds: primary title と共有する実マスター秒数

        Returns:
            YouTube API 用 localizations 辞書
        """
        localizations = {}
        loc_config = self.config.localizations.data
        scene_phrases = scene_phrases or {}

        # 単一言語チャンネルは scene_phrases が populate されない（no-op）ため
        # localizations 自体を生成しない。デフォルト言語のタイトル・概要欄は
        # snippet 側で供給済みなので localizations 欠落による情報損失はない (#1470)
        if not requires_scene_phrases(loc_config.get("supported_languages", [])):
            return {}

        template_errors = validate_localizations_title_templates(loc_config)
        if template_errors:
            raise ValueError("localizations.json の title_template が不正です:\n" + "\n".join(template_errors))

        # 英語固定パーツ（config/channel/content.json の descriptions.metadata から取得）
        desc_metadata = self.config.content.descriptions.metadata
        genre_line = desc_metadata.get("genre", "Jazz")
        vibe_line = desc_metadata.get("vibe", "Rainy night, Cozy")
        best_for_line = desc_metadata.get("best_for", "Study, Focus, Late Night")
        usage_lines = "\n".join(self._video_description_config.get("usage_attribution_lines", []))

        # 欠落チェック + 100 codepoint 超過を全言語まとめて検出する
        # （従来は 1 言語ずつ fail していたため多言語対応チャンネルで再アップロードを繰り返していた）
        violations, localized_titles = _validate_and_format_scene_titles(
            scene_phrases,
            self.config,
            duration_seconds,
            scene_emoji=scene_emoji,
        )
        if violations:
            raise ValueError(
                f"localizations の {len(violations)} 言語でタイトルが 100 codepoint を超過:\n"
                f"{format_scene_title_violations(violations)}\n"
                "→ workflow-state.json の該当 scene_phrases を短縮してください"
            )

        for lang in loc_config["supported_languages"]:
            lang_data = loc_config["languages"].get(lang, {})
            desc_data = lang_data.get("description", {})

            # --- タイトル ---（検証時に同じ入力から生成済み）
            loc_title = localized_titles[lang]

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

    def generate_complete_collection_metadata(
        self,
        title_override: str | None = None,
        loops: int = 1,
        *,
        duration_seconds: int | float | None = None,
    ) -> Dict:
        """
        Complete Collection 用メタデータ生成

        Args:
            title_override: 最終タイトルが既に確定している場合に渡す。`descriptions.md` の
                `## タイトル案` が最終タイトルを供給する経路では、本来捨てられる中間タイトル
                生成（`_generate_title` = `title.template.format(...)`）をスキップする。
                これにより `title.template` が未知プレースホルダを含んでいても upload 全体が
                `KeyError`/`ValidationError` で巻き込まれない（#574）。
            loops: master のループ回数。`format_timestamps_text(loops=loops)` に渡し、
                全ループ分のチャプターを展開する。既定 1（従来挙動）。
            duration_seconds: upload/preflight が probe した実マスター秒数。metadata 単体生成では
                track のクロスフェード補正済み合計を使う。

        Returns:
            Dict: YouTube アップロード用メタデータ
        """
        if not self.tracks:
            self.analyze_audio_files()

        crossfade = self._crossfade_sec
        total_duration = sum(track["duration"] for track in self.tracks) - max(0, len(self.tracks) - 1) * crossfade
        effective_duration = total_duration if duration_seconds is None else duration_seconds

        # タイトル生成（2026リブランド）。
        # title_override がある（descriptions.md で最終タイトルが確定する）場合は
        # 中間タイトル生成をスキップし、未知プレースホルダ由来のクラッシュを避ける。
        title = title_override if title_override else self._generate_title(effective_duration)

        timestamp_body = self.format_timestamps_text(loops=loops)
        perfect_for_lines = "\n".join(f"• {item}" for item in list(self.config.content.descriptions.perfect_for))

        section_headers = self._video_description_config.get("section_headers", {})
        usage_header = section_headers.get("usage_attribution", "")
        perfect_for_header = section_headers.get("perfect_for", "")
        channel_link_header = section_headers.get("channel_link_template", "🔗 {channel_name}:").format(
            channel_name=self.config.meta.channel_name
        )
        usage_lines_cfg = self._video_description_config.get("usage_attribution_lines", [])

        description = build_complete_collection_description(
            title=title,
            timestamp_body=timestamp_body,
            opening=self.config.content.descriptions.render_opening(),
            sub_opening=self.config.content.descriptions.sub_opening,
            usage_header=usage_header,
            usage_lines=usage_lines_cfg,
            perfect_for_header=perfect_for_header,
            perfect_for_lines=perfect_for_lines,
            channel_link_header=channel_link_header,
            cta_subscribe=self.config.meta.cta_subscribe,
            tagline=self.config.meta.tagline,
            hashtag_line=self.config.content.descriptions.hashtag_line,
        )

        # ローカライゼーション生成
        scene_phrases = self._load_scene_phrases()
        scene_emoji = self._load_scene_emoji()
        self._last_scene_phrases = scene_phrases
        localizations = self.generate_localizations(
            title,
            timestamp_body,
            scene_phrases,
            scene_emoji=scene_emoji,
            duration_seconds=effective_duration,
        )

        return {
            "title": title,
            "description": description,
            "tags": self._generate_tags(),
            "category_id": self.config.youtube.api.category_id,
            "privacy_status": self.config.youtube.api.privacy_status,
            "language": self.config.youtube.api.language,
            "localizations": localizations,
        }

    def _generate_tags(self) -> List[str]:
        """YouTube タグ生成（config/channel/content.json 駆動）"""
        return build_collection_tags(self.config.content.tags.for_collection(self.collection_name))

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
        state = _read_workflow_state_lenient(ws_path)
        try:
            return (state.theme if state is not None else None) or ""
        except WorkflowStateError:
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
        title = build_short_title(self.collection_name, channel_name)

        # description: 共通組み立て（fallback と同じロジックを再利用）
        description = build_short_description(
            self.config,
            collection_name=self.collection_name,
            cc_video_url=cc_video_url,
        )

        tag_list = build_short_tags(self.config.content.tags.base, self.config.content.tags.themes.get(theme, []))

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
        print("使用法: python -m youtube_automation.domains.metadata.service <collection_directory>")
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
