import { afterEach, describe, expect, spyOn, test } from "bun:test";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import process from "node:process";

import { reset as resetConfig } from "@youtube-automation/core/config";
import { REGISTRY } from "@youtube-automation/core/registry";

import { finalizeMasterCommand } from "../src/commands/finalize-master/cli.ts";

let tmpDirs: string[] = [];

const makeTempDir = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const realDir = realpathSync(dir);
  tmpDirs = [...tmpDirs, realDir];
  return realDir;
};

afterEach(() => {
  for (const dir of tmpDirs) {
    rmSync(dir, { force: true, recursive: true });
  }
  tmpDirs = [];
});

const parseFinalizeMasterArgs = (
  argv: string[]
): { _: string[]; collection: string | undefined; json: boolean } => {
  let collection: string | undefined;
  let json = false;

  for (const token of argv) {
    if (token === "--json") {
      json = true;
    } else {
      collection = token;
    }
  }

  return { _: argv, collection, json };
};

const runFinalizeMaster = async (
  options: { cwd?: string; env: Record<string, string | undefined> },
  ...argv: string[]
): Promise<{ exitCode: number; stderr: string; stdout: string }> => {
  type FinalizeMasterRunContext = Parameters<
    NonNullable<typeof finalizeMasterCommand.run>
  >[0];

  const previousCwd = process.cwd();
  const previousEnv: Record<string, string | undefined> = {};
  let exitCode = 0;
  let stderr = "";
  let stdout = "";

  const stdoutSpy = spyOn(process.stdout, "write").mockImplementation(
    (chunk) => {
      stdout += String(chunk);
      return true;
    }
  );
  const stderrSpy = spyOn(process.stderr, "write").mockImplementation(
    (chunk) => {
      stderr += String(chunk);
      return true;
    }
  );
  const exitSpy = spyOn(process, "exit").mockImplementation((code) => {
    exitCode = typeof code === "number" ? code : 1;
    throw new Error(`process.exit:${exitCode}`);
  });

  for (const key of Object.keys(options.env)) {
    previousEnv[key] = process.env[key];
  }

  try {
    resetConfig();
    for (const [key, value] of Object.entries(options.env)) {
      if (value === undefined) {
        Reflect.deleteProperty(process.env, key);
      } else {
        process.env[key] = value;
      }
    }

    if (options.cwd !== undefined) {
      process.chdir(options.cwd);
    }

    await finalizeMasterCommand.run?.({
      args: parseFinalizeMasterArgs(
        argv
      ) as unknown as FinalizeMasterRunContext["args"],
      cmd: finalizeMasterCommand,
      rawArgs: argv,
    });
  } catch (error) {
    if (
      !(error instanceof Error) ||
      !error.message.startsWith("process.exit:")
    ) {
      throw error;
    }
  } finally {
    process.chdir(previousCwd);
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) {
        Reflect.deleteProperty(process.env, key);
      } else {
        process.env[key] = value;
      }
    }
    stdoutSpy.mockRestore();
    stderrSpy.mockRestore();
    exitSpy.mockRestore();
    resetConfig();
  }

  return { exitCode, stderr, stdout };
};

const dispatcherSource = (): string =>
  readFileSync(join(import.meta.dir, "..", "bin", "tayk.ts"), "utf-8");

const writeCollectionFixture = (collectionRoot: string): string => {
  const collectionDir = join(collectionRoot, "test");
  const masterDir = join(collectionDir, "01-master");
  const musicDir = join(collectionDir, "02-Individual-music");
  mkdirSync(masterDir, { recursive: true });
  mkdirSync(musicDir, { recursive: true });
  writeFileSync(join(masterDir, "master.mp3"), "master", "utf-8");
  return collectionDir;
};

const writePassThroughFixture = (): {
  channelDir: string;
  collectionDir: string;
} => {
  const channelDir = makeTempDir("cli-finalize-channel-");
  const collectionDir = writeCollectionFixture(
    join(channelDir, "collections", "planning")
  );
  return { channelDir, collectionDir };
};

describe("core registry — finalize.master entry visible from cli package", () => {
  test("should expose the registry entry consumed by the CLI adapter", () => {
    const entry = REGISTRY["finalize.master"];

    expect(entry.deps).toEqual(["channelDir"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk finalize-master — adapter contract", () => {
  test("should print JSON pass-through output for an explicit collection path", async () => {
    const { channelDir, collectionDir } = writePassThroughFixture();

    const proc = await runFinalizeMaster(
      { env: { CHANNEL_DIR: channelDir } },
      collectionDir,
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      layersApplied: number;
      loudnormApplied: boolean;
      masterPath: string;
      passThrough: boolean;
      warnings: string[];
    };
    expect(parsed).toEqual({
      layersApplied: 0,
      loudnormApplied: false,
      masterPath: join(collectionDir, "01-master", "master.mp3"),
      passThrough: true,
      warnings: [],
    });
    expect(existsSync(parsed.masterPath)).toBe(true);
  });

  test("should resolve a relative collection path from CWD", async () => {
    const channelDir = makeTempDir("cli-finalize-channel-");
    const cwd = makeTempDir("cli-finalize-cwd-");
    const collectionDir = writeCollectionFixture(cwd);

    const proc = await runFinalizeMaster(
      { cwd, env: { CHANNEL_DIR: channelDir } },
      "test",
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as { masterPath: string };
    expect(parsed.masterPath).toBe(
      join(collectionDir, "01-master", "master.mp3")
    );
  });

  test("should use CWD when collection path is omitted", async () => {
    const { channelDir, collectionDir } = writePassThroughFixture();

    const proc = await runFinalizeMaster(
      { cwd: collectionDir, env: { CHANNEL_DIR: channelDir } },
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as { masterPath: string };
    expect(parsed.masterPath).toBe(
      join(collectionDir, "01-master", "master.mp3")
    );
  });

  test("should fail validation when omitted collection path cannot use CWD", async () => {
    const channelDir = makeTempDir("cli-finalize-channel-");
    const cwd = makeTempDir("cli-finalize-not-collection-");

    const proc = await runFinalizeMaster(
      { cwd, env: { CHANNEL_DIR: channelDir } },
      "--json"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toStartWith("[validation] ");
    expect(proc.stderr.toString()).toContain(
      "コレクションディレクトリを解決できません"
    );
  });

  test("should format dependency resolution errors through the command helper", async () => {
    const proc = await runFinalizeMaster(
      { env: { CHANNEL_DIR: undefined } },
      "--json"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toStartWith("[config] ");
    expect(proc.stderr.toString()).toContain("CHANNEL_DIR");
    expect(proc.stderr.toString()).not.toContain("at ");
  });

  test("should list finalize-master in dispatcher help", () => {
    expect(dispatcherSource()).toContain(
      '"finalize-master": finalizeMasterCommand'
    );
  });

  test("should expose --json but not --quiet in command help", () => {
    expect(finalizeMasterCommand.args).toBeDefined();
    const commandArgs = finalizeMasterCommand.args ?? {};
    expect(Object.keys(commandArgs)).toContain("json");
    expect(Object.keys(commandArgs)).not.toContain("quiet");

    const source = dispatcherSource();
    expect(source).not.toContain("--quiet");
  });
});
