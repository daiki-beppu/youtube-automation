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

import { REGISTRY } from "@tayk/core/registry";

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

const writeFixture = (): { channelDir: string; collectionDir: string } => {
  const channelDir = makeTempDir("cli-suno-channel-");
  mkdirSync(join(channelDir, "config", "skills"), { recursive: true });
  writeFileSync(
    join(channelDir, "config", "skills", "suno.yaml"),
    'genre_line: "lo-fi jazz, soft piano, warm rhodes, mellow drums, slow"\n',
    "utf-8"
  );

  const collectionDir = join(channelDir, "collections", "planning", "test");
  const docsDir = join(collectionDir, "20-documentation");
  mkdirSync(docsDir, { recursive: true });
  writeFileSync(
    join(docsDir, "suno-patterns.yaml"),
    [
      'title: "CLI Smoke"',
      "mode: instrumental",
      "tracks: 2",
      "patterns:",
      '  - name_jp: "午後"',
      '    name_en: "Afternoon"',
      '    tempo: "slow"',
      "    scenes:",
      '      - "sunlight across a quiet desk"',
    ].join("\n"),
    "utf-8"
  );

  return { channelDir, collectionDir };
};

const writeWarningFixture = (): {
  channelDir: string;
  collectionDir: string;
} => {
  const channelDir = makeTempDir("cli-suno-warning-channel-");
  mkdirSync(join(channelDir, "config", "skills"), { recursive: true });
  writeFileSync(
    join(channelDir, "config", "skills", "suno.yaml"),
    [
      'genre_line: "slow, ambient pad, soft synth, airy textures, subtle bass"',
      "style_char_limit: 40",
      "auto_lyrics_structure: false",
    ].join("\n"),
    "utf-8"
  );

  const collectionDir = join(channelDir, "collections", "planning", "warning");
  const docsDir = join(collectionDir, "20-documentation");
  mkdirSync(docsDir, { recursive: true });
  writeFileSync(
    join(docsDir, "suno-patterns.yaml"),
    [
      'title: "CLI Warning"',
      "mode: instrumental",
      "tracks: 2",
      "patterns:",
      '  - name_jp: "警告"',
      '    name_en: "Warning"',
      '    tempo: "slow"',
      "    scenes:",
      '      - "a very long descriptive scene with rain on glass and a quiet late night desk lamp"',
    ].join("\n"),
    "utf-8"
  );

  return { channelDir, collectionDir };
};

describe("core registry — suno.generate entry visible from cli package", () => {
  test("should expose the registry entry consumed by the CLI adapter", () => {
    const entry = REGISTRY["suno.generate"];

    expect(entry.deps).toEqual(["channelDir"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk generate-suno — smoke", () => {
  test("should generate artifacts through the dispatcher and print JSON output", () => {
    const { channelDir, collectionDir } = writeFixture();

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-suno",
      collectionDir,
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      entryCount: number;
      jsonPath: string;
      markdownPath: string;
    };
    expect(parsed.entryCount).toBe(1);
    expect(parsed.markdownPath).toBe(
      join(collectionDir, "20-documentation", "suno-prompts.md")
    );
    expect(parsed.jsonPath).toBe(
      join(collectionDir, "20-documentation", "suno-prompts.json")
    );
    expect(existsSync(parsed.markdownPath)).toBe(true);
    expect(existsSync(parsed.jsonPath)).toBe(true);
    expect(readFileSync(parsed.jsonPath, "utf-8")).toContain(
      "午後 — Afternoon"
    );
  });

  test("should accept a collection path relative to CHANNEL_DIR", () => {
    const { channelDir, collectionDir } = writeFixture();
    const relativeCollectionDir = collectionDir.slice(channelDir.length + 1);

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-suno",
      relativeCollectionDir,
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      jsonPath: string;
    };
    expect(parsed.jsonPath).toBe(
      join(collectionDir, "20-documentation", "suno-prompts.json")
    );
    expect(existsSync(parsed.jsonPath)).toBe(true);
  });

  test("should use CWD when collection path is omitted", () => {
    const { channelDir, collectionDir } = writeFixture();

    const proc = runTayk(
      { cwd: collectionDir, env: { CHANNEL_DIR: channelDir } },
      "generate-suno",
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      jsonPath: string;
    };
    expect(parsed.jsonPath).toBe(
      join(collectionDir, "20-documentation", "suno-prompts.json")
    );
    expect(existsSync(parsed.jsonPath)).toBe(true);
  });

  test("should format dependency resolution errors through the command helper", () => {
    const proc = runTayk(
      { env: { CHANNEL_DIR: undefined } },
      "generate-suno",
      "--json"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toStartWith("[config] ");
    expect(proc.stderr.toString()).toContain("CHANNEL_DIR");
    expect(proc.stderr.toString()).not.toContain("at ");
  });

  test("should list generate-suno in dispatcher help", () => {
    const proc = runTayk({ env: {} }, "--help");

    expect(proc.exitCode).toBe(0);
    expect(proc.stdout.toString()).toContain("generate-suno");
  });

  test("should print quality warnings in normal text output", () => {
    const { channelDir, collectionDir } = writeWarningFixture();

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-suno",
      collectionDir
    );

    expect(proc.exitCode).toBe(0);
    const stdout = proc.stdout.toString();
    expect(stdout).toContain("generated: 1");
    expect(stdout).toContain("[WARN]");
    expect(stdout).toContain("Style text exceeds 40 char limit");
  });
});
