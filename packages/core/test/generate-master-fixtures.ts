import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";

const tempRoots: string[] = [];
let savedEnv: Record<string, string | undefined> = {};

export const makeTempRoot = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempRoots.push(dir);
  return dir;
};

export const writeText = (path: string, data: string): void => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, data, "utf-8");
};

const writeBytes = (path: string, data: string): void => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, data);
};

export const setupCollection = (
  channelRoot: string,
  relativePath: string,
  fileNames: string[]
): string => {
  const collection = join(channelRoot, relativePath);
  mkdirSync(join(collection, "01-master"), { recursive: true });
  const musicDir = join(collection, "02-Individual-music");
  mkdirSync(musicDir, { recursive: true });
  for (const name of fileNames) {
    writeBytes(join(musicDir, name), `audio:${name}`);
  }
  return collection;
};

export const installFakeFfmpeg = (
  options: number | { exitCode?: number; writeOutput?: boolean } = 0
): string => {
  const exitCode =
    typeof options === "number" ? options : (options.exitCode ?? 0);
  const writeOutput =
    typeof options === "number" ? true : (options.writeOutput ?? true);
  const binDir = makeTempRoot("generate-master-bin-");
  const logPath = join(binDir, "ffmpeg.log");
  const script = `#!/usr/bin/env bun
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const args = Bun.argv.slice(2);
appendFileSync(process.env.YT_TEST_FFMPEG_LOG!, JSON.stringify(args) + "\\n");
const output = args.find((arg) => arg.includes("/01-master/master.mp3"));
if (${writeOutput} && output !== undefined) {
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, "fake-master", "utf-8");
}
process.exit(${exitCode});
`;
  const executable = join(binDir, "ffmpeg");
  writeText(executable, script);
  chmodSync(executable, 0o755);
  process.env.PATH = `${binDir}${delimiter}${process.env.PATH ?? ""}`;
  process.env.YT_TEST_FFMPEG_LOG = logPath;
  return logPath;
};

export const installFakeFfprobe = (
  durationsByName: Record<string, number>,
  exitCode = 0
): string => {
  const binDir = makeTempRoot("generate-master-probe-bin-");
  const logPath = join(binDir, "ffprobe.log");
  const script = `#!/usr/bin/env bun
import { appendFileSync } from "node:fs";
import { basename } from "node:path";

const args = Bun.argv.slice(2);
appendFileSync(process.env.YT_TEST_FFPROBE_LOG!, JSON.stringify(args) + "\\n");
const file = args.at(-1);
const durations = JSON.parse(process.env.YT_TEST_FFPROBE_DURATIONS ?? "{}");
if (${exitCode} !== 0 || file === undefined) {
  process.exit(${exitCode === 0 ? 1 : exitCode});
}
const duration = durations[basename(file)];
if (duration === undefined) {
  process.exit(1);
}
process.stdout.write(String(duration));
`;
  const executable = join(binDir, "ffprobe");
  writeText(executable, script);
  chmodSync(executable, 0o755);
  process.env.PATH = `${binDir}${delimiter}${process.env.PATH ?? ""}`;
  process.env.YT_TEST_FFPROBE_LOG = logPath;
  process.env.YT_TEST_FFPROBE_DURATIONS = JSON.stringify(durationsByName);
  return logPath;
};

export const readFfmpegCalls = (logPath: string): string[][] => {
  if (!existsSync(logPath)) {
    return [];
  }
  return readFileSync(logPath, "utf-8")
    .trim()
    .split("\n")
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as string[]);
};

export const readFfprobeCalls = (logPath: string): string[][] => {
  if (!existsSync(logPath)) {
    return [];
  }
  return readFileSync(logPath, "utf-8")
    .trim()
    .split("\n")
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as string[]);
};

export const inputFilesInCommand = (args: string[]): string[] => {
  const inputs: string[] = [];
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === "-i") {
      const value = args[index + 1];
      if (value !== undefined) {
        inputs.push(value);
      }
    }
  }
  return inputs;
};

export const saveGenerateMasterEnv = (): void => {
  savedEnv = {
    CHANNEL_DIR: process.env.CHANNEL_DIR,
    PATH: process.env.PATH,
    YT_TEST_FFMPEG_LOG: process.env.YT_TEST_FFMPEG_LOG,
    YT_TEST_FFPROBE_DURATIONS: process.env.YT_TEST_FFPROBE_DURATIONS,
    YT_TEST_FFPROBE_LOG: process.env.YT_TEST_FFPROBE_LOG,
  };
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  Reflect.deleteProperty(process.env, "YT_TEST_FFMPEG_LOG");
  Reflect.deleteProperty(process.env, "YT_TEST_FFPROBE_DURATIONS");
  Reflect.deleteProperty(process.env, "YT_TEST_FFPROBE_LOG");
};

export const restoreGenerateMasterFixtures = (): void => {
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) {
      Reflect.deleteProperty(process.env, key);
    } else {
      process.env[key] = value;
    }
  }
  while (tempRoots.length > 0) {
    const dir = tempRoots.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
};
