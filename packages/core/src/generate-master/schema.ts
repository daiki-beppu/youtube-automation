import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

export const MASTER_CONFIG_RELATIVE_PATH = "config/skills/masterup.yaml";
export const MASTER_SOURCE_DIR = "02-Individual-music";
export const MASTER_OUTPUT_DIR = "01-master";
export const MASTER_OUTPUT_BASENAME = "master";
export const SUPPORTED_AUDIO_EXTENSIONS = ["mp3", "wav"] as const;

const GenerateMasterSnakeInputSchema = z
  .object({
    collection: z.string(),
    loop: z.number().int().positive().optional(),
    pin_first: z.array(z.string()).min(1).optional(),
    pin_first_count: z.number().int().nonnegative().optional(),
    shuffle: z.boolean().optional(),
    shuffle_seed: z.number().int().optional(),
    target_duration: z.number().positive().optional(),
  })
  .strict();

const GenerateMasterCamelInputSchema = z
  .object({
    collection: z.string(),
    loop: z.number().int().positive().optional(),
    pinFirst: z.array(z.string()).min(1).optional(),
    pinFirstCount: z.number().int().nonnegative().optional(),
    shuffle: z.boolean().optional(),
    shuffleSeed: z.number().int().optional(),
    targetDuration: z.number().positive().optional(),
  })
  .strict();

const validateInput = (
  input: z.infer<typeof GenerateMasterCamelInputSchema>,
  context: z.RefinementCtx
): void => {
  if (input.loop !== undefined && input.targetDuration !== undefined) {
    context.addIssue({
      code: "custom",
      message: "loop and target_duration cannot be used together",
      path: ["target_duration"],
    });
  }
  if (input.pinFirst !== undefined && input.pinFirstCount !== undefined) {
    context.addIssue({
      code: "custom",
      message: "pin_first and pin_first_count cannot be used together",
      path: ["pin_first"],
    });
  }
};

export const GenerateMasterInputSchema = z
  .union([GenerateMasterSnakeInputSchema, GenerateMasterCamelInputSchema])
  .transform(
    (input): z.infer<typeof GenerateMasterCamelInputSchema> =>
      snakeToCamel(input)
  )
  .superRefine(validateInput);

export const GenerateMasterOutputSchema = z
  .object({
    audioExt: z.enum(SUPPORTED_AUDIO_EXTENSIONS),
    copied: z.boolean(),
    inputCount: z.number().int().positive(),
    loops: z.number().int().positive(),
    outputPath: z.string(),
    segmentCount: z.number().int().positive(),
    shuffleSeed: z.number().int().optional(),
  })
  .strict();

const MasterupAudioConfigSchema = z
  .object({
    bitrate: z.string().trim().min(1).optional(),
    crossfade_duration: z.number().positive().optional(),
    finalize: z.unknown().optional(),
    pin_first_count: z.number().int().nonnegative().optional(),
    shuffle: z.boolean().optional(),
    shuffle_seed: z.number().int().optional(),
    target_duration_min: z.number().int().positive().optional(),
    target_video_duration_min: z.number().positive().optional(),
  })
  .strict();

export const MasterupConfigSchema = z
  .object({
    audio: MasterupAudioConfigSchema.optional(),
  })
  .passthrough();

export type GenerateMasterInput = z.infer<typeof GenerateMasterInputSchema>;
export type GenerateMasterOutput = z.infer<typeof GenerateMasterOutputSchema>;
export type MasterupConfig = z.infer<typeof MasterupConfigSchema>;
export type SupportedAudioExtension =
  (typeof SUPPORTED_AUDIO_EXTENSIONS)[number];
