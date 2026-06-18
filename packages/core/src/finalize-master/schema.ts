import { z } from "zod";

export const MASTER_FILENAME = "master.mp3";
export const MASTER_TMP_FILENAME = "master.tmp.mp3";
export const MASTERUP_CONFIG_FILENAME = "masterup.json";

export const BRANDING_DIRNAME = "branding";
export const DEFAULT_LAYERS_DIRNAME = "rain_layers";
export const DEFAULT_LAYERS_GLOB = "rain_*.wav";

const DEFAULT_VOLUME_DB = -19;
const DEFAULT_FADEIN_S = 0.5;
const DEFAULT_FADEIN_CURVE = "tri";
const DEFAULT_LOUDNORM = { I: -14, LRA: 11, TP: -1.5 } as const;
const DEFAULT_LOUDNORM_ENABLED = true;
const DEFAULT_LOUDNORM_MODE = "linear";
const DEFAULT_MIX_DURATION = "first";
const DEFAULT_MIX_NORMALIZE = 0;
const DEFAULT_BITRATE = "192k";
const DEFAULT_CODEC = "libmp3lame";

const RAW_AMBIENT_LAYERS_DEFAULT = {
  dirname: DEFAULT_LAYERS_DIRNAME,
  fadein_curve: DEFAULT_FADEIN_CURVE,
  fadein_s: DEFAULT_FADEIN_S,
  glob: DEFAULT_LAYERS_GLOB,
  layers: {},
  volume_db: DEFAULT_VOLUME_DB,
} as const;

const RAW_LOUDNORM_DEFAULT = {
  I: DEFAULT_LOUDNORM.I,
  LRA: DEFAULT_LOUDNORM.LRA,
  TP: DEFAULT_LOUDNORM.TP,
  enabled: DEFAULT_LOUDNORM_ENABLED,
  mode: DEFAULT_LOUDNORM_MODE,
} as const;

const RAW_MIX_DEFAULT = {
  duration: DEFAULT_MIX_DURATION,
  normalize: DEFAULT_MIX_NORMALIZE,
} as const;

const RAW_FINALIZE_DEFAULT = {
  ambient_layers: RAW_AMBIENT_LAYERS_DEFAULT,
  codec: DEFAULT_CODEC,
  loudnorm: RAW_LOUDNORM_DEFAULT,
  mix: RAW_MIX_DEFAULT,
} as const;

const RawLayerOverrideSchema = z
  .object({
    fadein_curve: z.string().optional(),
    fadein_s: z.coerce.number().finite().optional(),
    volume_db: z.coerce.number().finite().optional(),
  })
  .passthrough();

const RawAmbientLayersConfigSchema = z
  .object({
    dirname: z.string().default(DEFAULT_LAYERS_DIRNAME),
    fadein_curve: z.string().default(DEFAULT_FADEIN_CURVE),
    fadein_s: z.coerce.number().finite().default(DEFAULT_FADEIN_S),
    glob: z.string().default(DEFAULT_LAYERS_GLOB),
    layers: z.record(z.string(), RawLayerOverrideSchema).default({}),
    volume_db: z.coerce.number().finite().default(DEFAULT_VOLUME_DB),
  })
  .passthrough()
  .default(RAW_AMBIENT_LAYERS_DEFAULT);

const RawLoudnormConfigSchema = z
  .object({
    I: z.coerce.number().finite().default(DEFAULT_LOUDNORM.I),
    LRA: z.coerce.number().finite().default(DEFAULT_LOUDNORM.LRA),
    TP: z.coerce.number().finite().default(DEFAULT_LOUDNORM.TP),
    enabled: z.boolean().default(DEFAULT_LOUDNORM_ENABLED),
    mode: z.string().default(DEFAULT_LOUDNORM_MODE),
  })
  .passthrough()
  .default(RAW_LOUDNORM_DEFAULT);

const RawMixConfigSchema = z
  .object({
    duration: z.string().default(DEFAULT_MIX_DURATION),
    normalize: z
      .union([z.boolean(), z.coerce.number()])
      .default(DEFAULT_MIX_NORMALIZE),
  })
  .passthrough()
  .default(RAW_MIX_DEFAULT);

