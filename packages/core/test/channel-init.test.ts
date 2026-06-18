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
import { join } from "node:path";

import * as channelInitPublicApi from "@youtube-automation/core/channel-init";
import {
  channelInitService,
  ChannelInitInputSchema,
} from "@youtube-automation/core/channel-init";
import type {
  ChannelInitInput,
  ChannelInitOutput,
} from "@youtube-automation/core/channel-init";
import {
  loadConfig,
  reset as resetConfig,
} from "@youtube-automation/core/config";
import { REGISTRY } from "@youtube-automation/core/registry";

const tmpDirs: string[] = [];
let savedChannelDir: string | undefined;

const configFiles = [
  "meta.json",
  "content.json",
  "youtube.json",
  "analytics.json",
  "playlists.json",
  "workflow.json",
  "audio.json",
] as const;

const gitkeepDirs = [
  "auth",
  "collections",
  "data",
  "docs/benchmarks",
  "research",
] as const;

const makeTempDir = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const realDir = realpathSync(dir);
  tmpDirs.push(realDir);
  return realDir;
};

afterEach(() => {
  if (savedChannelDir === undefined) {
    Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  } else {
    process.env.CHANNEL_DIR = savedChannelDir;
  }
  savedChannelDir = undefined;
  resetConfig();
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

const request = (
  overrides: Partial<ChannelInitInput> = {}
): ChannelInitInput => ({
  context: "Study",
  force: false,
  genre: "ambient",
  name: "Demo Channel",
  short: "DEMO",
  style: "soft piano",
  ...overrides,
});

const runOk = async (
  input: ChannelInitInput,
  channelDir: string
): Promise<ChannelInitOutput> => {
  const result = await channelInitService(input, { channelDir });
  if (!result.ok) {
    throw new Error(
      `expected an ok Result, got error: ${JSON.stringify(result.error)}`
    );
  }
  return result.value;
};

const readJson = (path: string): Record<string, unknown> =>
  JSON.parse(readFileSync(path, "utf-8")) as Record<string, unknown>;

describe("channel-init public API — exports map", () => {
  test("should expose only service boundary runtime symbols", () => {
    expect(Object.keys(channelInitPublicApi).toSorted()).toEqual([
      "ChannelInitInputSchema",
      "ChannelInitOutputSchema",
      "channelInitService",
    ]);
  });
});

describe("channel.init registry deps — contract", () => {
  test("should require only channelDir from adapters", () => {
    expect(REGISTRY["channel.init"].deps).toEqual(["channelDir"]);
  });
});

describe("ChannelInitInputSchema — contract", () => {
  test("should require short and name while defaulting optional flags", () => {
    const parsed = ChannelInitInputSchema.parse({
      name: "Demo Channel",
      short: "DEMO",
    });

    expect(parsed).toEqual({
      context: "TBD",
      force: false,
      genre: "TBD",
      name: "Demo Channel",
      short: "DEMO",
      style: "TBD",
    });
  });

  test("should reject channelDir because channelDir is a registry dependency", () => {
    expect(() =>
      ChannelInitInputSchema.parse({
        channelDir: "/tmp/channel",
        name: "Demo Channel",
        short: "DEMO",
      })
    ).toThrow();
  });
});

describe("channelInitService — scaffold generation", () => {
  test("should create seven config files and canonical gitkeep directories", async () => {
    const channelDir = makeTempDir("channel-init-created-");

    const output = await runOk(request(), channelDir);

    for (const name of configFiles) {
      const path = join(channelDir, "config", "channel", name);
      expect(existsSync(path)).toBe(true);
      expect(readFileSync(path, "utf-8").endsWith("\n")).toBe(true);
    }
    for (const rel of gitkeepDirs) {
      expect(existsSync(join(channelDir, rel, ".gitkeep"))).toBe(true);
    }
    expect(output.files.map((action) => action.kind)).toEqual(
      configFiles.map(() => "created")
    );
    expect(output.directories.map((action) => action.kind)).toEqual(
      gitkeepDirs.map(() => "created")
    );
    expect(output.summary).toContain("  created     config/channel/meta.json");
    expect(output.summary).toContain("  created     docs/benchmarks/");
    expect(output.diff).toBe("");
  });

  test("should render input values into meta and content config", async () => {
    const channelDir = makeTempDir("channel-init-render-");

    await runOk(
      request({
        context: "RPG maps",
        genre: "chiptune",
        name: "Awesome BGM",
        short: "ABC-01",
        style: "8-bit",
      }),
      channelDir
    );

    const meta = readJson(join(channelDir, "config", "channel", "meta.json"));
    const content = readJson(
      join(channelDir, "config", "channel", "content.json")
    );
    expect(meta).toMatchObject({
      channel: { name: "Awesome BGM", short: "ABC-01" },
    });
    expect(content).toMatchObject({
      genre: { context: "RPG maps", primary: "chiptune", style: "8-bit" },
    });
  });

  test("should skip matching files and existing gitkeep directories on a second run", async () => {
    const channelDir = makeTempDir("channel-init-skipped-");
    await runOk(request(), channelDir);

    const output = await runOk(request(), channelDir);

    expect(output.files.map((action) => action.kind)).toEqual(
      configFiles.map(() => "skipped")
    );
    expect(output.directories.map((action) => action.kind)).toEqual(
      gitkeepDirs.map(() => "skipped")
    );
    expect(output.summary).toContain("  skipped     config/channel/meta.json");
    expect(output.diff).toBe("");
  });

  test("should not overwrite a mismatched existing file without force and should report a diff", async () => {
    const channelDir = makeTempDir("channel-init-diff-");
    const metaPath = join(channelDir, "config", "channel", "meta.json");
    mkdirSync(join(channelDir, "config", "channel"), { recursive: true });
    writeFileSync(metaPath, '{"channel":{"name":"Old","short":"OLD"}}\n');

    const output = await runOk(request({ name: "New" }), channelDir);

    expect(readFileSync(metaPath, "utf-8")).toBe(
      '{"channel":{"name":"Old","short":"OLD"}}\n'
    );
    expect(
      output.files.find((action) => action.rel.endsWith("meta.json"))
    ).toMatchObject({
      kind: "skipped",
      rel: "config/channel/meta.json",
    });
    expect(output.diff).toContain("--- config/channel/meta.json (existing)");
    expect(output.diff).toContain("+++ config/channel/meta.json (template)");
    expect(output.diff).toContain("@@ -1 +1,8 @@");
    expect(output.diff).toContain('name": "New"');
    expect(output.diff).not.toContain("-+{");
  });

  test("should overwrite a mismatched existing file with force and suppress diff output", async () => {
    const channelDir = makeTempDir("channel-init-force-");
    await runOk(request({ name: "Old Name" }), channelDir);

    const output = await runOk(
      request({ force: true, name: "New Name" }),
      channelDir
    );

    const meta = readJson(join(channelDir, "config", "channel", "meta.json"));
    expect(meta).toMatchObject({ channel: { name: "New Name" } });
    expect(
      output.files.find((action) => action.rel.endsWith("meta.json"))
    ).toMatchObject({
      kind: "overwritten",
      rel: "config/channel/meta.json",
    });
    expect(output.diff).toBe("");
  });

  test("should be loadable by the channel config loader after scaffolding", async () => {
    const channelDir = makeTempDir("channel-init-loader-");
    savedChannelDir = process.env.CHANNEL_DIR;
    process.env.CHANNEL_DIR = channelDir;
    resetConfig();

    await runOk(request(), channelDir);

    const config = loadConfig();
    expect(config.identity.meta.channelName).toBe("Demo Channel");
    expect(config.identity.meta.channelShort).toBe("DEMO");
    expect(config.integrations.analytics.benchmark.channels).toEqual([]);
  });
});

describe("channelInitService — target validation", () => {
  test("should return a ServiceError when the injected channelDir does not exist", async () => {
    const missing = join(
      makeTempDir("channel-init-missing-parent-"),
      "missing"
    );

    const result = await channelInitService(request(), { channelDir: missing });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain(missing);
    }
  });

  test("should reject blocked scaffold directories before writing files", async () => {
    const channelDir = makeTempDir("channel-init-blocked-dir-");
    const docsPath = join(channelDir, "docs");
    writeFileSync(docsPath, "not a directory\n");

    const result = await channelInitService(request(), { channelDir });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain(docsPath);
    }
    expect(existsSync(join(channelDir, "config", "channel", "meta.json"))).toBe(
      false
    );
    expect(existsSync(join(channelDir, "auth", ".gitkeep"))).toBe(false);
    expect(readFileSync(docsPath, "utf-8")).toBe("not a directory\n");
  });
});
