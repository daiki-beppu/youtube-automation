/* eslint-disable no-restricted-properties -- #772 requires ffmpeg/ffprobe subprocess execution inside the core service boundary. */
import { join } from "node:path";

import { MASTER_OUTPUT_BASENAME, MASTER_OUTPUT_DIR } from "./schema.ts";
import type { SupportedAudioExtension } from "./schema.ts";
import type { ResolvedMasteringOptions } from "./types.ts";

const PROCESS_SUCCESS_CODE = 0;

const assertToolExists = (name: "ffmpeg" | "ffprobe"): void => {
  if (Bun.which(name) === null) {
    throw new Error(`validation: ${name} was not found`);
  }
};

const readProcessOutput = async (
  stream: ReadableStream<Uint8Array>
): Promise<string> => await new Response(stream).text();

const probeDuration = async (file: string): Promise<number> => {
  assertToolExists("ffprobe");
  const proc = Bun.spawn([
    "ffprobe",
    "-v",
    "error",
    "-show_entries",
    "format=duration",
    "-of",
    "default=noprint_wrappers=1:nokey=1",
    file,
  ]);
  const [exitCode, stdout] = await Promise.all([
    proc.exited,
    readProcessOutput(proc.stdout),
  ]);
  if (exitCode !== PROCESS_SUCCESS_CODE) {
    throw new Error(`validation: ffprobe failed for ${file}`);
  }
  const duration = Number(stdout.trim());
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error(
      `validation: ffprobe returned invalid duration for ${file}`
    );
  }
  return duration;
};

const expandedDurationSeconds = (
  singleLoopSeconds: number,
  trackCount: number,
  loopCount: number,
  crossfadeSeconds: number
): number =>
  loopCount * singleLoopSeconds -
  Math.max(loopCount * trackCount - 1, 0) * crossfadeSeconds;

export const resolveLoopCount = async (
  files: readonly string[],
  options: Pick<
    ResolvedMasteringOptions,
    "crossfadeSeconds" | "loop" | "targetDuration"
  >
): Promise<number> => {
  if (options.loop !== undefined) {
    return options.loop;
  }
  if (options.targetDuration !== undefined) {
    const durations = await Promise.all(
      files.map((file) => probeDuration(file))
    );
    const singleLoopSeconds = durations.reduce(
      (total, duration) => total + duration,
      0
    );
    const targetSeconds = options.targetDuration * 60;
    const firstLoopSeconds = expandedDurationSeconds(
      singleLoopSeconds,
      files.length,
      1,
      options.crossfadeSeconds
    );
    const additionalLoopSeconds =
      singleLoopSeconds - files.length * options.crossfadeSeconds;
    if (firstLoopSeconds < targetSeconds && additionalLoopSeconds <= 0) {
      throw new Error("validation: crossfade duration prevents loop expansion");
    }
    let loopCount = 1;
    while (
      expandedDurationSeconds(
        singleLoopSeconds,
        files.length,
        loopCount,
        options.crossfadeSeconds
      ) < targetSeconds
    ) {
      loopCount += 1;
    }
    return loopCount;
  }
  return 1;
};

const buildFilter = (
  segmentCount: number,
  crossfadeSeconds: number
): string => {
  const duration = `${crossfadeSeconds}`;
  if (segmentCount === 2) {
    return `[0:a][1:a]acrossfade=d=${duration}:c1=tri:c2=tri[aout]`;
  }
  return [
    `[0:a][1:a]acrossfade=d=${duration}:c1=tri:c2=tri[cf1]`,
    ...Array.from({ length: Math.max(segmentCount - 3, 0) }, (_, offset) => {
      const index = offset + 2;
      return `[cf${index - 1}][${index}:a]acrossfade=d=${duration}:c1=tri:c2=tri[cf${index}]`;
    }),
    `[cf${segmentCount - 2}][${segmentCount - 1}:a]acrossfade=d=${duration}:c1=tri:c2=tri[aout]`,
  ].join(";");
};

const codecArgs = (
  audioExt: SupportedAudioExtension,
  bitrate: string
): readonly string[] => {
  if (audioExt === "mp3") {
    return ["-c:a", "libmp3lame", "-b:a", bitrate];
  }
  return ["-c:a", "pcm_s16le"];
};

export const masterOutputPath = (
  collectionDir: string,
  audioExt: SupportedAudioExtension
): string =>
  join(
    collectionDir,
    MASTER_OUTPUT_DIR,
    `${MASTER_OUTPUT_BASENAME}.${audioExt}`
  );

export const runFfmpeg = async (
  files: readonly string[],
  outputPath: string,
  options: Pick<ResolvedMasteringOptions, "bitrate" | "crossfadeSeconds"> & {
    readonly audioExt: SupportedAudioExtension;
  }
): Promise<void> => {
  assertToolExists("ffmpeg");
  const inputArgs = files.flatMap((file) => ["-i", file]);
  const argv = [
    "ffmpeg",
    "-y",
    ...inputArgs,
    "-filter_complex",
    buildFilter(files.length, options.crossfadeSeconds),
    "-map",
    "[aout]",
    ...codecArgs(options.audioExt, options.bitrate),
    outputPath,
  ];
  const proc = Bun.spawn(argv);
  const exitCode = await proc.exited;
  if (exitCode !== PROCESS_SUCCESS_CODE) {
    throw new Error(`io: ffmpeg failed with exit code ${exitCode}`);
  }
};
