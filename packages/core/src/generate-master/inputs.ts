import { randomInt } from "node:crypto";
import { readdir } from "node:fs/promises";
import { basename, extname, join } from "node:path";

import { MASTER_SOURCE_DIR, SUPPORTED_AUDIO_EXTENSIONS } from "./schema.ts";
import type { SupportedAudioExtension } from "./schema.ts";
import type { AudioTrackSet, ResolvedMasteringOptions } from "./types.ts";

const AUTO_SEED_BOUND = 2 ** 32;

export const collectAudioInputs = async (
  collectionDir: string
): Promise<AudioTrackSet> => {
  const musicDir = join(collectionDir, MASTER_SOURCE_DIR);
  const entries = await readdir(musicDir, { withFileTypes: true });
  const filesByExt = new Map<SupportedAudioExtension, string[]>(
    SUPPORTED_AUDIO_EXTENSIONS.map((ext) => [ext, []])
  );

  for (const entry of entries) {
    if (!entry.isFile()) {
      continue;
    }
    const ext = extname(entry.name).slice(1).toLowerCase();
    if (ext === "mp3" || ext === "wav") {
      filesByExt.set(ext, [
        ...(filesByExt.get(ext) as string[]),
        join(musicDir, entry.name),
      ]);
    }
  }

  const present = [...filesByExt.entries()].filter(
    ([, files]) => files.length > 0
  );
  if (present.length === 0) {
    throw new Error(`validation: no audio files found in ${musicDir}`);
  }
  if (present.length > 1) {
    throw new Error(`validation: mixed audio formats found in ${musicDir}`);
  }

  const [audioExt, files] = present[0] as [SupportedAudioExtension, string[]];
  return { audioExt, files: files.toSorted() };
};

export const applyPinFirst = (
  files: readonly string[],
  options: Pick<ResolvedMasteringOptions, "pinFirst" | "pinFirstCount">
): readonly string[] => {
  if (options.pinFirst !== undefined) {
    const pinned = options.pinFirst.map((name) => {
      const target = files.find((file) => basename(file) === name);
      if (target === undefined) {
        throw new Error(`validation: pin_first track not found: ${name}`);
      }
      return target;
    });
    return [...pinned, ...files.filter((file) => !pinned.includes(file))];
  }

  if (options.pinFirstCount !== undefined && options.pinFirstCount > 0) {
    if (options.pinFirstCount > files.length) {
      throw new Error(
        `validation: pin_first_count exceeds track count: ${options.pinFirstCount}`
      );
    }
    return files;
  }

  return files;
};

export const resolveShuffleSeed = (
  options: Pick<ResolvedMasteringOptions, "shuffle" | "shuffleSeed">
): number | undefined => {
  if (!options.shuffle) {
    return undefined;
  }
  return options.shuffleSeed ?? randomInt(AUTO_SEED_BOUND);
};

export const shuffleTracks = (
  files: readonly string[],
  options: Pick<
    ResolvedMasteringOptions,
    "pinFirst" | "pinFirstCount" | "shuffle" | "shuffleSeed"
  >
): readonly string[] => {
  if (!options.shuffle) {
    return files;
  }
  const seed = options.shuffleSeed;
  if (seed === undefined) {
    throw new Error("validation: shuffle seed was not resolved");
  }
  const pinnedCount =
    options.pinFirst === undefined
      ? (options.pinFirstCount ?? 0)
      : options.pinFirst.length;
  const head = files.slice(0, pinnedCount);
  const tail = files.slice(pinnedCount);
  return [
    ...head,
    ...tail
      .map((file, index) => ({
        file,
        rank:
          Math.sin(seed + index * 10_000) -
          Math.floor(Math.sin(seed + index * 10_000)),
      }))
      .toSorted((left, right) => left.rank - right.rank)
      .map((entry) => entry.file),
  ];
};
