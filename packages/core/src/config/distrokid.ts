// DistroKid 配信プロファイル設定（merged の `distrokid`・optional/opt-in）。
//
// 形状検証 + `enabled=true` 時の条件付き必須チェックは superRefine で行い、
// 既存テストが期待する `config:` prefix のメッセージ（`distrokid.profile は object ...`
// / 欠落フィールド名）を保持する。

import { z } from "zod";

import { isPlainObject } from "./internal.ts";

// distrokid.enabled === true のとき profile に必須となるフィールド（条件付き必須）。
const REQUIRED_PROFILE_FIELDS = [
  "artist_name",
  "language",
  "main_genre",
  "songwriter",
  "apple_music_credit",
  "track_type",
] as const;

const DistrokidInner = z
  .object({
    enabled: z.boolean().default(false),
    profile: z.unknown().prefault({}),
  })
  .superRefine((dk, ctx) => {
    if (!isPlainObject(dk.profile)) {
      ctx.addIssue({
        code: "custom",
        message: "distrokid.profile は object でなければなりません",
        path: ["profile"],
      });
      return;
    }
    const { profile } = dk;
    // enabled=true のときのみ profile の必須 6 フィールドを条件付き検証（Fail Fast）。
    if (dk.enabled) {
      const missing = REQUIRED_PROFILE_FIELDS.filter((f) => !profile[f]);
      if (missing.length > 0) {
        ctx.addIssue({
          code: "custom",
          message: `distrokid.enabled=true のとき distrokid.profile に必須フィールドがありません: ${missing.join(", ")}`,
          path: ["profile"],
        });
      }
    }
  });

const str = (value: unknown): string =>
  typeof value === "string" ? value : "";

/** `distrokid` セクション（optional・opt-in）。 */
export const Distrokid = z
  .object({
    distrokid: DistrokidInner.prefault({}),
  })
  .transform((o) => {
    // superRefine の isPlainObject 検証通過済みのため、transform 到達時は常に plain object。
    const profile = o.distrokid.profile as Record<string, unknown>;
    return {
      enabled: o.distrokid.enabled,
      profile: {
        appleMusicCredit: str(profile.apple_music_credit),
        artistName: str(profile.artist_name),
        language: str(profile.language),
        mainGenre: str(profile.main_genre),
        songwriter: str(profile.songwriter),
        trackType: str(profile.track_type),
      },
    };
  });

export type Distrokid = z.infer<typeof Distrokid>;
