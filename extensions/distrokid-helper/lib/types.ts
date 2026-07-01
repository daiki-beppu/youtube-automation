// `/distrokid/release.json` の JSON 契約型。
//
// サーバー側 SSOT:
//   - src/youtube_automation/scripts/distrokid_release.py::build_release_payload
//   - src/youtube_automation/utils/config/distrokid.py::DistrokidProfile
// envelope は { profile, release } の 2 層。profile は静的（config 由来）、
// release はコレクション動的データ（アルバム名 / 曲 / ジャケット / リリース日）。
//
// schema は #813 で実 DOM 検証に基づき再設計した（Python の dataclass と 1:1）。
// 旧フラット 6 文字列（artist_name / apple_music_credit / track_type 等）は撤廃。

// 作曲者の本名（distrokid.com/new は first/middle/last の 3 欄に分割）。
export interface SongwriterName {
  first: string;
  last: string;
  middle: string | null;
}

// AI 開示（distrokid.com/new の AI 使用開示）。
// 実 DOM 再検証（#877）で判明: AI 開示は inline ではなく SweetAlert2 modal
// (.ai-credits-swal-modal) で開く。ai_gate_<uuid> radio で「はい」を選ぶと modal が mount し、
// modal 内で歌詞 / 作曲 / 録音範囲 / アーティスト種別 / apply-all を設定して保存する。
// Python の utils.config.distrokid.AiDisclosure と 1:1。
export interface AiDisclosure {
  enabled: boolean;
  lyrics: boolean;
  music: boolean;
  // 録音物の AI 範囲。"full"=音声すべて / "partial"=音声の一部。
  recording_scope: "full" | "partial";
  // recording_scope="partial" 時の種別。"full" のときは null。
  partial_audio_type: "vocals" | "instruments" | null;
  // true = AI ペルソナ (value=1) / false = 人間アーティスト (value=0)。
  artist_persona: boolean;
  // modal の Apply-to-all checkbox を入れて全 track へ伝播するか。
  apply_to_all: boolean;
}

// Apple Music の track credits 行（performer 行 / producer 行）の既定 role。
// 実 DOM の `#track-N-performer-1-role`（86 options）/ `#track-N-producer-1-role`
// （40 options）の SELECT value に対応する英語値。
// Python の utils.config.distrokid.DistrokidProfileCredits と 1:1（#919）。
export interface DistrokidProfileCredits {
  performer_role: string;
  producer_role: string;
}

// `distrokid.profile` セクション（distrokid.com/new フォーム項目に対応する静的プロファイル）。
export interface DistrokidProfile {
  artist: string;
  language: string;
  main_genre: string;
  sub_genre: string | null;
  songwriter: SongwriterName | null;
  ai_disclosure: AiDisclosure;
  credits: DistrokidProfileCredits;
}

// 1 トラックのメタ + asset 参照（asset_path は "/distrokid/assets/" 接頭辞込み）。
export interface ReleaseTrack {
  title: string;
  filename: string;
  asset_path: string;
}

// ジャケット画像の asset 参照。コレクションに無ければ release.cover は null。
export interface ReleaseCover {
  filename: string;
  asset_path: string;
}

// コレクション由来の動的リリースデータ。
export interface ReleaseData {
  album_title: string;
  tracks: ReleaseTrack[];
  cover: ReleaseCover | null;
  // workflow-state の publish_target_at（未確定なら null）。
  release_date: string | null;
}

// `/distrokid/release.json` のトップレベル envelope。
export interface ReleasePayload {
  profile: DistrokidProfile;
  release: ReleaseData;
}
