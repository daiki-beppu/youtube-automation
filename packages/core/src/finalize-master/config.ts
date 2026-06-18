import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { isRecord } from "../../internal/guards.ts";
import {
  FinalizeMasterConfigResultSchema,
  MASTERUP_CONFIG_FILENAME,
  RawFinalizeMasterConfigSchema,
} from "./schema.ts";
import type {
  FinalizeMasterConfig,
  FinalizeMasterConfigResult,
  LayerOverride,
  RawAmbientLayersConfig,
  RawFinalizeConfig,
  RawFinalizeMasterConfig,
  RawLoudnormConfig,
} from "./schema.ts";

const LEGACY_WARNING =
  "config: `rain_layer` is deprecated; use `audio.finalize.ambient_layers` and `audio.finalize.loudnorm`.";

const CONFIG_RELATIVE_PATH = join("config", "skills", MASTERUP_CONFIG_FILENAME);

const resolveLayerOverrides = (
  value: RawAmbientLayersConfig["layers"]
): Record<string, LayerOverride> =>
  Object.fromEntries(
    Object.entries(value).map(([filename, override]) => [
      filename,
      {
        fadeinCurve: override.fadein_curve,
        fadeinS: override.fadein_s,
        volumeDb: override.volume_db,
      },
    ])
  );

const resolveMixNormalize = (
  value: RawFinalizeConfig["mix"]["normalize"]
): 0 | 1 => {
  const normalized = typeof value === "boolean" ? Number(value) : value;
  if (normalized !== 0 && normalized !== 1) {
    throw new Error(
      "config: audio.finalize.mix.normalize must be 0, 1, true, or false"
    );
  }
  return normalized;
};

const resolveMixDuration = (
  value: RawFinalizeConfig["mix"]["duration"]
): "first" | "shortest" | "longest" => {
  const duration = value;
  if (
    duration !== "first" &&
    duration !== "shortest" &&
    duration !== "longest"
  ) {
    throw new Error(
      "config: audio.finalize.mix.duration must be first, shortest, or longest"
    );
  }
  return duration;
};

const resolveLoudnormMode = (value: RawLoudnormConfig["mode"]): "linear" => {
  const mode = value;
  if (mode === "dynamic") {
    throw new Error(
      "config: audio.finalize.loudnorm.mode dynamic is not implemented"
    );
  }
  if (mode !== "linear") {
    throw new Error("config: audio.finalize.loudnorm.mode must be linear");
  }
  return mode;
};

const optionalSourceRecord = (value: unknown): Record<string, unknown> =>
  isRecord(value) ? value : {};

const useLegacyAlias = (
  legacy: Record<string, unknown>,
  finalize: Record<string, unknown>
): boolean =>
  Object.keys(legacy).length > 0 && Object.keys(finalize).length === 0;

const parseRawConfig = (rawConfig: unknown): RawFinalizeMasterConfig => {
  const result = RawFinalizeMasterConfigSchema.safeParse(rawConfig);
  if (result.success) {
    return result.data;
  }
  const [issue] = result.error.issues;
  const path =
    issue === undefined || issue.path.length === 0
      ? "config"
      : issue.path.join(".");
  throw new TypeError(`config: ${path} ${issue?.message ?? "is invalid"}`);
};

const selectedAmbientLayers = (
  parsed: RawFinalizeMasterConfig,
  useLegacy: boolean
): RawAmbientLayersConfig =>
  useLegacy && parsed.rain_layer !== undefined
    ? parsed.rain_layer
    : parsed.audio.finalize.ambient_layers;

const selectedLoudnorm = (
  parsed: RawFinalizeMasterConfig,
  useLegacy: boolean
): RawLoudnormConfig =>
  useLegacy && parsed.rain_layer?.loudnorm !== undefined
    ? parsed.rain_layer.loudnorm
    : parsed.audio.finalize.loudnorm;

export const resolveFinalizeConfig = (
  rawConfig: unknown
): FinalizeMasterConfigResult => {
  const root = optionalSourceRecord(rawConfig);
  const rawAudio = optionalSourceRecord(root.audio);
  const rawFinalize = optionalSourceRecord(rawAudio.finalize);
  const rawLegacy = optionalSourceRecord(root.rain_layer);
  const parsed = parseRawConfig(rawConfig);
  const useLegacy = useLegacyAlias(rawLegacy, rawFinalize);
  const warnings = useLegacy ? [LEGACY_WARNING] : [];

  const { audio } = parsed;
  const { finalize } = audio;
  const ambient = selectedAmbientLayers(parsed, useLegacy);
  const loudnorm = selectedLoudnorm(parsed, useLegacy);
  const config: FinalizeMasterConfig = {
    ambientLayers: {
      dirname: ambient.dirname,
      fadeinCurve: ambient.fadein_curve,
      fadeinS: ambient.fadein_s,
      glob: ambient.glob,
      layers: resolveLayerOverrides(ambient.layers),
      volumeDb: ambient.volume_db,
    },
    loudnorm: {
      I: loudnorm.I,
      LRA: loudnorm.LRA,
      TP: loudnorm.TP,
      enabled: loudnorm.enabled,
      mode: resolveLoudnormMode(loudnorm.mode),
    },
    mix: {
      duration: resolveMixDuration(finalize.mix.duration),
      normalize: resolveMixNormalize(finalize.mix.normalize),
    },
    output: {
      bitrate: finalize.bitrate ?? audio.bitrate,
      codec: finalize.codec,
      sampleRate:
        finalize.sample_rate === undefined
          ? null
          : Math.trunc(finalize.sample_rate),
    },
  };

  return FinalizeMasterConfigResultSchema.parse({ config, warnings });
};

export const readFinalizeConfig = async (
  channelDir: string
): Promise<FinalizeMasterConfigResult> => {
  const path = join(channelDir, CONFIG_RELATIVE_PATH);
  let text: string;
  try {
    text = await readFile(path, "utf-8");
  } catch (error) {
    if (isRecord(error) && error.code === "ENOENT") {
      return resolveFinalizeConfig({});
    }
    throw error;
  }

  try {
    return resolveFinalizeConfig(JSON.parse(text));
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new TypeError(`config: ${path} is not valid JSON`, {
        cause: error,
      });
    }
    throw error;
  }
};
