import { spawn } from "node:child_process";
import { once } from "node:events";
import { constants } from "node:fs";
import { access, readdir, rename, rm, stat } from "node:fs/promises";
import { basename, delimiter, join } from "node:path";
import process from "node:process";
import { text } from "node:stream/consumers";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import { readFinalizeConfig } from "./config.ts";
import { buildFinalizeFilter, parseLoudnormJson } from "./filter.ts";
import {
  BRANDING_DIRNAME,
  DEFAULT_LAYERS_DIRNAME,
  DEFAULT_LAYERS_GLOB,
  FinalizeMasterInputSchema,
  FinalizeMasterOutputSchema,
  MASTER_FILENAME,
  MASTER_TMP_FILENAME,
} from "./schema.ts";
import type {
  FinalizeMasterConfig,
  FinalizeMasterInput,
  FinalizeMasterOutput,
  LayerOverride,
} from "./schema.ts";

export interface FinalizeMasterDeps {
  readonly channelDir: string;
}

interface ProcessResult {
  readonly code: number | null;
  readonly stderr: string;
}

const globToRegExp = (pattern: string): RegExp => {
  const escaped = pattern.replaceAll(/[.+^${}()|[\]\\]/gu, "\\$&");
  return new RegExp(
    `^${escaped.replaceAll("*", ".*").replaceAll("?", ".")}$`,
    "u"
  );
};

const listAmbientLayers = async (
  channelDir: string,
  dirname: string,
  pattern: string
): Promise<string[]> => {
  const dir = join(channelDir, BRANDING_DIRNAME, dirname);
  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch (error) {
    if (
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return [];
    }
    throw error;
  }
  const matcher = globToRegExp(pattern);
  return entries
    .filter((entry) => matcher.test(entry))
    .map((entry) => join(dir, entry))
    .toSorted();
};

const isPathSearchMiss = (error: unknown): boolean =>
  typeof error === "object" &&
  error !== null &&
  "code" in error &&
  (error.code === "ENOENT" ||
    error.code === "EACCES" ||
    error.code === "ENOTDIR");

const assertFfmpegAvailable = async (): Promise<void> => {
  const paths = process.env.PATH?.split(delimiter) ?? [];
  for (const path of paths) {
    if (path.length === 0) {
      continue;
    }
    try {
      await access(join(path, "ffmpeg"), constants.X_OK);
      return;
    } catch (error) {
      if (isPathSearchMiss(error)) {
        continue;
      }
      throw error;
    }
  }
  throw new Error("ffmpeg not found in PATH");
};

const assertMasterExists = async (masterPath: string): Promise<void> => {
  const info = await stat(masterPath);
  if (!info.isFile()) {
    throw new Error(`${masterPath}: master file not found`);
  }
};

const runFfmpeg = async (args: readonly string[]): Promise<ProcessResult> => {
  const child = spawn("ffmpeg", args, { stdio: ["ignore", "ignore", "pipe"] });
  const stderr = text(child.stderr);
  const close = once(child, "close") as Promise<[number | null]>;
  const error = async (): Promise<never> => {
    const [spawnError] = await once(child, "error");
    throw spawnError;
  };
  const [code] = await Promise.race([close, error()]);
  return { code, stderr: await stderr };
};

const ffmpegInputs = (
  masterPath: string,
  layers: readonly string[]
): string[] => ["-i", masterPath, ...layers.flatMap((layer) => ["-i", layer])];

const outputArgs = (
  config: FinalizeMasterConfig,
  outputPath: string
): string[] => [
  "-c:a",
  config.output.codec,
  "-b:a",
  config.output.bitrate,
  ...(config.output.sampleRate === null
    ? []
    : ["-ar", config.output.sampleRate.toString()]),
  outputPath,
];

const buildPass1Args = (
  masterPath: string,
  layers: readonly string[],
  filter: string
): string[] => [
  "-y",
  ...ffmpegInputs(masterPath, layers),
  "-filter_complex",
  filter,
  "-map",
  "[aout]",
  "-f",
  "null",
  "-",
];

const buildEncodeArgs = (
  masterPath: string,
  layers: readonly string[],
  filter: string,
  outputPath: string,
  config: FinalizeMasterConfig
): string[] => [
  "-y",
  ...ffmpegInputs(masterPath, layers),
  "-filter_complex",
  filter,
  "-map",
  "[aout]",
  ...outputArgs(config, outputPath),
];

const layerOverridesFor = (
  layers: readonly string[],
  overrides: Readonly<Record<string, LayerOverride>>
): (LayerOverride | null)[] =>
  layers.map((layer) => overrides[basename(layer)] ?? null);

