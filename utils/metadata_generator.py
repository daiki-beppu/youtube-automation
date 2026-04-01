#!/usr/bin/env python3
"""
YouTube メタデータ自動生成ユーティリティ
collections/ ディレクトリの構造を解析し、YouTube用メタデータを自動生成

Features:
- WAVファイル自動解析（afinfo使用）
- タイムスタンプ自動計算
- channel_config.json ベースのテンプレート適用
"""

import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .channel_config import ChannelConfig
from .time_utils import format_duration_display, format_duration_short, format_timestamp

logger = logging.getLogger(__name__)


class BAHMetadataGenerator:
    """メタデータ生成クラス（channel_config.json 駆動）"""

    def __init__(self, collection_path: str):
        """
        初期化

        Args:
            collection_path (str): コレクションディレクトリのパス
        """
        self.config = ChannelConfig.load()
        self.collection_path = Path(collection_path)
        self.collection_name = self._extract_collection_name()
        self.bit_depth = self.config.genre_style
        self.tracks = []

    def _extract_collection_name(self) -> str:
        """ディレクトリ名からコレクション名を抽出"""
        dir_name = self.collection_path.name

        # 日付・ステータス・プレフィックスを除去
        # 例: "20250907-live-16bit-village-town-ver2" → "Village Town ver.2"
        pattern = r'^\d{8}-\w+-(?:\d+bit-)?(.+)$'
        match = re.match(pattern, dir_name)

        if match:
            name_part = match.group(1)
            # ハイフンをスペースに、大文字化
            clean_name = name_part.replace('-', ' ').title()
            # "Ver" を "ver." に修正
            clean_name = re.sub(r'\bVer(\d)', r'ver.\1', clean_name)
            return clean_name

        return dir_name

    def analyze_audio_files(self) -> List[Dict]:
        """
        音声ファイル解析

        Returns:
            List[Dict]: 楽曲情報リスト
        """
        audio_dir = self.collection_path / '02-Individual-music'

        if not audio_dir.exists():
            logger.warning(f"音声ディレクトリが見つかりません（Lyria コレクション?）: {audio_dir}")
            return []

        tracks = []
        current_time = 0
        crossfade = self.config.crossfade_duration

        # 音声ファイルを取得（WAV / MP3 / M4A / AAC に対応、数字順にソート）
        AUDIO_EXTS = {'.wav', '.mp3', '.m4a', '.aac'}
        wav_files = sorted([f for f in audio_dir.iterdir()
                           if f.suffix.lower() in AUDIO_EXTS])

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

                    tracks.append({
                        'filename': wav_file.name,
                        'title': title,
                        'duration': duration,
                        'start_time': start_time,
                        'end_time': end_time,
                        'timestamp': self._format_timestamp(start_time)
                    })

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
                ['afinfo', str(wav_file)],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )

            # "estimated duration: XXX.XXX seconds" を抽出
            for line in result.stdout.split('\n'):
                if 'estimated duration' in line:
                    duration_str = line.split(':')[1].strip().split()[0]
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
        title = re.sub(r'^8bit\s+', '', title, flags=re.IGNORECASE)

        # 番号プレフィックス削除 ("01-", "02-" 等)
        title = re.sub(r'^\d{2}-', '', title)

        # パターンプレフィックス削除 ("pattern-a1-", "pattern-b-", "pattern-c2-" 等)
        title = re.sub(r'^pattern-[a-z]\d?-', '', title, flags=re.IGNORECASE)

        # サフィックス削除 ("(Remix)", "(Extended)" 等)
        title = re.sub(r'\s*\([^)]+\)\s*$', '', title)

        # アンダースコア・ハイフンをスペースに
        title = title.replace('_', ' ').replace('-', ' ')

        # 余分なスペース削除
        title = ' '.join(title.split())

        # タイトルケース変換（冠詞・前置詞は小文字維持、先頭語は常に大文字）
        SMALL_WORDS = {'a', 'an', 'the', 'at', 'by', 'in', 'of', 'on', 'to', 'and', 'but', 'or', 'for', 'nor'}
        words = title.title().split()
        for i, word in enumerate(words):
            if i > 0 and word.lower() in SMALL_WORDS:
                words[i] = word.lower()
        title = ' '.join(words)

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
        audio_dir = self.collection_path / '02-Individual-music'
        if audio_dir.exists() and any(audio_dir.iterdir()):
            tracks = self.analyze_audio_files()
            return [{'timestamp': t['timestamp'], 'title': t['title']} for t in tracks]

        # 2. composition.json がある場合（Lyria DJ 生成）
        comp_path = self.collection_path / '20-documentation' / 'composition.json'
        if comp_path.exists():
            return self._timestamps_from_composition(comp_path)

        return []

    def _timestamps_from_composition(self, comp_path: Path) -> list[dict]:
        """composition.json の phases からタイムスタンプを生成"""
        with open(comp_path, 'r', encoding='utf-8') as f:
            composition = json.load(f)

        timestamps = []
        for phase in composition.get('phases', []):
            at_min = phase.get('at_min', 0)
            at_sec = at_min * 60
            name = phase.get('name_en', phase.get('name', ''))
            timestamps.append({
                'timestamp': self._format_timestamp(at_sec),
                'title': name,
            })

        logger.info(f"composition.json から {len(timestamps)} チャプター生成")
        return timestamps

    def format_timestamps_text(self) -> str:
        """タイムスタンプをYouTube概要欄用テキストに整形"""
        timestamps = self.generate_timestamps()
        if not timestamps:
            return ''
        lines = [f"{ts['timestamp']} {ts['title']}" for ts in timestamps]
        return '\n'.join(lines)

    # ─── タイトル生成（2026リブランド） ─────────────────

    def _extract_theme_name(self) -> str:
        """コレクションのテーマ名を抽出

        優先順位: workflow-state.json の collection_name → _extract_collection_name() から "Collection" 除去
        """
        workflow_state_path = self.collection_path / 'workflow-state.json'
        if workflow_state_path.exists():
            try:
                with open(workflow_state_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                if state.get('collection_name'):
                    name = state['collection_name']
                    name = re.sub(r'\s+Collection$', '', name, flags=re.IGNORECASE)
                    return name
            except (json.JSONDecodeError, KeyError):
                pass

        name = self.collection_name
        name = re.sub(r'\s+Collection$', '', name, flags=re.IGNORECASE)
        return name

    def _get_activity(self) -> str:
        """タイトル用アクティビティキーワードを取得

        優先順位: workflow-state.json の title_activity → config のテーママッチング → デフォルト
        """
        workflow_state_path = self.collection_path / 'workflow-state.json'
        if workflow_state_path.exists():
            try:
                with open(workflow_state_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                if state.get('title_activity'):
                    return state['title_activity']
            except (json.JSONDecodeError, KeyError):
                pass

        theme = self._extract_theme_name()
        return self.config.get_activity_for_theme(theme)

    def _generate_title(self, total_seconds: int) -> str:
        """channel_config のテンプレートでタイトルを生成（100文字制限）"""
        theme = self._extract_theme_name()
        activity = self._get_activity()
        duration_display = format_duration_display(total_seconds)
        duration_short = format_duration_short(total_seconds)

        # jazzgak. TTP 形式: theme_scenes から scene_phrase と activities を取得
        theme_scenes = self.config.raw.get('title', {}).get('theme_scenes', {})
        scene_phrase = ""
        activities = activity
        if theme_scenes:
            theme_lower = theme.lower()
            for keyword, scene_data in theme_scenes.items():
                if keyword in theme_lower:
                    scene_phrase = scene_data.get('scene', '')
                    activities = scene_data.get('activities', activity)
                    break

        title = self.config.title_template.format(
            style=self.config.genre_style.title(),
            theme=theme,
            activity=activity,
            activities=activities,
            scene_phrase=scene_phrase,
            duration_display=duration_display,
            duration_short=duration_short,
        )
        return title[:100]

    def generate_localizations(self, title_vars: Dict, description_body: str) -> Dict:
        """各言語のローカライズされたタイトル・説明文を生成

        Args:
            title_vars: テンプレート変数（style, theme, activity, duration_display）
            description_body: 英語の説明文本文（タイムスタンプ部分）

        Returns:
            YouTube API 用 localizations 辞書
        """
        localizations = {}
        loc_config = self.config.localizations_config

        for lang in loc_config['supported_languages']:
            lang_data = loc_config['languages'][lang]

            # アクティビティフレーズ解決（自然言語 → フォールバック: 英語キーワード）
            activity = title_vars['activity']
            activity_phrases = lang_data.get('activity_phrases', {})
            activity_phrase = activity_phrases.get(activity, activity)

            # タイトル生成
            loc_vars = {**title_vars, 'activity_phrase': activity_phrase}
            loc_title = lang_data['title_template'].format(**loc_vars)[:100]

            # 説明文生成
            desc_data = lang_data['description']
            opening = desc_data['opening'].format(
                style=title_vars['style'],
                primary=self.config.genre_primary.title(),
                context=self.config.genre_context.title(),
            )

            usage_lines = '\n'.join(f"• {line}" for line in desc_data['usage_lines'])
            perfect_for_lines = '\n'.join(f"• {item}" for item in desc_data['perfect_for'])

            loc_desc = '\n'.join([
                description_body,
                "",
                opening,
                desc_data['sub_opening'],
                "",
                f"📝 {desc_data['usage_header']}",
                usage_lines,
                "",
                f"🎮 {desc_data['perfect_for_header']}",
                perfect_for_lines,
                "",
                f"🔗 {self.config.channel_name}:",
                desc_data['cta_subscribe'],
                desc_data['tagline'],
                "",
                self.config.hashtag_line,
            ])[:5000]

            localizations[lang] = {
                'title': loc_title,
                'description': loc_desc,
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

        crossfade = self.config.crossfade_duration
        total_duration = sum(track['duration'] for track in self.tracks) - max(0, len(self.tracks) - 1) * crossfade

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

        # タイムスタンプ部分（ローカライゼーション共有用）
        timestamp_body = '\n'.join(description_parts)

        # config から説明文パーツを構築
        perfect_for_lines = '\n'.join(f"• {item}" for item in self.config.perfect_for)

        description_parts.extend([
            "",
            self.config.description_opening,
            self.config.description_sub_opening,
            "",
            "📝 Usage & Attribution:",
            "• This music is original AI composition",
            "• Free to use for personal & commercial projects",
            "• Attribution appreciated but not required",
            "• Redistribution as-is prohibited",
            "",
            f"🎮 Perfect for:\n{perfect_for_lines}",
            "",
            f"🔗 {self.config.channel_name}:",
            self.config.cta_subscribe,
            self.config.tagline,
            "",
            self.config.hashtag_line,
        ])

        # ローカライゼーション用変数（インスタンスに保存して再利用可能にする）
        theme = self._extract_theme_name()
        title_vars = {
            'style': self.config.genre_style.title(),
            'theme': theme,
            'activity': self._get_activity(),
            'duration_display': format_duration_display(total_duration),
            'duration_short': format_duration_short(total_duration),
        }
        self._last_title_vars = title_vars
        localizations = self.generate_localizations(title_vars, timestamp_body)

        return {
            'title': title,
            'description': '\n'.join(description_parts),
            'tags': self._generate_tags(),
            'category_id': self.config.category_id,
            'privacy_status': self.config.privacy_status,
            'language': self.config.language,
            'localizations': localizations,
        }

    def _generate_tags(self) -> List[str]:
        """YouTube タグ生成（channel_config.json 駆動）"""
        return self.config.get_tags_for_collection(self.collection_name)

    def generate_metadata_report(self) -> str:
        """
        メタデータ生成レポート作成

        Returns:
            str: レポート文字列
        """
        if not self.tracks:
            self.analyze_audio_files()

        crossfade = self.config.crossfade_duration
        total_duration = sum(track['duration'] for track in self.tracks) - max(0, len(self.tracks) - 1) * crossfade

        report_parts = [
            f"📊 {self.config.channel_name} メタデータ生成レポート",
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
            duration_formatted = self._format_timestamp(track['duration'])
            report_parts.append(f"  {i:02d}. {track['timestamp']} {track['title']} ({duration_formatted})")

        return '\n'.join(report_parts)

def main():
    """メイン関数 - スタンドアロン実行用"""
    import sys

    if len(sys.argv) != 2:
        print("使用法: python metadata_generator.py <collection_directory>")
        sys.exit(1)

    collection_path = sys.argv[1]

    try:
        config = ChannelConfig.load()
        generator = BAHMetadataGenerator(collection_path)

        print(f"🎵 {config.channel_name} - メタデータ生成テスト")
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
