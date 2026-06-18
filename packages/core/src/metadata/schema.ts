import { z } from "zod";

import type { ChannelConfig } from "../config/config.ts";

const ChannelConfigValue = z.custom<ChannelConfig>(
  (value) => typeof value === "object" && value !== null,
  "ChannelConfig is required"
);

const TimestampTrack = z
  .object({
    patternKey: z.string().nullable().optional(),
    timestamp: z.string(),
    title: z.string(),
  })
  .strict();

const ThemeInline = z
  .object({
    prefix: z.string(),
    suffix: z.string(),
  })
  .strict();

const LocalizedText = z
  .object({
    description: z.string(),
    title: z.string(),
  })
  .strict();

export const VideoMetadataInput = z
  .object({
    collectionName: z.string(),
    config: ChannelConfigValue,
    description: z
      .object({
        sectionHeaders: z
          .object({
            channelLinkTemplate: z.string(),
            perfectFor: z.string(),
            usageAttribution: z.string(),
          })
          .strict(),
        usageLines: z.array(z.string()),
      })
      .strict(),
    localizations: z
      .object({
        scenePhrases: z.record(z.string(), z.string()),
        sectionHeaders: z
          .object({
            channelLinkTemplate: z.string(),
            trackList: z.string(),
            usageAttribution: z.string(),
          })
          .strict(),
      })
      .strict(),
    timestamps: z
      .object({
        themeInline: ThemeInline,
        themeNames: z.record(z.string(), z.string()),
        tracks: z.array(TimestampTrack),
      })
      .strict(),
    title: z
      .object({
        activities: z.string(),
        activity: z.string(),
        durationDisplay: z.string(),
        durationShort: z.string(),
        sceneEmoji: z.string(),
        scenePhrase: z.string(),
        theme: z.string(),
      })
      .strict(),
  })
  .strict();
export type VideoMetadataInput = z.infer<typeof VideoMetadataInput>;

export const VideoMetadataOutput = z
  .object({
    description: z.string(),
    localizations: z.record(z.string(), LocalizedText),
    tags: z.array(z.string()),
    title: z.string(),
  })
  .strict();
export type VideoMetadataOutput = z.infer<typeof VideoMetadataOutput>;
