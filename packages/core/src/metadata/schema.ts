import { z } from "zod";

import { codepointLength } from "./format.ts";

const MAX_TRACKS = 100;
const MAX_TIMELINE_SECONDS = 24 * 60 * 60;
const MAX_TRACK_TITLE_CODEPOINTS = 200;
const MAX_THEME_CODEPOINTS = 100;
const MAX_COLLECTION_SLUG_CODEPOINTS = 200;
const MAX_SCENE_PHRASE_LANGUAGES = 50;
const MAX_LANGUAGE_CODEPOINTS = 32;
const MAX_SCENE_PHRASE_CODEPOINTS = 100;

const boundedText = (field: string, maxCodepoints: number) =>
  z
    .string()
    .min(1)
    .refine((value) => codepointLength(value) <= maxCodepoints, {
      message: `${field} must be ${maxCodepoints} codepoints or less`,
    });

const GenerateMetadataTrack = z
  .object({
    durationSeconds: z
      .number()
      .finite()
      .int()
      .positive()
      .max(MAX_TIMELINE_SECONDS),
    startSeconds: z
      .number()
      .finite()
      .int()
      .nonnegative()
      .max(MAX_TIMELINE_SECONDS),
    title: boundedText("track title", MAX_TRACK_TITLE_CODEPOINTS),
  })
  .strict();

const ScenePhrases = z
  .record(
    z.string().min(1).max(MAX_LANGUAGE_CODEPOINTS),
    boundedText("scene phrase", MAX_SCENE_PHRASE_CODEPOINTS)
  )
  .refine((value) => Object.keys(value).length <= MAX_SCENE_PHRASE_LANGUAGES, {
    message: `scenePhrases must contain ${MAX_SCENE_PHRASE_LANGUAGES} languages or less`,
  });

export const GenerateMetadataInput = z
  .object({
    collectionSlug: boundedText(
      "collectionSlug",
      MAX_COLLECTION_SLUG_CODEPOINTS
    ).optional(),
    scenePhrases: ScenePhrases.optional(),
    theme: boundedText("theme", MAX_THEME_CODEPOINTS),
    tracks: z.array(GenerateMetadataTrack).nonempty().max(MAX_TRACKS),
  })
  .strict()
  .superRefine((input, ctx) => {
    let previousStartSeconds: number | undefined;
    for (const [index, track] of input.tracks.entries()) {
      if (
        previousStartSeconds !== undefined &&
        previousStartSeconds >= track.startSeconds
      ) {
        ctx.addIssue({
          code: "custom",
          message: "tracks must be sorted by ascending startSeconds",
          path: ["tracks", index, "startSeconds"],
        });
      }
      if (track.startSeconds + track.durationSeconds > MAX_TIMELINE_SECONDS) {
        ctx.addIssue({
          code: "custom",
          message: `track end must be ${MAX_TIMELINE_SECONDS} seconds or less`,
          path: ["tracks", index, "durationSeconds"],
        });
      }
      previousStartSeconds = track.startSeconds;
    }
  });

export const GenerateMetadataOutput = z
  .object({
    description: z.string(),
    localizations: z
      .record(
        z.string(),
        z
          .object({
            description: z.string(),
            title: z.string(),
          })
          .strict()
      )
      .optional(),
    tags: z.array(z.string()),
    timestamps: z.string(),
    title: z.string(),
    violations: z.array(
      z
        .object({
          lang: z.string(),
          length: z.number(),
          template: z.string(),
          title: z.string(),
        })
        .strict()
    ),
  })
  .strict();

export type GenerateMetadataInput = z.infer<typeof GenerateMetadataInput>;
export type GenerateMetadataOutput = z.infer<typeof GenerateMetadataOutput>;
