"""DistroKid 配信プロファイル設定の責務別 dataclass（optional・opt-in）.

`config/channel/distrokid.json` のトップレベルキー `distrokid` を読み込む。
`yt-collection-serve` の `/distrokid/release.json` エンドポイントが静的プロファイルとして
参照する。`enabled == false`（既定）のチャンネルでは `/distrokid/*` 系が 404 を返す。

`profile` のフィールドは distrokid.com/new のリリース登録フォーム項目（実 DOM 検証済み・#813）
に対応する。PR #803 の想像 schema（フラット 6 文字列）を撤廃し、songwriter は氏名 3 分割の
nested 構造に、AI 開示は `ai_disclosure` に再設計した。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# distrokid.enabled == True のとき profile に必須となるフィールド（条件付き必須）。
# loader の条件付きバリデーションと dataclass フィールドの SSOT。
# songwriter / ai_disclosure は任意（distrokid.com/new で省略可能）。
REQUIRED_PROFILE_FIELDS: tuple[str, ...] = (
    "language",
    "main_genre",
)


@dataclass(frozen=True)
class SongwriterName:
    """作曲者の本名（distrokid.com/new は first/middle/last の 3 欄に分割）.

    - `first`: 名（songwriter_real_name_first<N>）
    - `last`: 姓（songwriter_real_name_last<N>）
    - `middle`: ミドルネーム（songwriter_real_name_middle<N>、任意）
    """

    first: str
    last: str
    middle: str | None = None


@dataclass(frozen=True)
class AiDisclosure:
    """AI 開示モーダル（Suno 楽曲は通過必須）の各チェック状態.

    distrokid.com/new の「この楽曲には AI によって生成された…」radio で「はい」を選ぶと
    展開するモーダルの checkbox 群に対応する。

    - `enabled`: 「はい」radio を選択しモーダルを開くか
    - `lyrics`: 歌詞 AI（ai_lyrics_）
    - `composition`: 作曲 AI（ai_music_）
    - `full_audio`: 音声すべて AI
    - `partial_audio`: 音声の一部 AI（人間 + AI）
    - `apply_to_all`: 当リリースの全曲へ一括適用
    """

    enabled: bool = True
    lyrics: bool = True
    composition: bool = True
    full_audio: bool = True
    partial_audio: bool = False
    apply_to_all: bool = True


@dataclass(frozen=True)
class DistrokidProfile:
    """`distrokid.profile` セクション（distrokid.com/new フォーム項目に対応）.

    - `language`: メタデータ言語（language SELECT の value）
    - `main_genre`: メインジャンル（genrePrimary SELECT の value）
    - `sub_genre`: サブジャンル（genreSecondary SELECT の value、任意）
    - `songwriter`: 作曲者の本名（任意、省略時はトラック側で手入力）
    - `ai_disclosure`: AI 開示モーダルの設定（既定は全 AI 開示）
    """

    language: str = ""
    main_genre: str = ""
    sub_genre: str | None = None
    songwriter: SongwriterName | None = None
    ai_disclosure: AiDisclosure = field(default_factory=AiDisclosure)


@dataclass(frozen=True)
class Distrokid:
    """`distrokid` セクション（optional・opt-in）.

    - `enabled`: distrokid 連携を有効にするか（`comments.enabled` と対称のオプトイン）
    - `profile`: 配信時に使う静的プロファイル
    """

    enabled: bool = False
    profile: DistrokidProfile = field(default_factory=DistrokidProfile)
