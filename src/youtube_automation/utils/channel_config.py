#!/usr/bin/env python3
"""
ChannelConfig - チャンネル設定の一元管理

config/channel_config.json を読み込み、全スクリプトに設定値を提供するシングルトンクラス。
テンプレートリポジトリ化の際、チャンネル固有値はこのファイル経由でのみ参照される。
"""

import json
import logging
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError

logger = logging.getLogger(__name__)

# 必須キーの定義（ドット区切りのネストパス）
_REQUIRED_KEYS = [
    'channel.name',
    'channel.short',
    'channel.youtube_handle',
    'channel.url',
    'genre.primary',
    'genre.style',
    'genre.context',
    'youtube.category_id',
    'youtube.privacy_status',
    'youtube.language',
    'tags.base',
    'tags.themes',
    'descriptions.opening',
    'descriptions.perfect_for',
    'descriptions.hashtags',
    'title.template',
]

class ChannelConfig:
    """channel_config.json のシングルトンローダー"""

    _instance = None
    _data = None
    _localizations_data = None
    _channel_dir = None

    def __init__(self):
        raise RuntimeError("ChannelConfig.load() を使用してください")

    @classmethod
    def _resolve_channel_dir(cls) -> Path:
        """チャンネルディレクトリを解決する

        解決順序:
        1. CHANNEL_DIR 環境変数
        2. CWD から config/channel_config.json を持つ祖先ディレクトリを探索
        """
        import os
        env = os.environ.get('CHANNEL_DIR')
        if env:
            return Path(env)
        # CWD から config/channel_config.json を持つ祖先を探す
        for parent in [Path.cwd()] + list(Path.cwd().parents):
            if (parent / 'config' / 'channel_config.json').exists():
                return parent
        raise ConfigError(
            "CHANNEL_DIR 環境変数を設定するか、チャンネルディレクトリ配下で実行してください"
        )

    @classmethod
    def channel_dir(cls) -> Path:
        """チャンネルディレクトリを返す（他モジュールからの参照用）"""
        if cls._channel_dir is None:
            cls._channel_dir = cls._resolve_channel_dir()
        return cls._channel_dir

    @classmethod
    def load(cls, config_path: str = None) -> 'ChannelConfig':
        """設定ファイルを読み込みシングルトンインスタンスを返す

        Args:
            config_path: 設定ファイルパス（省略時は CHANNEL_DIR/config/channel_config.json）

        Returns:
            ChannelConfig インスタンス
        """
        if cls._instance is not None:
            return cls._instance

        # .env を自動ロード（CWD から親ディレクトリを遡り探索）
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv())

        if config_path is None:
            cls._channel_dir = cls._resolve_channel_dir()
            config_path = cls._channel_dir / 'config' / 'channel_config.json'
        else:
            config_path = Path(config_path)

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                cls._data = json.load(f)
        except FileNotFoundError:
            raise ConfigError(f"設定ファイルが見つかりません: {config_path}")
        except json.JSONDecodeError as e:
            raise ConfigError(f"設定ファイルの JSON パースに失敗: {config_path}: {e}")

        cls._validate()

        instance = object.__new__(cls)
        cls._instance = instance
        return instance

    @classmethod
    def _validate(cls):
        """必須キーの存在を検証する

        Raises:
            ConfigError: 必須キーが欠落している場合
        """
        missing = []
        for key_path in _REQUIRED_KEYS:
            parts = key_path.split('.')
            current = cls._data
            for part in parts:
                if not isinstance(current, dict) or part not in current:
                    missing.append(key_path)
                    break
                current = current[part]

        if missing:
            raise ConfigError(
                f"channel_config.json に必須キーがありません: {', '.join(missing)}"
            )

    @classmethod
    def reset(cls):
        """シングルトンをリセット（テスト用）"""
        cls._instance = None
        cls._data = None
        cls._localizations_data = None
        cls._channel_dir = None

    # ─── チャンネル基本情報 ───────────────────────────

    @property
    def channel_name(self) -> str:
        return self._data['channel']['name']

    @property
    def channel_short(self) -> str:
        return self._data['channel']['short']

    @property
    def youtube_handle(self) -> str:
        return self._data['channel']['youtube_handle']

    @property
    def channel_url(self) -> str:
        return self._data['channel']['url']

    @property
    def core_message(self) -> str:
        return self._data['channel']['core_message']

    @property
    def cta_subscribe(self) -> str:
        return self._data['channel']['cta_subscribe']

    @property
    def tagline(self) -> str:
        return self._data['channel']['tagline']

    # ─── ジャンル ─────────────────────────────────────

    @property
    def genre_primary(self) -> str:
        return self._data['genre']['primary']

    @property
    def genre_style(self) -> str:
        return self._data['genre']['style']

    @property
    def genre_context(self) -> str:
        return self._data['genre']['context']

    # ─── YouTube 設定 ─────────────────────────────────

    @property
    def category_id(self) -> str:
        return self._data['youtube']['category_id']

    @property
    def privacy_status(self) -> str:
        return self._data['youtube']['privacy_status']

    @property
    def language(self) -> str:
        return self._data['youtube']['language']

    # ─── タグ ─────────────────────────────────────────

    @property
    def base_tags(self) -> list[str]:
        return list(self._data['tags']['base'])

    @property
    def theme_tags(self) -> dict[str, list[str]]:
        return self._data['tags']['themes']

    @property
    def channel_specific_tags(self) -> list[str]:
        """チャンネル固有タグ（任意キー、未定義時は空リスト）"""
        return list(self._data['tags'].get('channel_specific', []))

    def get_tags_for_collection(self, collection_name: str) -> list[str]:
        """コレクション名からタグリストを生成

        Args:
            collection_name: コレクション名

        Returns:
            タグリスト（最大50）
        """
        tags = self.default_tags

        # チャンネル固有タグ（任意キー、全コレクション共通）
        tags.extend(self._data['tags'].get('channel_specific', []))

        # テーマ別タグ追加
        collection_lower = collection_name.lower()
        for theme, theme_tag_list in self._data['tags']['themes'].items():
            if theme in collection_lower:
                tags.extend(theme_tag_list)
                break

        return tags[:50]

    @property
    def default_tags(self) -> list[str]:
        """チャンネル名を含むデフォルトタグリスト"""
        tags = list(self._data['tags']['base'])
        # チャンネル名をタグに含める
        tags.append(self.channel_name.lower())
        return tags

    # ─── 説明文 ───────────────────────────────────────

    @property
    def description_opening(self) -> str:
        """説明文の冒頭行（プレースホルダ展開済み）"""
        template = self._data['descriptions']['opening']
        return template.format(
            style=self.genre_style.title(),
            primary=self.genre_primary,
            context=self.genre_context,
        )

    @property
    def description_sub_opening(self) -> str:
        return self._data['descriptions']['sub_opening']

    @property
    def perfect_for(self) -> list[str]:
        return list(self._data['descriptions']['perfect_for'])

    @property
    def hashtags(self) -> list[str]:
        return list(self._data['descriptions']['hashtags'])

    @property
    def hashtag_line(self) -> str:
        """ハッシュタグ行（スペース区切り）"""
        return ' '.join(self._data['descriptions']['hashtags'])

    # ─── Analytics ────────────────────────────────────

    @property
    def collection_filter_keywords(self) -> list[str]:
        return list(self._data['analytics']['collection_filter_keywords'])

    # ─── タイトル ───────────────────────────────────────

    @property
    def title_template(self) -> str:
        return self._data['title']['template']

    @property
    def default_activity(self) -> str:
        return self._data['title'].get('default_activity', self._data['title'].get('default_activities', 'Study'))

    def get_activity_for_theme(self, theme: str) -> str:
        """テーマ名からアクティビティキーワードを取得

        Args:
            theme: テーマ名（例: "Ice Cavern", "Battle"）

        Returns:
            アクティビティ文字列（例: "Study", "Gaming"）
        """
        theme_lower = theme.lower()
        # jazzgak. TTP 形式: theme_scenes (activities はシーン内に格納)
        theme_scenes = self._data['title'].get('theme_scenes', {})
        if theme_scenes:
            for keyword, scene_data in theme_scenes.items():
                if keyword in theme_lower:
                    return scene_data.get('activities', self.default_activity)
            return self.default_activity
        # 従来形式: theme_activities
        theme_activities = self._data['title'].get('theme_activities', {})
        for keyword, activity in theme_activities.items():
            if keyword in theme_lower:
                return activity
        return self.default_activity

    # ─── ローカライゼーション ──────────────────────────

    @property
    def localizations_config(self) -> dict:
        """localizations.json の遅延読み込み

        Raises:
            ConfigError: localizations.json が存在しない / JSON 不正の場合。
                多言語機能（upload の localizations / short の翻訳）を使わないチャンネルは
                `has_localizations` で事前確認してから参照すること。
        """
        if self._localizations_data is None:
            loc_path = ChannelConfig.channel_dir() / 'config' / 'localizations.json'
            try:
                with open(loc_path, 'r', encoding='utf-8') as f:
                    ChannelConfig._localizations_data = json.load(f)
            except FileNotFoundError:
                raise ConfigError(
                    f"localizations.json が見つかりません: {loc_path}\n"
                    "多言語機能を使う場合は channel-setup スキルの "
                    "references/localizations-template.json を参考に作成してください。"
                )
            except json.JSONDecodeError as e:
                raise ConfigError(f"localizations.json の JSON パースに失敗: {loc_path}: {e}")
        return self._localizations_data

    @property
    def has_localizations(self) -> bool:
        """localizations.json が存在するか（多言語機能の事前チェック用）"""
        loc_path = ChannelConfig.channel_dir() / 'config' / 'localizations.json'
        return loc_path.exists()

    @property
    def supported_languages(self) -> list[str]:
        """対応言語リスト。localizations.json が無い場合は channel.youtube.language のみ"""
        if not self.has_localizations:
            return [self.language]
        return list(self.localizations_config['supported_languages'])

    # ─── Music engine ──────────────────────────────────

    @property
    def music_engine(self) -> str:
        """音楽エンジン（'suno' / 'lyria'）。未設定時は 'suno'"""
        engine = self._data.get('music_engine', 'suno')
        if engine not in ('suno', 'lyria'):
            logger.warning(
                "channel_config.json の music_engine='%s' は未知の値です。"
                "既知の値は 'suno' / 'lyria'",
                engine,
            )
        return engine

    # ─── Benchmark ──────────────────────────────────

    @property
    def benchmark_channels(self) -> list[dict]:
        return self._data.get('benchmark', {}).get('channels', [])

    # ─── Playlists ──────────────────────────────────

    @property
    def playlists(self) -> dict:
        return self._data.get('playlists', {})

    # ─── 生データアクセス ─────────────────────────────

    @property
    def raw(self) -> dict:
        """生の設定辞書（高度な用途向け）"""
        return self._data
