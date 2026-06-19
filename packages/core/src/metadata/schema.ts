import { z } from "zod";

const GenerateMetadataTrack = z
  .object({
    durationSeconds: z.number(),
    startSeconds: z.number(),
    title: z.string(),
  })
  .strict();

export const GenerateMetadataInput = z
  .object({
    collectionSlug: z.string().optional(),
    scenePhrases: z.record(z.string(), z.string()).optional(),
    theme: z.string(),
    tracks: z.array(GenerateMetadataTrack),
  })
  .strict();

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
