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
    """AI 開示（distrokid.com/new の AI 使用開示）.

    実 DOM 再検証（#877）で判明した構造: AI 開示は inline 展開ではなく SweetAlert2 ベースの
    modal（`.ai-credits-swal-modal`）で開く。「はい/いいえ」の `ai_gate_<uuid>` radio で「はい」を
    選ぶと modal が mount し、modal 内で以下を設定して「保存」する。modal の
    「Apply these selections to all songs on this release」checkbox を入れると全 track に伝播する。

    - `enabled`: 「はい (AI 使用)」radio を選択して modal を開くか
    - `lyrics`: 歌詞 AI checkbox（`ai_lyrics_<uuid>` / `.distroAiLyrics`）を check するか
    - `music`: 作曲 AI checkbox（`ai_music_<uuid>` / `.distroAiMusic`）を check するか
    - `recording_scope`: 録音物の AI 範囲（`.distroAiRecordingScope`）。
      `"full"`（音声すべて）| `"partial"`（音声の一部）
    - `partial_audio_type`: `recording_scope="partial"` 時の種別
      （`"vocals"` | `"instruments"`）。`"full"` の場合は `None`
    - `artist_persona`: アーティストが AI ペルソナか（`.distroAiArtistPersona`）。
      `True` = AI ペルソナ（value=1）/ `False` = 人間アーティスト（value=0）。
      Suno 等の生成チャンネルは `True` が運用上の正解
    - `apply_to_all`: modal の Apply-to-all checkbox を入れて全 track に伝播するか
    """

    enabled: bool = True
    lyrics: bool = True
    music: bool = True
    recording_scope: str = "full"
    partial_audio_type: str | None = None
    artist_persona: bool = True
    apply_to_all: bool = True


@dataclass(frozen=True)
class DistrokidProfileCredits:
    """Apple Music クレジット既定値（distrokid.com/new の track credits 行）.

    各トラックの credits は performer 行と producer 行のペアで構成される（実 DOM 検証済み・#919）。
    人名（`track-N-performer-1-name` / `track-N-producer-1-name`）は DistroKid 側で
    アルバム artist で自動フィルされるため、本 dataclass では役割（role select）の既定値
    のみを保持する。SELECT の `value` 属性に対応する英語値で指定する（i18n は DistroKid 側）。

    - `performer_role`: performer 行の role（`track-N-performer-1-role` の SELECT value）。
      実 DOM 検証（#930 / 2026-06-11）: 84 options・楽器名のみ。`"Audio"` は存在しない。
      AI 制作 BGM は `"Synthesizer"` を既定とする。
    - `producer_role`: producer 行の role（`track-N-producer-1-role` の SELECT value）。
      `"Producer"`（プロデューサー）を既定とする。40 options。
    """

    performer_role: str = "Synthesizer"
    producer_role: str = "Producer"


@dataclass(frozen=True)
class DistrokidProfile:
    """`distrokid.profile` セクション（distrokid.com/new フォーム項目に対応）.

    - `language`: メタデータ言語（language SELECT の value）
    - `main_genre`: メインジャンル（genrePrimary SELECT の value）
    - `sub_genre`: サブジャンル（genreSecondary SELECT の value、任意）
    - `songwriter`: 作曲者の本名（任意、省略時はトラック側で手入力）
    - `ai_disclosure`: AI 開示モーダルの設定（既定は全 AI 開示）
    - `credits`: Apple Music クレジットの既定値（既定は Synthesizer + Producer）
    """

    language: str = ""
    main_genre: str = ""
    sub_genre: str | None = None
    songwriter: SongwriterName | None = None
    ai_disclosure: AiDisclosure = field(default_factory=AiDisclosure)
    credits: DistrokidProfileCredits = field(default_factory=DistrokidProfileCredits)


@dataclass(frozen=True)
class Distrokid:
    """`distrokid` セクション（optional・opt-in）.

    - `enabled`: distrokid 連携を有効にするか（`comments.enabled` と対称のオプトイン）
    - `profile`: 配信時に使う静的プロファイル
    """

    enabled: bool = False
    profile: DistrokidProfile = field(default_factory=DistrokidProfile)
