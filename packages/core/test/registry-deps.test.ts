import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  test,
} from "bun:test";

import { ok } from "@youtube-automation/core";
import { loadConfig, reset } from "@youtube-automation/core/config";
import type { ChannelConfig } from "@youtube-automation/core/config";
import type {
  YouTubeAnalyticsClient,
  YouTubeClient,
} from "@youtube-automation/core/oauth/client";
import * as registryModule from "@youtube-automation/core/registry";
import { REGISTRY } from "@youtube-automation/core/registry";
import type { DepsMap, RegistryEntry } from "@youtube-automation/core/registry";
import { z } from "zod";

import {
  cleanupChannels,
  minimalSections,
  restoreChannelDirEnv,
  saveChannelDirEnv,
  setupChannel,
} from "./config-fixtures.ts";

const fakeConfig = {
  identity: { meta: { channelName: "Fake Channel" } },
} as unknown as ChannelConfig;
const fakeYt = { videos: {} } as unknown as YouTubeClient;
const fakeYtAnalytics = { reports: {} } as unknown as YouTubeAnalyticsClient;
const fakeChannelDir = "/tmp/fake-channel";

beforeAll(saveChannelDirEnv);
afterAll(restoreChannelDirEnv);

beforeEach(() => {
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  reset();
});

afterEach(() => {
  reset();
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  cleanupChannels();
});

describe("DepsMap — type shape", () => {
  test("maps config / channelDir / yt / ytAnalytics to their declared types", () => {
    const deps: DepsMap = {
      channelDir: fakeChannelDir,
      config: fakeConfig,
      yt: fakeYt,
      ytAnalytics: fakeYtAnalytics,
    };

    expect(deps.channelDir).toBe(fakeChannelDir);
    expect(deps.config.identity.meta.channelName).toBe("Fake Channel");
    expect(typeof deps.yt.videos).toBe("object");
    expect(typeof deps.ytAnalytics.reports).toBe("object");
  });
});

describe("RegistryEntry — declared deps reach run, typed", () => {
  const InputSchema = z.object({ value: z.string() }).strict();
  const OutputSchema = z
    .object({
      channelDir: z.string(),
      channelName: z.string(),
      echoed: z.string(),
      hasVideos: z.boolean(),
    })
    .strict();

  const fakeEntry: RegistryEntry<
    typeof InputSchema,
    typeof OutputSchema,
    "channelDir" | "config" | "yt"
  > = {
    deps: ["config", "channelDir", "yt"],
    description: "fake entry exercising the DepsMap contract",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    run: (input, deps) =>
      Promise.resolve(
        ok({
          channelDir: deps.channelDir,
          channelName: deps.config.identity.meta.channelName,
          echoed: input.value,
          hasVideos: typeof deps.yt.videos === "object",
        })
      ),
  };

  test("run executes with { channelDir, config, yt } injected and uses each dep", async () => {
    const input = fakeEntry.inputSchema.parse({ value: "hello" });

    const result = await fakeEntry.run(input, {
      channelDir: fakeChannelDir,
      config: fakeConfig,
      yt: fakeYt,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.channelDir).toBe(fakeChannelDir);
      expect(result.value.channelName).toBe("Fake Channel");
      expect(result.value.hasVideos).toBe(true);
      expect(result.value.echoed).toBe("hello");
    }
  });

  test("declares exactly its required deps (no ytAnalytics)", () => {
    expect(fakeEntry.deps).toEqual(["config", "channelDir", "yt"]);
    expect(fakeEntry.deps).not.toContain("ytAnalytics");
  });
});

describe("REGISTRY — metadata.generate", () => {
  test("keeps service keys inside the registry data, not as public constants", () => {
    expect(Object.keys(registryModule)).not.toContain(
      "METADATA_GENERATE_REGISTRY_KEY"
    );
    expect(Object.keys(REGISTRY)).toContain("metadata.generate");
  });

  test("registers the metadata facade with only config dependency", () => {
    const entry = REGISTRY["metadata.generate"];

    expect(entry.deps).toEqual(["config"]);
    expect(entry.description).toBe(
      "コレクションの動画メタデータを一括生成する"
    );
    expect(
      entry.inputSchema.safeParse({
        theme: "Battle",
        tracks: [{ durationSeconds: 60, startSeconds: 0, title: "Intro" }],
      }).success
    ).toBe(true);
    expect(entry.outputSchema.safeParse({}).success).toBe(false);
  });

  test("runs the metadata facade through the registry entry", async () => {
    const channelDir = setupChannel(minimalSections());
    process.env.CHANNEL_DIR = channelDir;
    const config = loadConfig();
    const entry = REGISTRY["metadata.generate"];
    const input = entry.inputSchema.parse({
      theme: "Battle Royale",
      tracks: [
        { durationSeconds: 120, startSeconds: 0, title: "Song A" },
        { durationSeconds: 180, startSeconds: 120, title: "Song B" },
      ],
    });

    const result = await entry.run(input, { config });

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.title).toBe("Battle Royale - Study");
    expect(result.value.timestamps).toBe("00:00 Song A\n02:00 Song B");
    expect(result.value.tags).toContain("battle music");
  });
});
