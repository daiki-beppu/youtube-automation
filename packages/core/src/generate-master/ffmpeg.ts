import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { delimiter, join } from "node:path";
import process from "node:process";

import type { EffectiveGenerateMasterInput } from "./audio.ts";
import { AUTO_SEED_BOUND, OUTPUT_CODEC_ARGS } from "./constants.ts";

const normalizeSeed = (seed: number): number => {
  const normalized = Math.trunc(seed) % AUTO_SEED_BOUND;
  return normalized < 0 ? normalized + AUTO_SEED_BOUND : normalized;
};

export const seededRandom = (seed: number): (() => number) => {
  let state = normalizeSeed(seed);
  return () => {
    state = (state * 1_664_525 + 1_013_904_223) % AUTO_SEED_BOUND;
    return state / AUTO_SEED_BOUND;
  };
};

const currentProcessEnv = (): Record<string, string> =>
  Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] => entry[1] !== undefined
    )
  );

const buildFilter = (count: number, crossfadeDuration: number): string => {
  const duration = `${crossfadeDuration}`;
  if (count === 2) {
    return `[0:a][1:a]acrossfade=d=${duration}:c1=tri:c2=tri[aout]`;
  }
  const parts = [`[0:a][1:a]acrossfade=d=${duration}:c1=tri:c2=tri[cf1]`];
  for (let index = 2; index < count - 1; index += 1) {
    parts.push(
      `[cf${index - 1}][${index}:a]acrossfade=d=${duration}:c1=tri:c2=tri[cf${index}]`
    );
  }
  parts.push(
    `[cf${count - 2}][${count - 1}:a]acrossfade=d=${duration}:c1=tri:c2=tri[aout]`
  );
  return parts.join(";");
};

export const buildFfmpegArgs = (
  inputs: string[],
  outputPath: string,
  input: EffectiveGenerateMasterInput
): string[] => {
  if (inputs.length === 1) {
    const [only] = inputs;
    if (only === undefined) {
      throw new Error("validation: expected one input");
    }
    return [
      "-y",
      "-i",
      only,
      ...OUTPUT_CODEC_ARGS,
      "-b:a",
      input.bitrate,
      outputPath,
      "-loglevel",
      "error",
    ];
  }
  const args = ["-y"];
  for (const file of inputs) {
    args.push("-i", file);
  }
  args.push(
    "-filter_complex",
    buildFilter(inputs.length, input.crossfadeDuration),
    "-map",
    "[aout]",
    ...OUTPUT_CODEC_ARGS,
    "-b:a",
    input.bitrate,
    outputPath,
    "-loglevel",
    "error"
  );
  return args;
};

const runProcess = async (
  command: string,
  args: string[]
): Promise<{ exitCode: number; stderr: string; stdout: string }> => {
  const child = spawn(command, args, { env: currentProcessEnv() });
  const stdoutChunks: Buffer[] = [];
  const stderrChunks: Buffer[] = [];
  child.stdout.on("data", (chunk: Buffer) => {
    stdoutChunks.push(chunk);
  });
  child.stderr.on("data", (chunk: Buffer) => {
    stderrChunks.push(chunk);
  });
  const [code] = (await Promise.race([
    once(child, "close") as Promise<[number | null]>,
    once(child, "error").then(([error]) => {
      throw error instanceof Error ? error : new Error(String(error));
    }) as Promise<[number | null]>,
  ])) as [number | null];
  return {
    exitCode: code ?? 1,
    stderr: Buffer.concat(stderrChunks).toString("utf-8"),
    stdout: Buffer.concat(stdoutChunks).toString("utf-8"),
  };
};

const resolveExecutableFromPath = (name: string): string | null => {
  const pathValue = process.env.PATH;
  if (pathValue === undefined || pathValue.length === 0) {
    return null;
  }
  for (const dir of pathValue.split(delimiter)) {
    const candidate = join(dir, name);
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
};

export const probeDuration = async (file: string): Promise<number> => {
  const ffprobe = resolveExecutableFromPath("ffprobe");
  if (ffprobe === null) {
    throw new Error("validation: ffprobe not found");
  }
  const { exitCode, stdout } = await runProcess(ffprobe, [
    "-v",
    "error",
    "-show_entries",
    "format=duration",
    "-of",
    "default=noprint_wrappers=1:nokey=1",
    "--",
    file,
  ]);
  if (exitCode !== 0) {
    throw new Error(`validation: failed to probe track duration: ${file}`);
  }
  const duration = Number(stdout.trim());
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error(`validation: invalid track duration: ${file}`);
  }
  return duration;
};

export const runFfmpeg = async (args: string[]): Promise<void> => {
  const ffmpeg = resolveExecutableFromPath("ffmpeg");
  if (ffmpeg === null) {
    throw new Error("validation: ffmpeg not found");
  }
  const { exitCode, stderr } = await runProcess(ffmpeg, args);
  if (exitCode !== 0) {
    throw new Error(
      `ffmpeg failed with exit code ${exitCode}: ${stderr.trim()}`
    );
  }
};
