"""DistroKid 配信プロファイル設定の責務別 dataclass（optional・opt-in）.

`config/channel/distrokid.json` のトップレベルキー `distrokid` を読み込む。
`yt-collection-serve` の `/distrokid/release.json` エンドポイントが静的プロファイルとして
参照する。`enabled == false`（既定）のチャンネルでは `/distrokid/*` 系が 404 を返す。

`profile` のフィールドは distrokid.com/new のリリース登録フォーム項目に対応する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# distrokid.enabled == True のとき profile に必須となるフィールド（条件付き必須）。
# loader の条件付きバリデーションと dataclass フィールドの SSOT。
REQUIRED_PROFILE_FIELDS: tuple[str, ...] = (
    "artist_name",
    "language",
    "main_genre",
    "songwriter",
    "apple_music_credit",
    "track_type",
)


@dataclass(frozen=True)
class DistrokidProfile:
    """`distrokid.profile` セクション（distrokid.com/new フォーム項目に対応）.

    - `artist_name`: アーティスト名
    - `language`: メタデータ言語
    - `main_genre`: メインジャンル
    - `songwriter`: 作曲者の本名
    - `apple_music_credit`: Apple Music 表示クレジット
    - `track_type`: トラック種別（例: Instrumental）
    """

    artist_name: str = ""
    language: str = ""
    main_genre: str = ""
    songwriter: str = ""
    apple_music_credit: str = ""
    track_type: str = ""


@dataclass(frozen=True)
class Distrokid:
    """`distrokid` セクション（optional・opt-in）.

    - `enabled`: distrokid 連携を有効にするか（`comments.enabled` と対称のオプトイン）
    - `profile`: 配信時に使う静的プロファイル
    """

    enabled: bool = False
    profile: DistrokidProfile = field(default_factory=DistrokidProfile)
