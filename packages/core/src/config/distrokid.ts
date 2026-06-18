import { z } from "zod";

import { isPlainObject } from "./internal.ts";

const REQUIRED_PROFILE_FIELDS = ["language", "main_genre"] as const;

const AI_DISCLOSURE_DEFAULTS = {
  apply_to_all: true,
  artist_persona: true,
  enabled: true,
  lyrics: true,
  music: true,
  partial_audio_type: null,
  recording_scope: "full",
} as const;

const CREDIT_DEFAULTS = {
  performer_role: "Synthesizer",
  producer_role: "Producer",
} as const;

const Songwriter = z
  .object({
    first: z.string().optional(),
    last: z.string().optional(),
    middle: z.string().optional(),
  })
  .strict();

const AiDisclosure = z
  .object({
    apply_to_all: z.boolean().default(AI_DISCLOSURE_DEFAULTS.apply_to_all),
    artist_persona: z.boolean().default(AI_DISCLOSURE_DEFAULTS.artist_persona),
    enabled: z.boolean().default(AI_DISCLOSURE_DEFAULTS.enabled),
    lyrics: z.boolean().default(AI_DISCLOSURE_DEFAULTS.lyrics),
    music: z.boolean().default(AI_DISCLOSURE_DEFAULTS.music),
    partial_audio_type: z
      .enum(["vocals", "instruments"])
      .nullable()
      .default(AI_DISCLOSURE_DEFAULTS.partial_audio_type),
    recording_scope: z
      .enum(["full", "partial"])
      .default(AI_DISCLOSURE_DEFAULTS.recording_scope),
  })
  .strict()
  .superRefine((ai, ctx) => {
    if (ai.partial_audio_type !== null && ai.recording_scope !== "partial") {
      ctx.addIssue({
        code: "custom",
        message:
          "distrokid.profile.ai_disclosure.partial_audio_type requires recording_scope=partial",
        path: ["recording_scope"],
      });
    }
  });

const Credits = z
  .object({
    performer_role: z.string().default(CREDIT_DEFAULTS.performer_role),
    producer_role: z.string().default(CREDIT_DEFAULTS.producer_role),
  })
  .strict();

const Profile = z
  .object({
    ai_disclosure: AiDisclosure.prefault({}),
    credits: Credits.prefault({}),
    language: z.string().default(""),
    main_genre: z.string().default(""),
    songwriter: Songwriter.nullable().default(null),
    sub_genre: z.string().optional(),
  })
  .strict();

const DistrokidInner = z
  .object({
    enabled: z.boolean().default(false),
    profile: z.unknown().prefault({}),
  })
  .superRefine((dk, ctx) => {
    const { profile } = dk;
    if (!isPlainObject(profile)) {
      ctx.addIssue({
        code: "custom",
        message: "distrokid.profile は object でなければなりません",
        path: ["profile"],
      });
      return;
    }
    if (dk.enabled) {
      const missing = REQUIRED_PROFILE_FIELDS.filter((field) => {
        const value = profile[field];
        return typeof value !== "string" || value.length === 0;
      });
      if (missing.length > 0) {
        ctx.addIssue({
          code: "custom",
          message: `distrokid.enabled=true のとき distrokid.profile に必須フィールドがありません: ${missing.join(", ")}`,
          path: ["profile"],
        });
      }
    }
  });

export const Distrokid = z
  .object({
    distrokid: DistrokidInner.prefault({}),
  })
  .transform((o) => {
    const profile = Profile.parse(o.distrokid.profile);
    return {
      enabled: o.distrokid.enabled,
      profile: {
        aiDisclosure: {
          applyToAll: profile.ai_disclosure.apply_to_all,
          artistPersona: profile.ai_disclosure.artist_persona,
          enabled: profile.ai_disclosure.enabled,
          lyrics: profile.ai_disclosure.lyrics,
          music: profile.ai_disclosure.music,
          partialAudioType: profile.ai_disclosure.partial_audio_type,
          recordingScope: profile.ai_disclosure.recording_scope,
        },
        credits: {
          performerRole: profile.credits.performer_role,
          producerRole: profile.credits.producer_role,
        },
        language: profile.language,
        mainGenre: profile.main_genre,
        songwriter: profile.songwriter,
        subGenre: profile.sub_genre,
      },
    };
  });

export type Distrokid = z.infer<typeof Distrokid>;
