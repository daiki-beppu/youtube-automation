// DistroKid 配信プロファイル設定（merged の `distrokid`・optional/opt-in）。
//
// Python 側の `utils.config.distrokid.DistrokidProfile` と同じ JSON 契約を読み、
// core の公開 API では他 section と同じ camelCase shape へ変換する。
// 形状検証 + `enabled=true` 時の条件付き必須チェックは superRefine で行い、
// 既存テストが期待する `config:` prefix のメッセージ（`distrokid.profile は object ...`
// / 欠落フィールド名）を保持する。

import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";
import { isPlainObject } from "./internal.ts";

// distrokid.enabled === true のとき profile に必須となるフィールド（条件付き必須）。
// artist / songwriter / ai_disclosure は任意（Python 側の REQUIRED_PROFILE_FIELDS と一致）。
const REQUIRED_PROFILE_FIELDS = ["language", "main_genre"] as const;

const SongwriterName = z.object({
  first: z.string(),
  last: z.string(),
  middle: z.string().nullable().default(null),
});

const AiDisclosure = z.object({
  apply_to_all: z.boolean().default(true),
  artist_persona: z.boolean().default(true),
  enabled: z.boolean().default(true),
  lyrics: z.boolean().default(true),
  music: z.boolean().default(true),
  partial_audio_type: z
    .enum(["vocals", "instruments"])
    .nullable()
    .default(null),
  recording_scope: z.enum(["full", "partial"]).default("full"),
});

const DistrokidProfileCredits = z.object({
  performer_role: z.string().default("Synthesizer"),
  producer_role: z.string().default("Producer"),
});

const DistrokidProfile = z.object({
  ai_disclosure: AiDisclosure.prefault({}),
  artist: z.string().default(""),
  credits: DistrokidProfileCredits.prefault({}),
  language: z.string().default(""),
  main_genre: z.string().default(""),
  songwriter: SongwriterName.nullable().default(null),
  sub_genre: z.string().nullable().default(null),
});

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
    // enabled=true のときのみ profile の必須フィールドを条件付き検証（Fail Fast）。
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

const disabledProfileInput = (
  profile: Record<string, unknown>
): Record<string, unknown> => {
  const out: Record<string, unknown> = {};
  if ("artist" in profile) {
    out.artist = profile.artist;
  }
  for (const key of ["language", "main_genre"] as const) {
    const value = profile[key];
    if (typeof value === "string") {
      out[key] = value;
    }
  }
  const subGenre = profile.sub_genre;
  if (typeof subGenre === "string" || subGenre === null) {
    out.sub_genre = subGenre;
  }
  for (const key of ["songwriter", "ai_disclosure", "credits"] as const) {
    const value = profile[key];
    if (value === null || isPlainObject(value)) {
      out[key] = value;
    }
  }
  return out;
};

/** `distrokid` セクション（optional・opt-in）。 */
export const Distrokid = z
  .object({
    distrokid: DistrokidInner.prefault({}),
  })
  .transform((o) => {
    // superRefine の isPlainObject 検証通過済みのため、transform 到達時は常に plain object。
    const profileRaw = o.distrokid.profile as Record<string, unknown>;
    const profile = DistrokidProfile.parse(
      o.distrokid.enabled ? profileRaw : disabledProfileInput(profileRaw)
    );
    return {
      enabled: o.distrokid.enabled,
      profile: snakeToCamel(profile),
    };
  });

export type Distrokid = z.infer<typeof Distrokid>;
