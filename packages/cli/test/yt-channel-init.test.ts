import { afterEach, describe, expect, test } from "bun:test";
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
import { join, resolve } from "node:path";

import { REGISTRY } from "@youtube-automation/core/registry";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const taykBin = join(repoRoot, "packages", "cli", "bin", "tayk.ts");
const tmpDirs: string[] = [];

const makeTempDir = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const realDir = realpathSync(dir);
  tmpDirs.push(realDir);
  return realDir;
};

afterEach(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

const runTayk = (
  options: { cwd?: string; env: Record<string, string | undefined> },
  ...argv: string[]
) => {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) {
      env[key] = value;
    }
  }
  for (const [key, value] of Object.entries(options.env)) {
    if (value === undefined) {
      Reflect.deleteProperty(env, key);
    } else {
      env[key] = value;
    }
  }

  return Bun.spawnSync(["bun", taykBin, ...argv], {
    cwd: options.cwd ?? repoRoot,
    env,
  });
};

const readJson = (path: string): Record<string, unknown> =>
  JSON.parse(readFileSync(path, "utf-8")) as Record<string, unknown>;

describe("core registry — channel.init entry visible from cli package", () => {
  test("should expose the registry entry consumed by the CLI adapter", () => {
    const entry = REGISTRY["channel.init"];

    expect(entry.deps).toEqual(["channelDir"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk channel-init — smoke", () => {
  test("should scaffold a target directory through the dispatcher", () => {
    const channelDir = makeTempDir("cli-channel-init-");

    const proc = runTayk(
      { env: { CHANNEL_DIR: undefined } },
      "channel-init",
      "--target",
      channelDir,
      "--short",
      "DEMO",
      "--name",
      "Demo Channel",
      "--genre",
      "ambient",
      "--style",
      "soft piano",
      "--context",
      "Study"
    );

    expect(proc.exitCode).toBe(0);
    expect(proc.stderr.toString()).toBe("");
    expect(proc.stdout.toString()).toContain(
      "  created     config/channel/meta.json"
    );
    expect(proc.stdout.toString()).toContain("  created     research/");
    const meta = readJson(join(channelDir, "config", "channel", "meta.json"));
    expect(meta).toMatchObject({
      channel: { name: "Demo Channel", short: "DEMO" },
    });
    expect(existsSync(join(channelDir, "auth", ".gitkeep"))).toBe(true);
  });

  test("should resolve target from CHANNEL_DIR when --target is omitted", () => {
    const channelDir = makeTempDir("cli-channel-init-env-");

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "channel-init",
      "--short",
      "ENV",
      "--name",
      "Env Channel"
    );

    expect(proc.exitCode).toBe(0);
    const meta = readJson(join(channelDir, "config", "channel", "meta.json"));
    expect(meta).toMatchObject({
      channel: { name: "Env Channel", short: "ENV" },
    });
  });

  test("should resolve target from CWD when --target and CHANNEL_DIR are omitted", () => {
    const channelDir = makeTempDir("cli-channel-init-cwd-");

    const proc = runTayk(
      { cwd: channelDir, env: { CHANNEL_DIR: undefined } },
      "channel-init",
      "--short",
      "CWD",
      "--name",
      "Cwd Channel"
    );

    expect(proc.exitCode).toBe(0);
    expect(existsSync(join(channelDir, "config", "channel", "meta.json"))).toBe(
      true
    );
  });

  test("should print unified diff to stderr and not overwrite without force", () => {
    const channelDir = makeTempDir("cli-channel-init-diff-");
    const metaPath = join(channelDir, "config", "channel", "meta.json");
    mkdirSync(join(channelDir, "config", "channel"), { recursive: true });
    writeFileSync(metaPath, '{"channel":{"name":"Old","short":"OLD"}}\n');

    const proc = runTayk(
      { env: { CHANNEL_DIR: undefined } },
      "channel-init",
      "--target",
      channelDir,
      "--short",
      "NEW",
      "--name",
      "New Channel"
    );

    expect(proc.exitCode).toBe(0);
    expect(proc.stdout.toString()).toContain(
      "  skipped     config/channel/meta.json"
    );
    expect(proc.stderr.toString()).toContain(
      "--- config/channel/meta.json (existing)"
    );
    expect(proc.stderr.toString()).toContain(
      "+++ config/channel/meta.json (template)"
    );
    expect(proc.stderr.toString()).toContain("@@ -1 +1,8 @@");
    expect(proc.stderr.toString()).not.toContain("-+{");
    expect(readFileSync(metaPath, "utf-8")).toBe(
      '{"channel":{"name":"Old","short":"OLD"}}\n'
    );
  });

  test("should overwrite with force and keep stderr free of diff output", () => {
    const channelDir = makeTempDir("cli-channel-init-force-");
    const initial = runTayk(
      { env: { CHANNEL_DIR: undefined } },
      "channel-init",
      "--target",
      channelDir,
      "--short",
      "OLD",
      "--name",
      "Old Channel"
    );
    expect(initial.exitCode).toBe(0);

    const proc = runTayk(
      { env: { CHANNEL_DIR: undefined } },
      "channel-init",
      "--target",
      channelDir,
      "--short",
      "NEW",
      "--name",
      "New Channel",
      "--force"
    );

    expect(proc.exitCode).toBe(0);
    expect(proc.stderr.toString()).toBe("");
    expect(proc.stdout.toString()).toContain(
      "  overwritten config/channel/meta.json"
    );
    const meta = readJson(join(channelDir, "config", "channel", "meta.json"));
    expect(meta).toMatchObject({
      channel: { name: "New Channel", short: "NEW" },
    });
  });
});
