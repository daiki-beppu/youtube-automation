import { describe, expect, test } from "bun:test";

import { ok } from "@youtube-automation/core";
import type { ChannelConfig } from "@youtube-automation/core/config";
import type { ImageProvider } from "@youtube-automation/core/image";
import type {
  YouTubeAnalyticsClient,
  YouTubeClient,
} from "@youtube-automation/core/oauth/client";
import type { DepsMap, RegistryEntry } from "@youtube-automation/core/registry";
import { z } from "zod";

const fakeConfig = {
  identity: { meta: { channelName: "Fake Channel" } },
} as unknown as ChannelConfig;
const fakeYt = { videos: {} } as unknown as YouTubeClient;
const fakeYtAnalytics = { reports: {} } as unknown as YouTubeAnalyticsClient;
const fakeChannelDir = "/tmp/fake-channel";
const fakeImageProvider = {
  generate: () => Promise.resolve(new Uint8Array([1])),
  name: "fake",
  supportedAspectRatios: [],
} satisfies ImageProvider;

describe("DepsMap — type shape", () => {
  test("maps config / channelDir / imageProvider / yt / ytAnalytics to their declared types", () => {
    const deps: DepsMap = {
      channelDir: fakeChannelDir,
      config: fakeConfig,
      imageProvider: fakeImageProvider,
      yt: fakeYt,
      ytAnalytics: fakeYtAnalytics,
    };

    expect(deps.channelDir).toBe(fakeChannelDir);
    expect(deps.config.identity.meta.channelName).toBe("Fake Channel");
    expect(deps.imageProvider.name).toBe("fake");
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