const filterOptions = (
  config: FinalizeMasterConfig,
  layers: readonly string[],
  overrides: readonly (LayerOverride | null)[],
  applyLoudnorm: boolean,
  measured: Parameters<typeof buildFinalizeFilter>[0]["measured"]
): Parameters<typeof buildFinalizeFilter>[0] => ({
  applyLoudnorm,
  fadeinCurve: config.ambientLayers.fadeinCurve,
  fadeinS: config.ambientLayers.fadeinS,
  layerCount: layers.length,
  layerOverrides: overrides,
  loudnorm: config.loudnorm,
  measured,
  mixDuration: config.mix.duration,
  mixNormalize: config.mix.normalize,
  volumeDb: config.ambientLayers.volumeDb,
});

const passThroughOutput = (
  masterPath: string,
  warnings: readonly string[]
): FinalizeMasterOutput => ({
  layersApplied: 0,
  loudnormApplied: false,
  masterPath,
  passThrough: true,
  warnings: [...warnings],
});

const executeSinglePass = async (
  masterPath: string,
  tmpPath: string,
  layers: readonly string[],
  config: FinalizeMasterConfig,
  overrides: readonly (LayerOverride | null)[]
): Promise<void> => {
  const filter = buildFinalizeFilter(
    filterOptions(config, layers, overrides, false, null)
  );
  const result = await runFfmpeg(
    buildEncodeArgs(masterPath, layers, filter, tmpPath, config)
  );
  if (result.code !== 0) {
    throw new Error(`ffmpeg single-pass failed with exit code ${result.code}`);
  }
};

const parseMeasurements = (
  measured: Record<string, string>
): Parameters<typeof buildFinalizeFilter>[0]["measured"] => {
  const value = (key: string): string => {
    const parsed = measured[key];
    if (parsed === undefined) {
      throw new Error(`validation: loudnorm JSON is missing ${key}`);
    }
    return parsed;
  };
  return {
    input_i: value("input_i"),
    input_lra: value("input_lra"),
    input_thresh: value("input_thresh"),
    input_tp: value("input_tp"),
    target_offset: value("target_offset"),
  };
};

const executeTwoPass = async (
  masterPath: string,
  tmpPath: string,
  layers: readonly string[],
  config: FinalizeMasterConfig,
  overrides: readonly (LayerOverride | null)[]
): Promise<void> => {
  const pass1Filter = buildFinalizeFilter(
    filterOptions(config, layers, overrides, true, null)
  );
  const pass1 = await runFfmpeg(
    buildPass1Args(masterPath, layers, pass1Filter)
  );
  if (pass1.code !== 0) {
    throw new Error(`ffmpeg pass1 failed with exit code ${pass1.code}`);
  }

  const measured = parseMeasurements(parseLoudnormJson(pass1.stderr));
  const pass2Filter = buildFinalizeFilter(
    filterOptions(config, layers, overrides, true, measured)
  );
  const pass2 = await runFfmpeg(
    buildEncodeArgs(masterPath, layers, pass2Filter, tmpPath, config)
  );
  if (pass2.code !== 0) {
    throw new Error(`ffmpeg pass2 failed with exit code ${pass2.code}`);
  }
};

export const finalizeMasterService = async (
  input: FinalizeMasterInput,
  deps: FinalizeMasterDeps
): Promise<Result<FinalizeMasterOutput, ServiceError>> => {
  try {
    const request = FinalizeMasterInputSchema.parse(input);
    const masterPath = join(
      request.collectionDir,
      "01-master",
      MASTER_FILENAME
    );
    const tmpPath = join(
      request.collectionDir,
      "01-master",
      MASTER_TMP_FILENAME
    );

    const gate1Layers = await listAmbientLayers(
      deps.channelDir,
      DEFAULT_LAYERS_DIRNAME,
      DEFAULT_LAYERS_GLOB
    );
    if (gate1Layers.length === 0) {
      return ok(
        FinalizeMasterOutputSchema.parse(passThroughOutput(masterPath, []))
      );
    }

    const resolved = await readFinalizeConfig(deps.channelDir);
    const layers = await listAmbientLayers(
      deps.channelDir,
      resolved.config.ambientLayers.dirname,
      resolved.config.ambientLayers.glob
    );
    if (layers.length === 0) {
      return ok(
        FinalizeMasterOutputSchema.parse(
          passThroughOutput(masterPath, resolved.warnings)
        )
      );
    }

    await assertFfmpegAvailable();
    await assertMasterExists(masterPath);

    const overrides = layerOverridesFor(
      layers,
      resolved.config.ambientLayers.layers
    );
    try {
      await (resolved.config.loudnorm.enabled
        ? executeTwoPass(
            masterPath,
            tmpPath,
            layers,
            resolved.config,
            overrides
          )
        : executeSinglePass(
            masterPath,
            tmpPath,
            layers,
            resolved.config,
            overrides
          ));
      await rename(tmpPath, masterPath);
    } finally {
      await rm(tmpPath, { force: true });
    }

    return ok(
      FinalizeMasterOutputSchema.parse({
        layersApplied: layers.length,
        loudnormApplied: resolved.config.loudnorm.enabled,
        masterPath,
        passThrough: false,
        warnings: resolved.warnings,
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
