// DistroKid 配信プロファイル設定（Python `distrokid.py` + loader の移植・optional/opt-in）。

import { ConfigError } from "../errors.ts";
import { asRecord, isRecord } from "./internal.ts";

// distrokid.enabled === true のとき profile に必須となるフィールド（条件付き必須）。
const REQUIRED_PROFILE_FIELDS = [
  "artist_name",
  "language",
  "main_genre",
  "songwriter",
  "apple_music_credit",
  "track_type",
] as const;

/** `distrokid.profile` セクション（distrokid.com/new フォーム項目に対応）。 */
interface DistrokidProfile {
  readonly artistName: string;
  readonly language: string;
  readonly mainGenre: string;
  readonly songwriter: string;
  readonly appleMusicCredit: string;
  readonly trackType: string;
}

/** `distrokid` セクション（optional・opt-in）。 */
export interface Distrokid {
  readonly enabled: boolean;
  readonly profile: DistrokidProfile;
}

const emptyProfile = (): DistrokidProfile => ({
  appleMusicCredit: "",
  artistName: "",
  language: "",
  mainGenre: "",
  songwriter: "",
  trackType: "",
});

export const parseDistrokid = (merged: Record<string, unknown>): Distrokid => {
  const raw = merged.distrokid;
  if (raw === undefined || raw === null) {
    return { enabled: false, profile: emptyProfile() };
  }
  if (!isRecord(raw)) {
    throw new ConfigError("distrokid セクションは object でなければなりません");
  }

  const enabled = (raw.enabled as boolean | undefined) ?? false;
  const profileRoot = asRecord(raw.profile, "distrokid.profile");

  // enabled=true のときのみ profile の必須 6 フィールドを条件付き検証（Fail Fast）。
  if (enabled) {
    const missing = REQUIRED_PROFILE_FIELDS.filter((f) => !profileRoot[f]);
    if (missing.length > 0) {
      throw new ConfigError(
        `distrokid.enabled=true のとき distrokid.profile に必須フィールドがありません: ${missing.join(", ")}`
      );
    }
  }

  return {
    enabled,
    profile: {
      appleMusicCredit:
        (profileRoot.apple_music_credit as string | undefined) ?? "",
      artistName: (profileRoot.artist_name as string | undefined) ?? "",
      language: (profileRoot.language as string | undefined) ?? "",
      mainGenre: (profileRoot.main_genre as string | undefined) ?? "",
      songwriter: (profileRoot.songwriter as string | undefined) ?? "",
      trackType: (profileRoot.track_type as string | undefined) ?? "",
    },
  };
};
