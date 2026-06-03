// `/distrokid/release.json` の JSON 契約型。
//
// サーバー側 SSOT:
//   - src/youtube_automation/scripts/distrokid_release.py::build_release_payload
//   - src/youtube_automation/utils/config/distrokid.py::DistrokidProfile
// envelope は { profile, release } の 2 層。profile は静的（config 由来）、
// release はコレクション動的データ（アルバム名 / 曲 / ジャケット / リリース日）。

// `distrokid.profile` セクション（distrokid.com/new フォーム項目に対応する静的プロファイル）。
export interface DistrokidProfile {
  artist_name: string;
  language: string;
  main_genre: string;
  songwriter: string;
  apple_music_credit: string;
  track_type: string;
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
