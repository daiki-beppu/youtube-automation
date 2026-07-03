import { afterEach, describe, expect, test } from "bun:test";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, delimiter, dirname, join, resolve } from "node:path";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const taykScript = join(repoRoot, "packages", "cli", "bin", "tayk.ts");
const cliPackageJsonPath = join(repoRoot, "packages", "cli", "package.json");
const tempRoots: string[] = [];
const CLI_SMOKE_TIMEOUT_MS = 15_000;

const makeTempRoot = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempRoots.push(dir);
  return dir;
};

const writeText = (path: string, data: string): void => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, data, "utf-8");
};

const setupCollection = (
  channelRoot: string,
  relativePath: string,
  fileNames: string[]
): void => {
  const collection = join(channelRoot, relativePath);
  mkdirSync(join(collection, "01-master"), { recursive: true });
  for (const name of fileNames) {
    writeText(join(collection, "02-Individual-music", name), `audio:${name}`);
  }
};

const installFakeFfmpeg = (): {
  env: Record<string, string>;
  logPath: string;
} => {
  const binDir = makeTempRoot("yt-generate-master-bin-");
  const logPath = join(binDir, "ffmpeg.log");
  const executable = join(binDir, "ffmpeg");
  writeText(
    executable,
    `#!/usr/bin/env bun
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const args = Bun.argv.slice(2);
appendFileSync(process.env.YT_TEST_FFMPEG_LOG!, JSON.stringify(args) + "\\n");
const output = args.find((arg) => arg.includes("/01-master/master.mp3"));
if (output !== undefined) {
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, "fake-master", "utf-8");
}
`
  );
  chmodSync(executable, 0o755);
  return {
    env: {
      PATH: `${binDir}${delimiter}${process.env.PATH ?? ""}`,
      YT_TEST_FFMPEG_LOG: logPath,
    },
    logPath,
  };
};

const installFakeFfprobe = (
  durationsByName: Record<string, number>,
  exitCode = 0
): {
  env: Record<string, string>;
  logPath: string;
} => {
  const binDir = makeTempRoot("yt-generate-master-probe-bin-");
  const logPath = join(binDir, "ffprobe.log");
  const executable = join(binDir, "ffprobe");
  writeText(
    executable,
    `#!/usr/bin/env bun
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
`
  );
  chmodSync(executable, 0o755);
  return {
    env: {
      PATH: `${binDir}${delimiter}${process.env.PATH ?? ""}`,
      YT_TEST_FFPROBE_DURATIONS: JSON.stringify(durationsByName),
      YT_TEST_FFPROBE_LOG: logPath,
    },
    logPath,
  };
};

const runTayk = (
  env: Record<string, string>,
  ...argv: string[]
): ReturnType<typeof Bun.spawnSync> => {
  const commandEnv = { ...process.env, ...env };
  if (!Object.hasOwn(env, "CHANNEL_DIR")) {
    Reflect.deleteProperty(commandEnv, "CHANNEL_DIR");
  }
  return Bun.spawnSync(["bun", taykScript, ...argv], {
    cwd: repoRoot,
    env: commandEnv,
    timeout: CLI_SMOKE_TIMEOUT_MS,
  });
};

const runTaykFrom = (
  cwd: string,
  env: Record<string, string>,
  ...argv: string[]
): ReturnType<typeof Bun.spawnSync> => {
  const commandEnv = { ...process.env, ...env };
  if (!Object.hasOwn(env, "CHANNEL_DIR")) {
    Reflect.deleteProperty(commandEnv, "CHANNEL_DIR");
  }
  return Bun.spawnSync(["bun", taykScript, ...argv], {
    cwd,
    env: commandEnv,
    timeout: CLI_SMOKE_TIMEOUT_MS,
  });
};

const readFfmpegCall = (logPath: string): string[] => {
  const [line] = readFileSync(logPath, "utf-8").trim().split("\n");
  if (line === undefined) {
    throw new Error("expected fake ffmpeg to be called");
  }
  return JSON.parse(line) as string[];
};

