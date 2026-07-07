import { lstat, readdir, realpath } from "node:fs/promises";
import { basename, extname, isAbsolute, join, relative } from "node:path";

import type { MasterupAudioConfig } from "./config.ts";
import { MUSIC_DIRNAME, SUPPORTED_AUDIO_EXTENSIONS } from "./constants.ts";
import { probeDuration, seededRandom } from "./ffmpeg.ts";
import type { GenerateMasterInternalInput } from "./schema.ts";

export type EffectiveGenerateMasterInput = GenerateMasterInternalInput & {
  bitrate: string;
  crossfadeDuration: number;
  pinFirst: string[];
  shuffle: boolean;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isNodeErrorCode = (error: unknown, code: string): boolean =>
  isRecord(error) && error.code === code;

const assertSafeAudioDirectory = async (path: string): Promise<void> => {
  try {
    const stats = await lstat(path);
    if (!stats.isDirectory() || stats.isSymbolicLink()) {
      throw new Error(`validation: unsafe audio directory: ${path}`);
    }
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) {
      throw new Error(`validation: directory not found: ${path}`, {
        cause: error,
      });
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
  input: GenerateMasterInternalInput,
  config: MasterupAudioConfig
): EffectiveGenerateMasterInput => {
  const { shuffleSeed: inputShuffleSeed } = input;
  const { shuffleSeed: configShuffleSeed } = config;
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
  const useConfigShuffleSeed =
    !input.specified.shuffle &&
    !input.specified.shuffleSeed &&
    config.shuffle === true;
  let shuffleSeed: number | undefined;
  if (input.specified.shuffleSeed) {
    shuffleSeed = inputShuffleSeed;
  } else if (useConfigShuffleSeed) {
    shuffleSeed = configShuffleSeed;
  }
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
  await assertSafeAudioDirectory(musicDir);
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

interface DurationPreview {
  estimatedSeconds: number;
  targetSeconds?: number;
  trackTotalSeconds: number;
}

export interface LoopPlan {
  durationPreview?: DurationPreview;
  loopCount: number;
}

const estimateLoopedDuration = (
  trackTotalSeconds: number,
  fileCount: number,
  loopCount: number,
  crossfadeDuration: number
): number => {
  const segmentCount = loopCount * fileCount;
  const crossfadeCount = Math.max(0, segmentCount - 1);
  return Math.max(
    0,
    trackTotalSeconds * loopCount - crossfadeCount * crossfadeDuration
  );
};

const resolveTargetLoopCount = (
  trackTotalSeconds: number,
  fileCount: number,
  targetSeconds: number,
  crossfadeDuration: number
): number => {
  const perLoopNetSeconds = trackTotalSeconds - fileCount * crossfadeDuration;
  if (perLoopNetSeconds <= 0) {
    return 1;
  }
  return Math.max(
    1,
    Math.ceil((targetSeconds - crossfadeDuration) / perLoopNetSeconds)
  );
};

const sumDurations = async (files: string[]): Promise<number> => {
  const durations = await Promise.all(files.map((file) => probeDuration(file)));
  return durations.reduce((total, value) => total + value, 0);
};

export const resolveLoopPlan = async (
  files: string[],
  input: EffectiveGenerateMasterInput
): Promise<LoopPlan> => {
  if (input.noLoop) {
    const trackTotalSeconds = await sumDurations(files);
    const targetSeconds =
      input.targetDurationMin === undefined
        ? undefined
        : input.targetDurationMin * 60;
    return {
      durationPreview: {
        estimatedSeconds: estimateLoopedDuration(
          trackTotalSeconds,
          files.length,
          1,
          input.crossfadeDuration
        ),
        targetSeconds,
        trackTotalSeconds,
      },
      loopCount: 1,
    };
  }
  if (input.loop !== undefined) {
    const trackTotalSeconds = await sumDurations(files);
    return {
      durationPreview: {
        estimatedSeconds: estimateLoopedDuration(
          trackTotalSeconds,
          files.length,
          input.loop,
          input.crossfadeDuration
        ),
        trackTotalSeconds,
      },
      loopCount: input.loop,
    };
  }
  if (input.targetDurationMin === undefined) {
    return { loopCount: 1 };
  }
  const trackTotalSeconds = await sumDurations(files);
  const targetSeconds = input.targetDurationMin * 60;
  const loopCount = resolveTargetLoopCount(
    trackTotalSeconds,
    files.length,
    targetSeconds,
    input.crossfadeDuration
  );
  return {
    durationPreview: {
      estimatedSeconds: estimateLoopedDuration(
        trackTotalSeconds,
        files.length,
        loopCount,
        input.crossfadeDuration
      ),
      targetSeconds,
      trackTotalSeconds,
    },
    loopCount,
  };
};
