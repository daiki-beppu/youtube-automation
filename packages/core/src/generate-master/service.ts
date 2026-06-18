import { copyFile, mkdir, readFile, realpath } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import { masterOutputPath, resolveLoopCount, runFfmpeg } from "./ffmpeg.ts";
import {
  applyPinFirst,
  collectAudioInputs,
  resolveShuffleSeed,
  shuffleTracks,
} from "./inputs.ts";
import {
  GenerateMasterInputSchema,
  GenerateMasterOutputSchema,
  MASTER_CONFIG_RELATIVE_PATH,
  MASTER_OUTPUT_DIR,
  MAX_MASTER_SEGMENT_COUNT,
  MasterupConfigSchema,
} from "./schema.ts";
import type {
  GenerateMasterInput,
  GenerateMasterOutput,
  MasterupConfig,
} from "./schema.ts";
import type { ResolvedMasteringOptions } from "./types.ts";

const DEFAULT_CROSSFADE_SECONDS = 1;
const DEFAULT_BITRATE = "192k";
const MASTER_DEFAULT_CONFIG_PATH = join(
  import.meta.dirname,
  "..",
  "..",
  "..",
  "cli",
  "_skills",
  "masterup",
  "config.default.json"
);

const deepMerge = (
  base: Record<string, unknown>,
  override: Record<string, unknown>
): Record<string, unknown> => {
  const merged = { ...base };
  for (const [key, value] of Object.entries(override)) {
    const baseValue = merged[key];
    merged[key] =
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      baseValue !== null &&
      typeof baseValue === "object" &&
      !Array.isArray(baseValue)
        ? deepMerge(
            baseValue as Record<string, unknown>,
            value as Record<string, unknown>
          )
        : value;
  }
  return merged;
};

const readJsonObject = async (
  path: string
): Promise<Record<string, unknown>> => {
  const text = await readFile(path, { encoding: "utf-8" });
  const parsed = JSON.parse(text) as unknown;
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`config: masterup config root must be an object: ${path}`);
  }
  return parsed as Record<string, unknown>;
};

const readMasterupConfig = async (
  channelDir: string
): Promise<MasterupConfig> => {
  const defaults = await readJsonObject(MASTER_DEFAULT_CONFIG_PATH);
  try {
    const override = await readJsonObject(
      join(channelDir, MASTER_CONFIG_RELATIVE_PATH)
    );
    return MasterupConfigSchema.parse(deepMerge(defaults, override));
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return MasterupConfigSchema.parse(defaults);
    }
    throw error;
  }
};

const resolveCollectionDir = async (
  channelDir: string,
  collection: string
): Promise<string> => {
  const path = isAbsolute(collection)
    ? collection
    : join(channelDir, collection);
  return await realpath(path);
};

const resolveTargetDuration = (
  request: GenerateMasterInput,
  config: MasterupConfig
): number | undefined => {
  if (request.loop !== undefined || request.targetDuration !== undefined) {
    return request.targetDuration;
  }
  return config.audio?.target_duration_min;
};

const resolveShuffle = (
  request: GenerateMasterInput,
  config: MasterupConfig
): { readonly shuffle: boolean; readonly shuffleSeed?: number } => {
  const cliShuffleSpecified =
    request.shuffle === true || request.shuffleSeed !== undefined;
  return {
    shuffle: cliShuffleSpecified || config.audio?.shuffle === true,
    shuffleSeed: request.shuffleSeed ?? config.audio?.shuffle_seed,
  };
};

const resolvePinFirstCount = (
  request: GenerateMasterInput,
  config: MasterupConfig
): number | undefined => {
  if (request.pinFirst !== undefined || request.pinFirstCount !== undefined) {
    return request.pinFirstCount;
  }
  const configured = config.audio?.pin_first_count;
  return configured !== undefined && configured > 0 ? configured : undefined;
};

const resolveOptions = async (
  input: GenerateMasterInput,
  deps: { channelDir: string }
): Promise<ResolvedMasteringOptions> => {
  const request = GenerateMasterInputSchema.parse(input);
  const channelDir = await realpath(deps.channelDir);
  const config = await readMasterupConfig(channelDir);
  const { audio } = config;
  const shuffle = resolveShuffle(request, config);
  return {
    bitrate: audio?.bitrate ?? DEFAULT_BITRATE,
    collectionDir: await resolveCollectionDir(channelDir, request.collection),
    crossfadeSeconds: audio?.crossfade_duration ?? DEFAULT_CROSSFADE_SECONDS,
    loop: request.loop,
    pinFirst: request.pinFirst,
    pinFirstCount: resolvePinFirstCount(request, config),
    shuffle: shuffle.shuffle,
    shuffleSeed: shuffle.shuffleSeed,
    targetDuration: resolveTargetDuration(request, config),
  };
};

export const generateMasterService = async (
  input: GenerateMasterInput,
  deps: { channelDir: string }
): Promise<Result<GenerateMasterOutput, ServiceError>> => {
  try {
    const options = await resolveOptions(input, deps);
    const tracks = await collectAudioInputs(options.collectionDir);
    const shuffleSeed = resolveShuffleSeed(options);
    const resolvedOptions = { ...options, shuffleSeed };
    const pinned = applyPinFirst(tracks.files, resolvedOptions);
    const ordered = shuffleTracks(pinned, resolvedOptions);
    const loops = await resolveLoopCount(ordered, resolvedOptions);
    const segmentCount = loops * ordered.length;
    if (segmentCount > MAX_MASTER_SEGMENT_COUNT) {
      throw new Error(
        `validation: generated segment count ${segmentCount} exceeds max ${MAX_MASTER_SEGMENT_COUNT}`
      );
    }
    const expanded = Array.from({ length: loops }, () => ordered).flat();
    const outputPath = masterOutputPath(options.collectionDir, tracks.audioExt);
    await mkdir(join(options.collectionDir, MASTER_OUTPUT_DIR), {
      recursive: true,
    });

    const copied = expanded.length === 1;
    if (copied) {
      const [sourcePath] = expanded;
      if (sourcePath === undefined) {
        throw new Error("validation: no audio segments selected");
      }
      await copyFile(sourcePath, outputPath);
    } else {
      await runFfmpeg(expanded, outputPath, {
        audioExt: tracks.audioExt,
        bitrate: options.bitrate,
        crossfadeSeconds: options.crossfadeSeconds,
      });
    }

    return ok(
      GenerateMasterOutputSchema.parse({
        audioExt: tracks.audioExt,
        copied,
        inputCount: tracks.files.length,
        loops,
        outputPath,
        segmentCount,
        shuffleSeed,
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
