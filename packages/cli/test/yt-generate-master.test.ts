import { afterEach, describe, expect, test } from "bun:test";
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
import { basename, delimiter, dirname, join, resolve } from "node:path";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const taykScript = join(repoRoot, "packages", "cli", "bin", "tayk.ts");
const cliPackageJsonPath = join(repoRoot, "packages", "cli", "package.json");
const tempRoots: string[] = [];
const CLI_SMOKE_TIMEOUT_MS = 15_000;

const testCliSmoke = (name: string, fn: () => void): void => {
  test(name, fn, CLI_SMOKE_TIMEOUT_MS);
};

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

const runYtAlias = (...argv: string[]): ReturnType<typeof Bun.spawnSync> => {
  const binDir = makeTempRoot("yt-generate-master-alias-bin-");
  const executable = join(binDir, "yt");
  writeText(
    executable,
    `#!/usr/bin/env sh\nexec bun ${JSON.stringify(taykScript)} "$@"\n`
  );
  chmodSync(executable, 0o755);
  return Bun.spawnSync([executable, ...argv], {
    cwd: repoRoot,
    env: { ...process.env },
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
      const proc = runTayk({}, "--help");
      expect(proc.exitCode).toBe(0);
      expect(proc.stdout?.toString()).toContain("generate-master");
    },
    CLI_SMOKE_TIMEOUT_MS
  );

  testCliSmoke("yt alias reaches generate-master help", () => {
    const proc = runYtAlias("generate-master", "--help");

    expect(proc.exitCode).toBe(0);
    expect(proc.stdout?.toString()).toContain("--target-duration");
  });

  testCliSmoke(
    "runs generate-master through registry and prints JSON output",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      setupCollection(channelRoot, "collections/demo", [
        "01-a.mp3",
        "02-b.mp3",
        "03-c.mp3",
      ]);
      const fake = installFakeFfmpeg();
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
    }
  );

  testCliSmoke(
    "runs target-duration through ffprobe and prints JSON output",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      setupCollection(channelRoot, "collections/demo", [
        "01-a.mp3",
        "02-b.mp3",
      ]);
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
    }
  );

  testCliSmoke(
    "prints duration preview for text target-duration output",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      setupCollection(channelRoot, "collections/demo", [
        "01-a.mp3",
        "02-b.mp3",
      ]);
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
    }
  );

  testCliSmoke("quiet suppresses the human summary output", () => {
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

  testCliSmoke(
    "accepts equals value flags and negative numeric flag values",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      setupCollection(channelRoot, "collections/demo", [
        "01-a.mp3",
        "02-b.mp3",
      ]);
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
        "--loop=2",
        "--shuffle-seed",
        "-1",
        "collections/demo"
      );
      expect(proc.exitCode).toBe(0);
      expect(proc.stderr?.toString()).toBe("");
      const parsed = JSON.parse(proc.stdout?.toString() ?? "") as {
        loopCount: number;
        segmentCount: number;
      };
      expect(parsed.loopCount).toBe(2);
      expect(parsed.segmentCount).toBe(4);
    }
  );

  testCliSmoke(
    "uses trailing collection after pin-first when it resolves under channel dir",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      setupCollection(channelRoot, "collections/demo", [
        "01-a.mp3",
        "02-hook.mp3",
        "03-c.mp3",
      ]);
      const fake = installFakeFfmpeg();
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
    }
  );

  testCliSmoke(
    "uses CHANNEL_DIR for relative trailing collection after pin-first",
    () => {
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
    }
  );

  testCliSmoke(
    "service errors flow through run-command stderr and exit code",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      const fake = installFakeFfmpeg();
      const proc = runTayk(
        fake.env,
        "generate-master",
        "--channel-dir",
        channelRoot,
        "collections/missing"
      );
      expect(proc.exitCode).toBe(1);
      expect(proc.stdout?.toString()).toBe("");
      expect(proc.stderr?.toString()).toContain("[validation]");
    }
  );

  testCliSmoke(
    "parse errors flow through run-command stderr and exit code",
    () => {
      const proc = runTayk({}, "generate-master", "--unknown-option");
      expect(proc.exitCode).toBe(1);
      expect(proc.stdout?.toString()).toBe("");
      expect(proc.stderr?.toString()).toContain("[validation]");
      expect(proc.stderr?.toString()).toContain("unknown option");
      expect(proc.stderr?.toString()).not.toContain("ZodError");
    }
  );

  testCliSmoke(
    "rejects multiple collection positionals before service execution",
    () => {
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
    }
  );

  testCliSmoke(
    "rejects pin-first with no following values before service execution",
    () => {
      const proc = runTayk({}, "generate-master", "--pin-first", "--shuffle");

      expect(proc.exitCode).toBe(1);
      expect(proc.stdout?.toString()).toBe("");
      expect(proc.stderr?.toString()).toContain("[validation]");
      expect(proc.stderr?.toString()).toContain("--pin-first requires a value");
    }
  );

  testCliSmoke(
    "uses cwd collection with multiple pin-first files when collection positional is omitted",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      const collection = join(channelRoot, "collections", "demo");
      setupCollection(channelRoot, "collections/demo", [
        "01-a.mp3",
        "02-hook.mp3",
        "03-intro.mp3",
      ]);
      const fake = installFakeFfmpeg();
      const proc = runTaykFrom(
        collection,
        { ...fake.env, CHANNEL_DIR: channelRoot },
        "generate-master",
        "--pin-first",
        "02-hook.mp3",
        "03-intro.mp3",
        "--shuffle"
      );
      expect(proc.exitCode).toBe(0);
      expect(proc.stderr?.toString()).toBe("");
      expect(
        inputFilesInCommand(readFfmpegCall(fake.logPath)).map((path) =>
          basename(path)
        )
      ).toEqual(["02-hook.mp3", "03-intro.mp3", "01-a.mp3"]);
    }
  );

  testCliSmoke(
    "derives channel config from an absolute collection path",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      const collection = join(channelRoot, "collections", "demo");
      setupCollection(channelRoot, "collections/demo", [
        "01-a.mp3",
        "02-b.mp3",
      ]);
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
    }
  );

  testCliSmoke(
    "rejects channel-dir-relative collection paths that escape the channel root",
    () => {
      const parent = makeTempRoot("yt-generate-master-parent-");
      const channelRoot = join(parent, "channel");
      mkdirSync(channelRoot, { recursive: true });
      setupCollection(parent, "victim", ["01-outside.mp3"]);
      const fake = installFakeFfmpeg();

      const proc = runTayk(
        fake.env,
        "generate-master",
        "--json",
        "--channel-dir",
        channelRoot,
        "../victim"
      );

      expect(proc.exitCode).toBe(1);
      expect(proc.stdout?.toString()).toBe("");
      expect(proc.stderr?.toString()).toContain("[validation]");
      expect(proc.stderr?.toString()).toContain(
        "collection escapes channel_dir"
      );
      expect(existsSync(fake.logPath)).toBe(false);
      expect(
        existsSync(join(parent, "victim", "01-master", "master.mp3"))
      ).toBe(false);
    }
  );

  testCliSmoke(
    "keeps a missing path-like token after pin-first as the requested collection",
    () => {
      const channelRoot = makeTempRoot("yt-generate-master-channel-");
      setupCollection(channelRoot, "collections/demo", ["01-a.mp3"]);
      const fake = installFakeFfmpeg();

      const proc = runTayk(
        fake.env,
        "generate-master",
        "--json",
        "--channel-dir",
        channelRoot,
        "--pin-first",
        "01-a.mp3",
        "collections/missing"
      );

      expect(proc.exitCode).toBe(1);
      expect(proc.stdout?.toString()).toBe("");
      expect(proc.stderr?.toString()).toContain("[validation]");
      expect(proc.stderr?.toString()).toContain("collections/missing");
      expect(existsSync(fake.logPath)).toBe(false);
    }
  );
});
