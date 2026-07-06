import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

export const DEFAULT_BITRATE = "192k";
export const DEFAULT_CROSSFADE_DURATION = 1;

const inputSpecifiedFields = [
  ["bitrate", "bitrate"],
  ["crossfade_duration", "crossfadeDuration"],
  ["pin_first_count", "pinFirstCount"],
  ["shuffle", "shuffle"],
  ["shuffle_seed", "shuffleSeed"],
  ["target_duration_min", "targetDurationMin"],
] as const;

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

const GenerateMasterRawInputSchema = z.preprocess(
  withInputPresence,
  z
    .object({
      __specified: z.object({
        bitrate: z.boolean(),
        crossfadeDuration: z.boolean(),
        pinFirstCount: z.boolean(),
        shuffle: z.boolean(),
        shuffleSeed: z.boolean(),
        targetDurationMin: z.boolean(),
      }),
      bitrate: z.string().default(DEFAULT_BITRATE),
      channel_dir: z.string().optional(),
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
      if (input.loop !== undefined && input.target_duration_min !== undefined) {
        ctx.addIssue({
          code: "custom",
          message: "loop and target_duration_min are mutually exclusive",
          path: ["target_duration_min"],
        });
      }
      if (input.no_loop && input.target_duration_min !== undefined) {
        ctx.addIssue({
          code: "custom",
          message: "no_loop and target_duration_min are mutually exclusive",
          path: ["target_duration_min"],
        });
      }
      if (input.pin_first.length > 0 && input.pin_first_count !== undefined) {
        ctx.addIssue({
          code: "custom",
          message: "pin_first and pin_first_count are mutually exclusive",
          path: ["pin_first_count"],
        });
      }
    })
);

const GenerateMasterExternalInputSchema =
  GenerateMasterRawInputSchema.transform((input) => {
    const { __specified, ...externalInput } = input;
    void __specified;
    return snakeToCamel(externalInput);
  });

const GenerateMasterInternalInputSchema = z
  .object({
    bitrate: z.string(),
    channelDir: z.string().optional(),
    collection: z.string().min(1).optional(),
    crossfadeDuration: z.number().positive(),
    loop: z.number().int().positive().optional(),
    noLoop: z.boolean(),
    pinFirst: z.array(z.string().min(1)),
    pinFirstCount: z.number().int().nonnegative().optional(),
    shuffle: z.boolean(),
    shuffleSeed: z.number().int().optional(),
    specified: z
      .object({
        bitrate: z.boolean(),
        crossfadeDuration: z.boolean(),
        pinFirstCount: z.boolean(),
        shuffle: z.boolean(),
        shuffleSeed: z.boolean(),
        targetDurationMin: z.boolean(),
      })
      .strict(),
    targetDurationMin: z.number().int().positive().optional(),
  })
  .strict()
  .superRefine((input, ctx) => {
    if (input.loop !== undefined && input.targetDurationMin !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "loop and targetDurationMin are mutually exclusive",
        path: ["targetDurationMin"],
      });
    }
    if (input.noLoop && input.targetDurationMin !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "noLoop and targetDurationMin are mutually exclusive",
        path: ["targetDurationMin"],
      });
    }
    if (input.pinFirst.length > 0 && input.pinFirstCount !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "pinFirst and pinFirstCount are mutually exclusive",
        path: ["pinFirstCount"],
      });
    }
  });

const GenerateMasterCamelInputSchema = z
  .object({
    bitrate: z.string(),
    channelDir: z.string().optional(),
    collection: z.string().min(1).optional(),
    crossfadeDuration: z.number().positive(),
    loop: z.number().int().positive().optional(),
    noLoop: z.boolean(),
    pinFirst: z.array(z.string().min(1)),
    pinFirstCount: z.number().int().nonnegative().optional(),
    shuffle: z.boolean(),
    shuffleSeed: z.number().int().optional(),
    targetDurationMin: z.number().int().positive().optional(),
  })
  .strict()
  .superRefine((input, ctx) => {
    if (input.loop !== undefined && input.targetDurationMin !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "loop and targetDurationMin are mutually exclusive",
        path: ["targetDurationMin"],
      });
    }
    if (input.noLoop && input.targetDurationMin !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "noLoop and targetDurationMin are mutually exclusive",
        path: ["targetDurationMin"],
      });
    }
    if (input.pinFirst.length > 0 && input.pinFirstCount !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "pinFirst and pinFirstCount are mutually exclusive",
        path: ["pinFirstCount"],
      });
    }
  });

const GenerateMasterRawServiceInputSchema =
  GenerateMasterRawInputSchema.transform((input) => {
    const { __specified, ...externalInput } = input;
    return {
      ...snakeToCamel(externalInput),
      specified: __specified,
    };
  });

const unspecifiedFields = Object.fromEntries(
  inputSpecifiedFields.map(([, outputField]) => [outputField, false])
) as GenerateMasterInternalInput["specified"];

const GenerateMasterExternalServiceInputSchema =
  GenerateMasterCamelInputSchema.transform((input) => ({
    ...input,
    specified: unspecifiedFields,
  }));

export const GenerateMasterInputSchema = GenerateMasterExternalInputSchema;

export const GenerateMasterServiceInputSchema =
  GenerateMasterRawServiceInputSchema;

export const ParseableGenerateMasterInputSchema = z.union([
  GenerateMasterInternalInputSchema,
  GenerateMasterRawServiceInputSchema,
  GenerateMasterExternalServiceInputSchema,
]);

export const GenerateMasterOutputSchema = z
  .object({
    bitrate: z.string(),
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
