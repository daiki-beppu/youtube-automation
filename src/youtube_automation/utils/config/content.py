"""コンテンツ関連（ジャンル・タグ・説明文・タイトル）の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Genre:
    """`genre` セクション."""

    primary: str
    style: str
    context: str


@dataclass(frozen=True)
class Tags:
    """`tags` セクション。`channel_name` は loader が合成時に注入."""

    base: list[str]
    themes: dict[str, list[str]]
    channel_specific: list[str]
    channel_name: str
    min_count: int | None = None

    def default(self) -> list[str]:
        """チャンネル名を含むデフォルトタグリスト."""
        return list(self.base) + [self.channel_name.lower()]

    def for_collection(self, collection_name: str) -> list[str]:
        """コレクション名からタグリストを生成（最大 50 件）."""
        tags = self.default()
        tags.extend(self.channel_specific)
        lowered = collection_name.lower()
        for theme, theme_tag_list in self.themes.items():
            if theme in lowered:
                tags.extend(theme_tag_list)
                break
        return tags[:50]


@dataclass(frozen=True)
class Descriptions:
    """`descriptions` セクション。`genre` は loader が合成時に注入."""

    opening: str
    sub_opening: str
    perfect_for: list[str]
    hashtags: list[str]
    metadata: dict
    genre: Genre

    @property
    def hashtag_line(self) -> str:
        """ハッシュタグ行（スペース区切り）."""
        return " ".join(self.hashtags)

    def render_opening(self) -> str:
        """`{style}` / `{primary}` / `{context}` を format 展開した冒頭行を返す."""
        return self.opening.format(
            style=self.genre.style.title(),
            primary=self.genre.primary,
            context=self.genre.context,
        )


@dataclass(frozen=True)
class Title:
    """`title` セクション."""

    template: str
    default_activity: str
    theme_scenes: dict
    theme_activities: dict

    def activity_for_theme(self, theme: str) -> str:
        """テーマ名からアクティビティキーワードを取得.

        `theme_scenes` 優先（TTP 形式）、未定義なら `theme_activities`（レガシー形式）。
        解決順序: (1) 完全一致 → (2) 長いキーから順に substring 一致（longest-match）→
        (3) `default_activity`. 単純な dict 挿入順の substring 一致だと
        `campus-cafe` が先に存在する `cafe` にマッチしてしまい、明示エントリが
        dead code 化する症状があったため longest-match を優先する（#80）。
        """
        lowered = theme.lower()
        if self.theme_scenes:
            if lowered in self.theme_scenes:
                return self.theme_scenes[lowered].get("activities", self.default_activity)
            for keyword in sorted(self.theme_scenes, key=len, reverse=True):
                if keyword in lowered:
                    return self.theme_scenes[keyword].get("activities", self.default_activity)
            return self.default_activity
        if self.theme_activities:
            if lowered in self.theme_activities:
                return self.theme_activities[lowered]
            for keyword in sorted(self.theme_activities, key=len, reverse=True):
                if keyword in lowered:
                    return self.theme_activities[keyword]
        return self.default_activity

    def scene_for_theme(self, theme: str) -> str:
        """テーマ名から英語シーンフレーズを取得.

        `theme_scenes` の `scene` キーを `activity_for_theme` と同じ longest-match で返す。
        未定義なら空文字列を返す（`scene_phrases` 初期化時に呼び出し側が `--en` フォールバック判定する）。
        """
        if not self.theme_scenes:
            return ""
        lowered = theme.lower()
        if lowered in self.theme_scenes:
            return self.theme_scenes[lowered].get("scene", "")
        for keyword in sorted(self.theme_scenes, key=len, reverse=True):
            if keyword in lowered:
                return self.theme_scenes[keyword].get("scene", "")
        return ""


@dataclass(frozen=True)
class Content:
    """コンテンツ責務の合成（genre / tags / descriptions / title）."""

    genre: Genre
    tags: Tags
    descriptions: Descriptions
    title: Title
