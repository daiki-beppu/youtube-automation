import { lstat, readdir, realpath, stat } from "node:fs/promises";
import { basename, extname, isAbsolute, join, relative } from "node:path";

import type { MasterupAudioConfig } from "./config.ts";
import { MUSIC_DIRNAME, SUPPORTED_AUDIO_EXTENSIONS } from "./constants.ts";
import { probeDuration, seededRandom } from "./ffmpeg.ts";
import type { GenerateMasterInput } from "./schema.ts";

export type EffectiveGenerateMasterInput = GenerateMasterInput & {
  bitrate: string;
  crossfadeDuration: number;
  pinFirst: string[];
  shuffle: boolean;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isNodeErrorCode = (error: unknown, code: string): boolean =>
  isRecord(error) && error.code === code;

const isDirectory = async (path: string): Promise<boolean> => {
  try {
    const stats = await stat(path);
    return stats.isDirectory();
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) {
      return false;
    }
    throw error;
  }
};

const isInside = (root: string, path: string): boolean => {
  const rel = relative(root, path);
  return rel.length > 0 && !rel.startsWith("..") && !isAbsolute(rel);
};

const assertSafeAudioFile = async (
  musicDirRealPath: string,
  path: string
): Promise<string> => {
  const stats = await lstat(path);
  if (!stats.isFile() || stats.isSymbolicLink()) {
    throw new Error(`validation: unsafe audio input: ${path}`);
  }
  const real = await realpath(path);
  if (!isInside(musicDirRealPath, real)) {
    throw new Error(
      `validation: audio input escapes ${MUSIC_DIRNAME}: ${path}`
    );
  }
  return path;
};

export const withConfigOverrides = (
  input: GenerateMasterInput,
  config: MasterupAudioConfig
): EffectiveGenerateMasterInput => {
  const bitrate =
    !input.specified.bitrate && config.bitrate !== undefined
      ? config.bitrate
      : input.bitrate;
  const crossfadeDuration =
    !input.specified.crossfadeDuration && config.crossfadeDuration !== undefined
      ? config.crossfadeDuration
      : input.crossfadeDuration;
  const targetDurationMin =
    input.loop === undefined &&
    !input.noLoop &&
    !input.specified.targetDurationMin
      ? config.targetDurationMin
      : input.targetDurationMin;
  const shuffle =
    input.specified.shuffle || input.specified.shuffleSeed
      ? input.shuffle || input.shuffleSeed !== undefined
      : config.shuffle === true;
  const shuffleSeed = input.specified.shuffleSeed
    ? input.shuffleSeed
    : config.shuffleSeed;
  const pinFirstCount =
    input.pinFirst.length === 0 && !input.specified.pinFirstCount
      ? config.pinFirstCount
      : input.pinFirstCount;
  return {
    ...input,
    bitrate,
    crossfadeDuration,
    pinFirstCount,
    shuffle,
    shuffleSeed,
    targetDurationMin,
  };
};

export const collectAudioInputs = async (
  musicDir: string
): Promise<string[]> => {
  if (!(await isDirectory(musicDir))) {
    throw new Error(`validation: directory not found: ${musicDir}`);
  }
  const names = await readdir(musicDir);
  const musicDirRealPath = await realpath(musicDir);
  const candidates = names
    .filter((name) =>
      SUPPORTED_AUDIO_EXTENSIONS.includes(
        extname(
          name
        ).toLowerCase() as (typeof SUPPORTED_AUDIO_EXTENSIONS)[number]
      )
    )
    .toSorted()
    .map((name) => join(musicDir, name));
  const files = await Promise.all(
    candidates.map((path) => assertSafeAudioFile(musicDirRealPath, path))
  );
  if (files.length === 0) {
    throw new Error(
      `validation: audio files not found in ${MUSIC_DIRNAME}: ${musicDir}`
    );
  }
  return files;
};

const applyPinFirst = (
  files: string[],
  pinFirst: string[],
  pinFirstCount: number | undefined
): { messages: string[]; ordered: string[] } => {
  if (pinFirst.length > 0) {
    const byName = new Map(files.map((file) => [basename(file), file]));
    const pinned = pinFirst.map((name) => {
      const file = byName.get(name);
      if (file === undefined) {
        throw new Error(`validation: pin-first file not found: ${name}`);
      }
      return file;
    });
    const pinnedNames = new Set(pinFirst);
    const remaining = files.filter((file) => !pinnedNames.has(basename(file)));
    return {
      messages: [
        `[Pin] first ${pinned.length} track(s) fixed: ${JSON.stringify(
          pinned.map((file) => basename(file))
        )}`,
      ],
      ordered: [...pinned, ...remaining],
    };
  }
  if (pinFirstCount !== undefined && pinFirstCount > 0) {
    if (pinFirstCount > files.length) {
      throw new Error(
        `validation: pin_first_count=${pinFirstCount} exceeds track count ${files.length}`
      );
    }
    const pinned = files.slice(0, pinFirstCount);
    return {
      messages: [
        `[Pin] first ${pinFirstCount} track(s) fixed: ${JSON.stringify(
          pinned.map((file) => basename(file))
        )}`,
      ],
      ordered: files,
    };
  }
  return { messages: [], ordered: files };
};

const shuffleFiles = (
  files: string[],
  seed: number | undefined
): { messages: string[]; ordered: string[] } => {
  const seedSource =
    seed === undefined
      ? crypto.getRandomValues(new Uint32Array(1))[0]
      : Math.trunc(seed);
  if (seedSource === undefined) {
    throw new Error("validation: failed to create shuffle seed");
  }
  const random = seededRandom(seedSource);
  const ordered = [...files];
  for (let index = ordered.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1));
    const current = ordered[index];
    const replacement = ordered[swapIndex];
    if (current !== undefined && replacement !== undefined) {
      ordered[index] = replacement;
      ordered[swapIndex] = current;
    }
  }
  return { messages: [`[Shuffle] seed=${seedSource}`], ordered };
};

export const orderInputs = (
  files: string[],
  input: EffectiveGenerateMasterInput
): { messages: string[]; ordered: string[] } => {
  const pinned = applyPinFirst(files, input.pinFirst, input.pinFirstCount);
  if (!input.shuffle) {
    return pinned;
  }
  const pinnedCount =
    input.pinFirst.length > 0
      ? input.pinFirst.length
      : (input.pinFirstCount ?? 0);
  const fixed = pinned.ordered.slice(0, pinnedCount);
  const shuffled = shuffleFiles(
    pinned.ordered.slice(pinnedCount),
    input.shuffleSeed
  );
  return {
    messages: [...shuffled.messages, ...pinned.messages],
    ordered: [...fixed, ...shuffled.ordered],
  };
};

export const resolveLoopCount = async (
  files: string[],
  input: EffectiveGenerateMasterInput
): Promise<number> => {
  if (input.noLoop) {
    return 1;
  }
  if (input.loop !== undefined) {
    return input.loop;
  }
  if (input.targetDurationMin === undefined) {
    return 1;
  }
  const durations = await Promise.all(files.map((file) => probeDuration(file)));
  const singleLoopSeconds = durations.reduce(
    (total, value) => total + value,
    0
  );
  const targetSeconds = input.targetDurationMin * 60;
  const span = Math.max(singleLoopSeconds - input.crossfadeDuration, 0.000_001);
  return Math.max(
    1,
    Math.ceil((targetSeconds - input.crossfadeDuration) / span)
  );
};
