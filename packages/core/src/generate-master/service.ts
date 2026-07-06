import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { copyFile, lstat, mkdir, rename, rm } from "node:fs/promises";
import { extname, isAbsolute, join, resolve } from "node:path";
import process from "node:process";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { CollectionPaths, resolveCollectionDir } from "../paths.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import {
  collectAudioInputs,
  orderInputs,
  resolveLoopPlan,
  withConfigOverrides,
} from "./audio.ts";
import { readMasterupAudioConfig } from "./config.ts";
import { MASTER_DIRNAME, MASTER_FILENAME } from "./constants.ts";
import { buildFfmpegArgs, runFfmpeg } from "./ffmpeg.ts";
import {
  resolveCollectionPathForChannel,
  tryFindChannelRootForCollection,
} from "./paths.ts";
import {
  GenerateMasterOutputSchema,
  ParseableGenerateMasterInputSchema,
} from "./schema.ts";
import type {
  GenerateMasterInternalInput,
  GenerateMasterOutput,
} from "./schema.ts";

interface GenerateMasterDeps {
  channelDir: string;
}

const parseGenerateMasterInput = (
  input: unknown
): GenerateMasterInternalInput =>
  ParseableGenerateMasterInputSchema.parse(input);

const resolveCollectionPath = (
  input: GenerateMasterInternalInput,
  deps: Partial<GenerateMasterDeps> | undefined
): string => {
  if (input.collection === undefined) {
    return resolveCollectionDir(null);
  }
  const channelDir = input.channelDir ?? deps?.channelDir;
  if (isAbsolute(input.collection)) {
    return channelDir === undefined || channelDir.length === 0
      ? resolve(input.collection)
      : resolveCollectionPathForChannel(channelDir, input.collection);
  }
  if (channelDir === undefined || channelDir.length === 0) {
    throw new Error(
      "validation: relative collection requires channel_dir or CHANNEL_DIR"
    );
  }
  return resolveCollectionPathForChannel(channelDir, input.collection);
};

const resolveConfigChannelDir = (
  input: GenerateMasterInternalInput,
  deps: Partial<GenerateMasterDeps> | undefined
): string | undefined => {
  const channelDir = input.channelDir ?? deps?.channelDir;
  if (channelDir !== undefined && channelDir.length > 0) {
    return channelDir;
  }
  return input.collection !== undefined && isAbsolute(input.collection)
    ? tryFindChannelRootForCollection(input.collection)
    : undefined;
};

const assertMasterOutputPathSafe = async (
  masterDir: string,
  outputPath: string
): Promise<void> => {
  const masterStats = await lstat(masterDir);
  if (!masterStats.isDirectory() || masterStats.isSymbolicLink()) {
    throw new Error(`validation: unsafe master directory: ${masterDir}`);
  }
  try {
    const outputStats = await lstat(outputPath);
    if (outputStats.isSymbolicLink()) {
      throw new Error(`validation: unsafe symlink output path: ${outputPath}`);
    }
  } catch (error) {
    if (
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return;
    }
    throw error;
  }
};

const tempMasterPath = (outputPath: string): string =>
  `${outputPath}.tmp-${process.pid}-${randomUUID()}`;

const runGenerateMaster = async (
  input: GenerateMasterInternalInput,
  deps?: Partial<GenerateMasterDeps>
): Promise<GenerateMasterOutput> => {
  const collectionDir = resolveCollectionPath(input, deps);
  const config = await readMasterupAudioConfig(
    resolveConfigChannelDir(input, deps)
  );
  const effectiveInput = withConfigOverrides(input, config);
  const paths = new CollectionPaths(collectionDir);
  const files = await collectAudioInputs(paths.musicDir);
  const ordered = orderInputs(files, effectiveInput);
  const { durationPreview, loopCount } = await resolveLoopPlan(
    ordered.ordered,
    effectiveInput
  );
  const segments = Array.from(
    { length: loopCount },
    () => ordered.ordered
  ).flat();

  await mkdir(join(collectionDir, MASTER_DIRNAME), { recursive: true });
  const outputPath = join(paths.masterDir, MASTER_FILENAME);
  await assertMasterOutputPathSafe(paths.masterDir, outputPath);
  const tempPath = tempMasterPath(outputPath);
  const [onlySegment] = segments;
  const shouldCopySingleMp3 =
    segments.length === 1 &&
    onlySegment !== undefined &&
    extname(onlySegment).toLowerCase() === ".mp3";
  try {
    await (shouldCopySingleMp3
      ? copyFile(onlySegment, tempPath)
      : runFfmpeg(buildFfmpegArgs(segments, tempPath, effectiveInput)));
    if (!existsSync(tempPath)) {
      throw new Error(`io: master output was not created: ${outputPath}`);
    }
    await rename(tempPath, outputPath);
  } catch (error) {
    await rm(tempPath, { force: true });
    throw error;
  }

  return GenerateMasterOutputSchema.parse({
    bitrate: effectiveInput.bitrate,
    crossfadeDuration: effectiveInput.crossfadeDuration,
    durationPreview,
    inputCount: files.length,
    loopCount,
    messages: ordered.messages,
    outputPath,
    segmentCount: segments.length,
  });
};

export const generateMasterService = async (
  rawInput: unknown,
  deps?: Partial<GenerateMasterDeps>
): Promise<Result<GenerateMasterOutput, ServiceError>> => {
  try {
    const input = parseGenerateMasterInput(rawInput);
    return ok(await runGenerateMaster(input, deps));
  } catch (error) {
    return err(toServiceError(error));
  }
};
