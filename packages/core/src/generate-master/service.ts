import { existsSync } from "node:fs";
import { copyFile, mkdir } from "node:fs/promises";
import { extname, isAbsolute, join, resolve } from "node:path";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { CollectionPaths, resolveCollectionDir } from "../paths.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import {
  collectAudioInputs,
  orderInputs,
  resolveLoopCount,
  withConfigOverrides,
} from "./audio.ts";
import { readMasterupAudioConfig } from "./config.ts";
import { MASTER_DIRNAME, MASTER_FILENAME } from "./constants.ts";
import { buildFfmpegArgs, runFfmpeg } from "./ffmpeg.ts";
import { GenerateMasterOutputSchema } from "./schema.ts";
import type { GenerateMasterInput, GenerateMasterOutput } from "./schema.ts";

interface GenerateMasterDeps {
  channelDir: string;
}

const resolveCollectionPath = (
  input: GenerateMasterInput,
  deps: Partial<GenerateMasterDeps> | undefined
): string => {
  if (input.collection === undefined) {
    return resolveCollectionDir(null);
  }
  if (isAbsolute(input.collection)) {
    return resolve(input.collection);
  }
  const channelDir = input.channelDir ?? deps?.channelDir;
  if (channelDir === undefined || channelDir.length === 0) {
    throw new Error(
      "validation: relative collection requires channel_dir or CHANNEL_DIR"
    );
  }
  return resolve(channelDir, input.collection);
};

const resolveConfigChannelDir = (
  input: GenerateMasterInput,
  deps: Partial<GenerateMasterDeps> | undefined
): string | undefined => {
  const channelDir = input.channelDir ?? deps?.channelDir;
  return channelDir === undefined || channelDir.length === 0
    ? undefined
    : channelDir;
};

export const generateMasterService = async (
  input: GenerateMasterInput,
  deps?: Partial<GenerateMasterDeps>
): Promise<Result<GenerateMasterOutput, ServiceError>> => {
  try {
    const collectionDir = resolveCollectionPath(input, deps);
    const config = await readMasterupAudioConfig(
      resolveConfigChannelDir(input, deps)
    );
    const effectiveInput = withConfigOverrides(input, config);
    const paths = new CollectionPaths(collectionDir);
    const files = await collectAudioInputs(paths.musicDir);
    const ordered = orderInputs(files, effectiveInput);
    const loopCount = await resolveLoopCount(ordered.ordered, effectiveInput);
    const segments = Array.from(
      { length: loopCount },
      () => ordered.ordered
    ).flat();

    await mkdir(join(collectionDir, MASTER_DIRNAME), { recursive: true });
    const outputPath = join(paths.masterDir, MASTER_FILENAME);
    const [onlySegment] = segments;
    const shouldCopySingleMp3 =
      segments.length === 1 &&
      onlySegment !== undefined &&
      extname(onlySegment).toLowerCase() === ".mp3";
    await (shouldCopySingleMp3
      ? copyFile(onlySegment, outputPath)
      : runFfmpeg(buildFfmpegArgs(segments, outputPath, effectiveInput)));

    const output = GenerateMasterOutputSchema.parse({
      bitrate: effectiveInput.bitrate,
      crossfadeDuration: effectiveInput.crossfadeDuration,
      inputCount: files.length,
      loopCount,
      messages: ordered.messages,
      outputPath,
      segmentCount: segments.length,
    });
    if (!existsSync(output.outputPath)) {
      throw new Error(
        `io: master output was not created: ${output.outputPath}`
      );
    }
    return ok(output);
  } catch (error) {
    return err(toServiceError(error));
  }
};
