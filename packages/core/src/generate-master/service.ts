import { copyFile, mkdir, readFile, realpath } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

import { parse as parseYaml } from "yaml";

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

const readMasterupConfig = async (
  channelDir: string
): Promise<MasterupConfig> => {
  try {
    const text = await readFile(join(channelDir, MASTER_CONFIG_RELATIVE_PATH), {
      encoding: "utf-8",
    });
    const parsed = parseYaml(text);
    return MasterupConfigSchema.parse(parsed ?? {});
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return MasterupConfigSchema.parse({});
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
        segmentCount: expanded.length,
        shuffleSeed,
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