const RawFinalizeConfigSchema = z
  .object({
    ambient_layers: RawAmbientLayersConfigSchema,
    bitrate: z.string().optional(),
    codec: z.string().default(DEFAULT_CODEC),
    loudnorm: RawLoudnormConfigSchema,
    mix: RawMixConfigSchema,
    sample_rate: z.coerce.number().finite().optional(),
  })
  .passthrough()
  .default(RAW_FINALIZE_DEFAULT);

const RawLegacyRainLayerConfigSchema = RawAmbientLayersConfigSchema.and(
  z
    .object({
      loudnorm: RawLoudnormConfigSchema.optional(),
    })
    .passthrough()
);

export const RawFinalizeMasterConfigSchema = z
  .object({
    audio: z
      .object({
        bitrate: z.string().default(DEFAULT_BITRATE),
        finalize: RawFinalizeConfigSchema,
      })
      .passthrough()
      .default({
        bitrate: DEFAULT_BITRATE,
        finalize: RAW_FINALIZE_DEFAULT,
      }),
    rain_layer: RawLegacyRainLayerConfigSchema.optional(),
  })
  .passthrough()
  .default({
    audio: {
      bitrate: DEFAULT_BITRATE,
      finalize: RAW_FINALIZE_DEFAULT,
    },
  });

export const FinalizeMasterInputSchema = z
  .object({
    collectionDir: z.string(),
  })
  .strict();

export const FinalizeMasterOutputSchema = z
  .object({
    layersApplied: z.number().int().nonnegative(),
    loudnormApplied: z.boolean(),
    masterPath: z.string(),
    passThrough: z.boolean(),
    warnings: z.array(z.string()),
  })
  .strict();

const LoudnormConfigSchema = z
  .object({
    I: z.number(),
    LRA: z.number(),
    TP: z.number(),
    enabled: z.boolean(),
    mode: z.literal("linear"),
  })
  .strict();

const LayerOverrideSchema = z
  .object({
    fadeinCurve: z.string().optional(),
    fadeinS: z.number().optional(),
    volumeDb: z.number().optional(),
  })
  .strict();

const FinalizeMasterConfigSchema = z
  .object({
    ambientLayers: z
      .object({
        dirname: z.string(),
        fadeinCurve: z.string(),
        fadeinS: z.number(),
        glob: z.string(),
        layers: z.record(z.string(), LayerOverrideSchema),
        volumeDb: z.number(),
      })
      .strict(),
    loudnorm: LoudnormConfigSchema,
    mix: z
      .object({
        duration: z.enum(["first", "shortest", "longest"]),
        normalize: z.union([z.literal(0), z.literal(1)]),
      })
      .strict(),
    output: z
      .object({
        bitrate: z.string(),
        codec: z.string(),
        sampleRate: z.number().int().positive().nullable(),
      })
      .strict(),
  })
  .strict();

export const FinalizeMasterConfigResultSchema = z
  .object({
    config: FinalizeMasterConfigSchema,
    warnings: z.array(z.string()),
  })
  .strict();

export type FinalizeMasterInput = z.infer<typeof FinalizeMasterInputSchema>;
export type FinalizeMasterOutput = z.infer<typeof FinalizeMasterOutputSchema>;
export type FinalizeMasterConfig = z.infer<typeof FinalizeMasterConfigSchema>;
export type FinalizeMasterConfigResult = z.infer<
  typeof FinalizeMasterConfigResultSchema
>;
export type LayerOverride = z.infer<typeof LayerOverrideSchema>;
export type LoudnormConfig = z.infer<typeof LoudnormConfigSchema>;
export type RawAmbientLayersConfig = z.infer<
  typeof RawAmbientLayersConfigSchema
>;
export type RawFinalizeConfig = z.infer<typeof RawFinalizeConfigSchema>;
export type RawFinalizeMasterConfig = z.infer<
  typeof RawFinalizeMasterConfigSchema
>;
export type RawLoudnormConfig = z.infer<typeof RawLoudnormConfigSchema>;