const readFfprobeCalls = (logPath: string): string[][] => {
  const text = readFileSync(logPath, "utf-8").trim();
  return text.length === 0
    ? []
    : text.split("\n").map((line) => JSON.parse(line) as string[]);
};

const inputFilesInCommand = (args: string[]): string[] => {
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

afterEach(() => {
  while (tempRoots.length > 0) {
    const dir = tempRoots.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

describe("tayk dispatcher — generate-master", () => {
  test("package exposes tayk as the primary dispatcher bin", () => {
    const packageJson = JSON.parse(
      readFileSync(cliPackageJsonPath, "utf-8")
    ) as {
      bin: Record<string, string>;
    };

    expect(packageJson.bin.tayk).toBe("./bin/tayk.ts");
    expect(packageJson.bin.yt).toBe("./bin/tayk.ts");
  });

  test(
    "help lists the generate-master subcommand",
    () => {
      // Given the dispatcher invoked with --help
      const proc = runTayk({}, "--help");

      // Then the new command is reachable from the single dispatcher.
      expect(proc.exitCode).toBe(0);
      expect(proc.stdout?.toString()).toContain("generate-master");
    },
    CLI_SMOKE_TIMEOUT_MS
  );

  test("runs generate-master through registry and prints JSON output", () => {
    // Given a channel-root-relative collection and fake ffmpeg on PATH
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
      "03-c.mp3",
    ]);
    const fake = installFakeFfmpeg();

    // When the collection positional is explicit and --pin-first receives multiple files
    const proc = runTayk(
      fake.env,
      "generate-master",
      "--json",
      "--channel-dir",
      channelRoot,
      "collections/demo",
      "--pin-first=03-c.mp3",
      "01-a.mp3"
    );

    // Then the CLI adapter passes the real contract shape to the service.
    expect(proc.exitCode).toBe(0);
    expect(proc.stderr?.toString()).toBe("");
    const parsed = JSON.parse(proc.stdout?.toString() ?? "") as {
      inputCount: number;
      outputPath: string;
      segmentCount: number;
    };
    expect(parsed.inputCount).toBe(3);
    expect(parsed.segmentCount).toBe(3);
    expect(parsed.outputPath).toBe(
      join(channelRoot, "collections/demo", "01-master", "master.mp3")
    );
    expect(
      inputFilesInCommand(readFfmpegCall(fake.logPath)).map((path) =>
        basename(path)
      )
    ).toEqual(["03-c.mp3", "01-a.mp3", "02-b.mp3"]);
  });

  test("runs target-duration through ffprobe and prints JSON output", () => {
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    const fakeFfmpeg = installFakeFfmpeg();
    const fakeFfprobe = installFakeFfprobe({
      "01-a.mp3": 30,
      "02-b.mp3": 30,
    });

    const proc = runTayk(
      {
        ...fakeFfmpeg.env,
        ...fakeFfprobe.env,
        PATH: [
          dirname(fakeFfprobe.logPath),
          dirname(fakeFfmpeg.logPath),
          process.env.PATH ?? "",
        ].join(delimiter),
      },
      "generate-master",
      "--json",
      "--channel-dir",
      channelRoot,
      "--target-duration",
      "3",
      "collections/demo"
    );

    expect(proc.exitCode).toBe(0);
    expect(proc.stderr?.toString()).toBe("");
    const parsed = JSON.parse(proc.stdout?.toString() ?? "") as {
      loopCount: number;
      segmentCount: number;
    };
    expect(parsed.loopCount).toBe(4);
    expect(parsed.segmentCount).toBe(8);
    expect(readFfprobeCalls(fakeFfprobe.logPath)).toHaveLength(2);
  });

  test("prints duration preview for text target-duration output", () => {
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    const fakeFfmpeg = installFakeFfmpeg();
    const fakeFfprobe = installFakeFfprobe({
      "01-a.mp3": 30,
      "02-b.mp3": 30,
    });

    const proc = runTayk(
      {
        ...fakeFfmpeg.env,
        ...fakeFfprobe.env,
        PATH: [
          dirname(fakeFfprobe.logPath),
          dirname(fakeFfmpeg.logPath),
          process.env.PATH ?? "",
        ].join(delimiter),
      },
      "generate-master",
      "--channel-dir",
      channelRoot,
      "--target-duration",
      "3",
      "collections/demo"
    );

    expect(proc.exitCode).toBe(0);
    const stdout = proc.stdout?.toString() ?? "";
    expect(stdout).toContain("Duration preview");
    expect(stdout).toContain("Track total : 01:00");
    expect(stdout).toContain("Target      : 03:00");
    expect(stdout).toContain("Estimated   : 03:53");
  });

  test("quiet suppresses the human summary output", () => {
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    const fake = installFakeFfmpeg();

    const proc = runTayk(
      fake.env,
      "generate-master",
      "--quiet",
      "--channel-dir",
      channelRoot,
      "collections/demo"
    );

    expect(proc.exitCode).toBe(0);
    expect(proc.stderr?.toString()).toBe("");
    expect(proc.stdout?.toString()).toBe("");
  });

  test("accepts equals value flags and negative numeric flag values", () => {
    // Given a channel-root-relative collection and fake ffmpeg on PATH
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    const fakeFfmpeg = installFakeFfmpeg();
    const fakeFfprobe = installFakeFfprobe({
      "01-a.mp3": 30,
      "02-b.mp3": 30,
    });

    // When citty help-advertised --flag=value syntax and a negative seed are used
    const proc = runTayk(
      {
        ...fakeFfmpeg.env,
        ...fakeFfprobe.env,
        PATH: [
          dirname(fakeFfprobe.logPath),
          dirname(fakeFfmpeg.logPath),
          process.env.PATH ?? "",
        ].join(delimiter),
      },
      "generate-master",
      "--json",
      "--channel-dir",
      channelRoot,
      "--loop=2",
      "--shuffle-seed",
      "-1",
      "collections/demo"
    );

    // Then the raw parser preserves the CLI contract before service execution.
    expect(proc.exitCode).toBe(0);
    expect(proc.stderr?.toString()).toBe("");
    const parsed = JSON.parse(proc.stdout?.toString() ?? "") as {
      loopCount: number;
      segmentCount: number;
    };
    expect(parsed.loopCount).toBe(2);
    expect(parsed.segmentCount).toBe(4);
  });

  test("uses trailing collection after pin-first when it resolves under channel dir", () => {
    // Given a channel-root-relative collection and fake ffmpeg on PATH
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-hook.mp3",
      "03-c.mp3",
    ]);
    const fake = installFakeFfmpeg();

    // When the collection argument appears after --pin-first before another option
    const proc = runTayk(
      fake.env,
      "generate-master",
      "--json",
      "--channel-dir",
      channelRoot,
      "--pin-first",
      "02-hook.mp3",
      "collections/demo",
      "--shuffle"
    );

    // Then the trailing directory is treated as collection, not as a pin-first file.
    expect(proc.exitCode).toBe(0);
    expect(proc.stderr?.toString()).toBe("");
    const parsed = JSON.parse(proc.stdout?.toString() ?? "") as {
      inputCount: number;
      outputPath: string;
      segmentCount: number;
    };
    expect(parsed.inputCount).toBe(3);
    expect(parsed.segmentCount).toBe(3);
    expect(parsed.outputPath).toBe(
      join(channelRoot, "collections/demo", "01-master", "master.mp3")
    );
    const inputNames = inputFilesInCommand(readFfmpegCall(fake.logPath)).map(
      (path) => basename(path)
    );
    expect(inputNames[0]).toBe("02-hook.mp3");
    expect(inputNames.toSorted()).toEqual([
      "01-a.mp3",
      "02-hook.mp3",
      "03-c.mp3",
    ]);
  });

  test("uses CHANNEL_DIR for relative trailing collection after pin-first", () => {
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-hook.mp3",
      "03-c.mp3",
    ]);
    const fake = installFakeFfmpeg();

    const proc = runTayk(
      { ...fake.env, CHANNEL_DIR: channelRoot },
      "generate-master",
      "--json",
      "--pin-first",
      "02-hook.mp3",
      "collections/demo",
      "--shuffle"
    );

    expect(proc.exitCode).toBe(0);
    expect(proc.stderr?.toString()).toBe("");
    const parsed = JSON.parse(proc.stdout?.toString() ?? "") as {
      outputPath: string;
    };
    expect(parsed.outputPath).toBe(
      join(channelRoot, "collections/demo", "01-master", "master.mp3")
    );
    expect(
      inputFilesInCommand(readFfmpegCall(fake.logPath)).map((path) =>
        basename(path)
      )
    ).toContain("02-hook.mp3");
  });

  test("service errors flow through run-command stderr and exit code", () => {
    // Given the requested collection does not exist
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    const fake = installFakeFfmpeg();

    // When the command is executed
    const proc = runTayk(
      fake.env,
      "generate-master",
      "--channel-dir",
      channelRoot,
      "collections/missing"
    );

    // Then emitResult handles the ServiceError boundary.
    expect(proc.exitCode).toBe(1);
    expect(proc.stdout?.toString()).toBe("");
    expect(proc.stderr?.toString()).toContain("[validation]");
  });

  test("parse errors flow through run-command stderr and exit code", () => {
    // Given an unknown option before service execution
    const proc = runTayk({}, "generate-master", "--unknown-option");

    // Then the CLI still emits the shared ServiceError format.
    expect(proc.exitCode).toBe(1);
    expect(proc.stdout?.toString()).toBe("");
    expect(proc.stderr?.toString()).toContain("[validation]");
    expect(proc.stderr?.toString()).toContain("unknown option");
    expect(proc.stderr?.toString()).not.toContain("ZodError");
  });

  test("rejects multiple collection positionals before service execution", () => {
    const proc = runTayk(
      {},
      "generate-master",
      "collections/one",
      "collections/two"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stdout?.toString()).toBe("");
    expect(proc.stderr?.toString()).toContain("[validation]");
    expect(proc.stderr?.toString()).toContain("at most one collection");
  });

  test("rejects pin-first with no following values before service execution", () => {
    const proc = runTayk({}, "generate-master", "--pin-first", "--shuffle");

    expect(proc.exitCode).toBe(1);
    expect(proc.stdout?.toString()).toBe("");
    expect(proc.stderr?.toString()).toContain("[validation]");
    expect(proc.stderr?.toString()).toContain("--pin-first requires a value");
  });

  test("uses cwd collection with multiple pin-first files when collection positional is omitted", () => {
    // Given the process cwd is a collection directory
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    const collection = join(channelRoot, "collections", "demo");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-hook.mp3",
      "03-intro.mp3",
    ]);
    const fake = installFakeFfmpeg();

    // When pin-first is passed without a collection positional
    const proc = runTaykFrom(
      collection,
      fake.env,
      "generate-master",
      "--pin-first",
      "02-hook.mp3",
      "03-intro.mp3",
      "--shuffle"
    );

    // Then pin-first stays a pin value and cwd supplies the collection.
    expect(proc.exitCode).toBe(0);
    expect(proc.stderr?.toString()).toBe("");
    expect(
      inputFilesInCommand(readFfmpegCall(fake.logPath)).map((path) =>
        basename(path)
      )
    ).toEqual(["02-hook.mp3", "03-intro.mp3", "01-a.mp3"]);
  });

  test("derives channel config from an absolute collection path", () => {
    const channelRoot = makeTempRoot("yt-generate-master-channel-");
    const collection = join(channelRoot, "collections", "demo");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    mkdirSync(join(channelRoot, "config", "channel"), { recursive: true });
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { bitrate: "320k", crossfade_duration: 2 } })
    );
    const fake = installFakeFfmpeg();

    const proc = runTayk(fake.env, "generate-master", "--json", collection);

    expect(proc.exitCode).toBe(0);
    expect(proc.stderr?.toString()).toBe("");
    const parsed = JSON.parse(proc.stdout?.toString() ?? "") as {
      bitrate: string;
      crossfadeDuration: number;
    };
    expect(parsed.bitrate).toBe("320k");
    expect(parsed.crossfadeDuration).toBe(2);
  });
});
