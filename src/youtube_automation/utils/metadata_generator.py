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
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from youtube_automation.utils.config import load_config

from .audio_formats import AUDIO_EXTS
from .skill_config import load_skill_config
from .time_utils import format_duration_display, format_duration_short, format_timestamp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SceneTitleViolation:
    """多言語タイトルの codepoint 超過違反（100 codepoint 上限）."""

    lang: str
    length: int
    title: str
    template: str


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
        title = title_tpl.format(scene_phrase=scene, activities=activities, scene_emoji=scene_emoji)
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
        current_time = 0
        crossfade = self._crossfade_sec

        # 音声ファイルを取得（AUDIO_EXTS で許容形式を共有、数字順にソート）
        wav_files = sorted([f for f in audio_dir.iterdir() if f.suffix.lower() in AUDIO_EXTS])

        for wav_file in wav_files:
            try:
                # afinfo コマンドで楽曲長を取得
                duration = self._get_audio_duration(wav_file)

                if duration > 0:
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
                        }
                    )

                    current_time = int(end_time - crossfade)

            except Exception as e:
                logger.warning(f"ファイル解析エラー {wav_file.name}: {e}")
                continue

        self.tracks = tracks
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
        """3ソース対応のタイムスタンプ生成

        優先順位:
        1. 個別トラックがある場合 → analyze_audio_files()
        2. composition.json がある場合 → phases[].at_min
        3. いずれもない場合 → 空リスト
        """
        # 1. 個別トラックがある場合
        audio_dir = self.collection_path / "02-Individual-music"
        if audio_dir.exists() and any(audio_dir.iterdir()):
            tracks = self.analyze_audio_files()
            return [{"timestamp": t["timestamp"], "title": t["title"]} for t in tracks]

        # 2. composition.json がある場合（Lyria DJ 生成）
        comp_path = self.collection_path / "20-documentation" / "composition.json"
        if comp_path.exists():
            return self._timestamps_from_composition(comp_path)

        return []

    def _timestamps_from_composition(self, comp_path: Path) -> list[dict]:
        """composition.json の phases からタイムスタンプを生成"""
        with open(comp_path, "r", encoding="utf-8") as f:
            composition = json.load(f)

        timestamps = []
        for phase in composition.get("phases", []):
            at_min = phase.get("at_min", 0)
            at_sec = at_min * 60
            name = phase.get("name_en", phase.get("name", ""))
            timestamps.append(
                {
                    "timestamp": self._format_timestamp(at_sec),
                    "title": name,
                }
            )

        logger.info(f"composition.json から {len(timestamps)} チャプター生成")
        return timestamps

    def format_timestamps_text(self) -> str:
        """タイムスタンプをYouTube概要欄用テキストに整形"""
        timestamps = self.generate_timestamps()
        if not timestamps:
            return ""
        lines = [f"{ts['timestamp']} {ts['title']}" for ts in timestamps]
        return "\n".join(lines)

    # ─── タイトル生成（2026リブランド） ─────────────────

    def _extract_theme_name(self) -> str:
        """コレクションのテーマ名を抽出

        優先順位: workflow-state.json の collection_name → _extract_collection_name() から "Collection" 除去
        """
        workflow_state_path = self.collection_path / "workflow-state.json"
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
        workflow_state_path = self.collection_path / "workflow-state.json"
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

        title = self.config.content.title.template.format(
            style=self.config.content.genre.style.title(),
            theme=theme,
            activity=activity,
            activities=activities,
            scene_phrase=scene_phrase,
            scene_emoji=scene_emoji,
            duration_display=duration_display,
            duration_short=duration_short,
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
        ws_path = self.collection_path / "workflow-state.json"
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
        ws_path = self.collection_path / "workflow-state.json"
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
            loc_title = title_tpl.format(scene_phrase=scene, activities=activities, scene_emoji=scene_emoji)

            # --- 概要欄（ハイブリッド方式）---
            opening_poem = desc_data.get("opening_poem", "")
            cta = desc_data.get("cta_subscribe", self.config.meta.cta_subscribe)
            tagline = desc_data.get("tagline", self.config.meta.tagline)
            hashtags = desc_data.get("hashtags", self.config.content.descriptions.hashtag_line)

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
                    "⎯⎯⎯⎯ ✦ Track List ✦ ⎯⎯⎯⎯",
                    timestamp_body,
                    "",
                    "📝 Usage & Attribution:",
                    usage_lines,
                    "",
                    f"🔗 {self.config.meta.channel_name}:",
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

    def generate_complete_collection_metadata(self) -> Dict:
        """
        Complete Collection 用メタデータ生成

        Returns:
            Dict: YouTube アップロード用メタデータ
        """
        if not self.tracks:
            self.analyze_audio_files()

        crossfade = self._crossfade_sec
        total_duration = sum(track["duration"] for track in self.tracks) - max(0, len(self.tracks) - 1) * crossfade

        # タイトル生成（2026リブランド）
        title = self._generate_title(total_duration)

        # 説明文生成
        description_parts = []

        # ヘッダーを新タイトルと一致させる
        header = f"🎵 {title}"
        description_parts.append(header)
        description_parts.append("")

        # チャプター用タイムスタンプ
        for i, track in enumerate(self.tracks, 1):
            description_parts.append(f"{track['timestamp']} {i:02d}. {track['title']}")

        # タイムスタンプ部分（ローカライゼーション用、ヘッダーなし）
        timestamp_lines = []
        for i, track in enumerate(self.tracks, 1):
            timestamp_lines.append(f"{track['timestamp']} {i:02d}. {track['title']}")
        timestamp_body = "\n".join(timestamp_lines)

        # config から説明文パーツを構築
        perfect_for_lines = "\n".join(f"• {item}" for item in list(self.config.content.descriptions.perfect_for))

        description_parts.extend(
            [
                "",
                self.config.content.descriptions.render_opening(),
                self.config.content.descriptions.sub_opening,
                "",
                "📝 Usage & Attribution:",
                "• This music is original AI composition",
                "• Free to use for personal & commercial projects",
                "• Attribution appreciated but not required",
                "• Redistribution as-is prohibited",
                "",
                f"🎮 Perfect for:\n{perfect_for_lines}",
                "",
                f"🔗 {self.config.meta.channel_name}:",
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
