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
    """AI 開示（distrokid.com/new の各 track ごとの AI 使用開示）.

    実 DOM 検証（#866）で判明した構造:
    - 「はい/いいえ」は track ごとの `ai_gate_<uuid>` radio
    - 「歌詞 AI」「作曲 AI」は track ごとの `ai_lyrics_<uuid>` / `ai_music_<uuid>` checkbox
    - 「部分的に AI を使った音声」の種別は `ai_partial_audio_type_<uuid>` radio
      （value="vocals" / "instruments" の 2 値のみ。100% AI 楽曲では何も選ばない）
    - 「音声すべて AI」「apply_to_all」相当の UI は実 DOM に存在せず、本リポは
      全 track へ同じ設定を一括適用することで apply_to_all を代替する

    - `enabled`: 「はい (AI 使用)」radio を選択するか
    - `lyrics`: 歌詞 AI checkbox を check するか
    - `composition`: 作曲 AI checkbox を check するか
    - `partial_audio_type`: 部分的 AI 音声の種別（`"vocals"` | `"instruments"`）。
      Suno 等の 100% AI 楽曲は `None`（追加開示なし）
    """

    enabled: bool = True
    lyrics: bool = True
    composition: bool = True
    partial_audio_type: str | None = None


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
