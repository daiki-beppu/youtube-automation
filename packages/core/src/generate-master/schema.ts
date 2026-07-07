import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

export const DEFAULT_BITRATE = "192k";
export const DEFAULT_CROSSFADE_DURATION = 1;

const BitrateSchema = z.string().trim().min(1);
const ChannelDirSchema = z.string().trim().min(1);

const inputSpecifiedFields = [
  ["bitrate", "bitrate"],
  ["crossfade_duration", "crossfadeDuration"],
  ["pin_first_count", "pinFirstCount"],
  ["shuffle", "shuffle"],
  ["shuffle_seed", "shuffleSeed"],
  ["target_duration_min", "targetDurationMin"],
] as const;

const GenerateMasterSpecifiedSchema = z
  .object({
    bitrate: z.boolean(),
    crossfadeDuration: z.boolean(),
    pinFirstCount: z.boolean(),
    shuffle: z.boolean(),
    shuffleSeed: z.boolean(),
    targetDurationMin: z.boolean(),
  })
  .strict();

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const withInputPresence = (value: unknown): unknown => {
  if (!isRecord(value)) {
    return value;
  }
  return {
    ...value,
    __specified: Object.fromEntries(
      inputSpecifiedFields.map(([inputField, outputField]) => [
        outputField,
        Object.hasOwn(value, inputField),
      ])
    ),
  };
};

interface GenerateMasterInvariantInput {
  loop?: number;
  noLoop: boolean;
  pinFirst: string[];
  pinFirstCount?: number;
  targetDurationMin?: number;
}

interface GenerateMasterInvariantPaths {
  pinFirstCount: string;
  targetDurationMin: string;
}

const addGenerateMasterInvariantIssues = (
  input: GenerateMasterInvariantInput,
  ctx: z.RefinementCtx,
  paths: GenerateMasterInvariantPaths
): void => {
  if (input.loop !== undefined && input.targetDurationMin !== undefined) {
    ctx.addIssue({
      code: "custom",
      message: `loop and ${paths.targetDurationMin} are mutually exclusive`,
      path: [paths.targetDurationMin],
    });
  }
  if (input.noLoop && input.targetDurationMin !== undefined) {
    ctx.addIssue({
      code: "custom",
      message: `noLoop and ${paths.targetDurationMin} are mutually exclusive`,
      path: [paths.targetDurationMin],
    });
  }
  if (input.pinFirst.length > 0 && input.pinFirstCount !== undefined) {
    ctx.addIssue({
      code: "custom",
      message: `pinFirst and ${paths.pinFirstCount} are mutually exclusive`,
      path: [paths.pinFirstCount],
    });
  }
};

const GenerateMasterRawInputSchema = z.preprocess(
  withInputPresence,
  z
    .object({
      __specified: GenerateMasterSpecifiedSchema,
      bitrate: BitrateSchema.default(DEFAULT_BITRATE),
      channel_dir: ChannelDirSchema.optional(),
      collection: z.string().min(1).optional(),
      crossfade_duration: z
        .number()
        .positive()
        .default(DEFAULT_CROSSFADE_DURATION),
      loop: z.number().int().positive().optional(),
      no_loop: z.boolean().default(false),
      pin_first: z.array(z.string().min(1)).default([]),
      pin_first_count: z.number().int().nonnegative().optional(),
      shuffle: z.boolean().default(false),
      shuffle_seed: z.number().int().optional(),
      target_duration_min: z.number().int().positive().optional(),
    })
    .strict()
    .superRefine((input, ctx) => {
      addGenerateMasterInvariantIssues(
        {
          loop: input.loop,
          noLoop: input.no_loop,
          pinFirst: input.pin_first,
          pinFirstCount: input.pin_first_count,
          targetDurationMin: input.target_duration_min,
        },
        ctx,
        {
          pinFirstCount: "pin_first_count",
          targetDurationMin: "target_duration_min",
        }
      );
    })
);

const GenerateMasterInternalInputSchema = z
  .object({
    bitrate: BitrateSchema,
    channelDir: ChannelDirSchema.optional(),
    collection: z.string().min(1).optional(),
    crossfadeDuration: z.number().positive(),
    loop: z.number().int().positive().optional(),
    noLoop: z.boolean(),
    pinFirst: z.array(z.string().min(1)),
    pinFirstCount: z.number().int().nonnegative().optional(),
    shuffle: z.boolean(),
    shuffleSeed: z.number().int().optional(),
    specified: GenerateMasterSpecifiedSchema,
    targetDurationMin: z.number().int().positive().optional(),
  })
  .strict()
  .superRefine((input, ctx) => {
    addGenerateMasterInvariantIssues(input, ctx, {
      pinFirstCount: "pinFirstCount",
      targetDurationMin: "targetDurationMin",
    });
  });

const GenerateMasterRawServiceInputSchema =
  GenerateMasterRawInputSchema.transform((input) => {
    const { __specified, ...externalInput } = input;
    return {
      ...snakeToCamel(externalInput),
      specified: __specified,
    };
  });

export const GenerateMasterInputSchema = GenerateMasterRawServiceInputSchema;

export const GenerateMasterServiceInputSchema =
  GenerateMasterRawServiceInputSchema;

export const ParseableGenerateMasterInputSchema = z.union([
  GenerateMasterInternalInputSchema,
  GenerateMasterRawServiceInputSchema,
]);

export const GenerateMasterOutputSchema = z
  .object({
    bitrate: BitrateSchema,
    crossfadeDuration: z.number().positive(),
    durationPreview: z
      .object({
        estimatedSeconds: z.number().nonnegative(),
        targetSeconds: z.number().positive().optional(),
        trackTotalSeconds: z.number().nonnegative(),
      })
      .strict()
      .optional(),
    inputCount: z.number().int().nonnegative(),
    loopCount: z.number().int().positive(),
    messages: z.array(z.string()),
    outputPath: z.string(),
    segmentCount: z.number().int().nonnegative(),
  })
  .strict();

export type GenerateMasterInternalInput = z.infer<
  typeof GenerateMasterInternalInputSchema
>;
export type GenerateMasterInput = z.infer<typeof GenerateMasterInputSchema>;
export type GenerateMasterServiceInput = z.infer<
  typeof GenerateMasterServiceInputSchema
>;
export type GenerateMasterOutput = z.infer<typeof GenerateMasterOutputSchema>;
