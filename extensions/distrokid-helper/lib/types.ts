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

// AI 開示（distrokid.com/new の各 track ごとの AI 使用開示）。
// 実 DOM 検証（#866）で判明: 「はい/いいえ」radio は ai_gate_<uuid>、歌詞/作曲は
// ai_lyrics_<uuid> / ai_music_<uuid> checkbox、部分的 AI 音声は
// ai_partial_audio_type_<uuid> radio (value="vocals" | "instruments")。
// apply_to_all 相当の UI は実 DOM に存在しないため、全 track へ一括適用で代替する。
export interface AiDisclosure {
  enabled: boolean;
  lyrics: boolean;
  composition: boolean;
  // 部分的 AI 音声の種別。100% AI 楽曲 (Suno 等) は null (追加開示なし)。
  partial_audio_type: "vocals" | "instruments" | null;
}

// `distrokid.profile` セクション（distrokid.com/new フォーム項目に対応する静的プロファイル）。
export interface DistrokidProfile {
  language: string;
  main_genre: string;
  sub_genre: string | null;
  songwriter: SongwriterName | null;
  ai_disclosure: AiDisclosure;
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
