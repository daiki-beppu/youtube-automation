import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { basename, join } from "node:path";

import { REGISTRY } from "@youtube-automation/core/registry";

import {
  inputFilesInCommand,
  installFakeFfmpeg,
  readFfmpegCalls,
  restoreGenerateMasterFixtures,
  saveGenerateMasterEnv,
  setupCollection,
  writeText,
  makeTempRoot,
} from "./generate-master-fixtures.ts";

beforeEach(saveGenerateMasterEnv);
afterEach(restoreGenerateMasterFixtures);

describe("core registry — masterup.generate-master entry", () => {
  test("is registered under a dotted key with channelDir dependency", () => {
    const entry = REGISTRY["masterup.generate-master"];
    // receives channel root resolution through the registry boundary.
    expect(entry).toBeDefined();
    expect(entry.deps).toEqual(["channelDir"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });

  test("parses snake_case input through its own schema and returns a Result", async () => {
    const entry = REGISTRY["masterup.generate-master"];
    const input = entry.inputSchema.parse({
      collection: "/tmp/does-not-exist",
      crossfade_duration: 1,
    });
    const result = await entry.run(input, { channelDir: "/tmp/channel" });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
    }
  });

  test("keeps explicit parsed input ahead of masterup config overrides", async () => {
    const channelRoot = makeTempRoot("generate-master-registry-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({
        audio: { bitrate: "320k", crossfade_duration: 2 },
      })
    );
    const logPath = installFakeFfmpeg();
    const entry = REGISTRY["masterup.generate-master"];

    const input = entry.inputSchema.parse({
      bitrate: "192k",
      collection: "collections/demo",
      crossfade_duration: 1,
    });
    const result = await entry.run(input, { channelDir: channelRoot });

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(
        `expected ok Result, got ${JSON.stringify(result.error)}`
      );
    }
    expect(result.value.bitrate).toBe("192k");
    expect(result.value.crossfadeDuration).toBe(1);
    const [args] = readFfmpegCalls(logPath);
    expect(args).toContain("192k");
    expect(args).toContain("[0:a][1:a]acrossfade=d=1:c1=tri:c2=tri[aout]");
    expect(
      inputFilesInCommand(args ?? []).map((path) => basename(path))
    ).toEqual(["01-a.mp3", "02-b.mp3"]);
  });
});
