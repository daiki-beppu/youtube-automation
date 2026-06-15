// Tests for the DepsMap contract (ADR-0004 / #993). DepsMap goes from
// `Record<never, never>` to the real { config, yt, ytAnalytics } map so a
// registry entry can declare the heavy dependencies it needs and receive them —
// typed — as run()'s second argument, without loading config or touching the
// network. These pin two things:
//   1. the type shape: a full DepsMap literal compiles only with the three keys
//      mapped to ChannelConfig / YouTubeClient / YouTubeAnalyticsClient (enforced
//      by tsc; a regression to Record<never, never> fails the typecheck step).
//   2. the run pass-through: a fake entry with deps ['config', 'yt'] runs with
//      those fakes injected directly — the AC `entry.run(input, { config, yt })`.

import { describe, expect, test } from "bun:test";

import { ok } from "@youtube-automation/core";
import type { ChannelConfig } from "@youtube-automation/core/config";
import type {
  YouTubeAnalyticsClient,
  YouTubeClient,
} from "@youtube-automation/core/oauth/client";
import type { DepsMap, RegistryEntry } from "@youtube-automation/core/registry";
import { z } from "zod";

// Minimal hand-built stand-ins cast to their DepsMap types. The contract under
// test is the type wiring + run pass-through, not the internals of a real config
// or googleapis client, so fakes are injected directly (the AC: no reset() /
// loadConfig() needed for a service test).
const fakeConfig = {
  identity: { meta: { channelName: "Fake Channel" } },
} as unknown as ChannelConfig;
const fakeYt = { videos: {} } as unknown as YouTubeClient;
const fakeYtAnalytics = { reports: {} } as unknown as YouTubeAnalyticsClient;

describe("DepsMap — type shape", () => {
  test("maps config / yt / ytAnalytics to their config + googleapis types", () => {
    // Given a full DepsMap literal — this only type-checks once DepsMap carries
    // exactly these three keys (a regression to Record<never, never> would make
    // every property an excess-property type error at the typecheck step).
    const deps: DepsMap = {
      config: fakeConfig,
      yt: fakeYt,
      ytAnalytics: fakeYtAnalytics,
    };

    // Then each key is reachable with its declared type at runtime.
    expect(deps.config.identity.meta.channelName).toBe("Fake Channel");
    expect(typeof deps.yt.videos).toBe("object");
    expect(typeof deps.ytAnalytics.reports).toBe("object");
  });
});

describe("RegistryEntry — declared deps reach run, typed", () => {
  const InputSchema = z.object({ value: z.string() }).strict();
  const OutputSchema = z
    .object({
      channelName: z.string(),
      echoed: z.string(),
      hasVideos: z.boolean(),
    })
    .strict();

  // A throwaway entry that declares deps: ['config', 'yt']. Its run reads
  // deps.config (ChannelConfig) and deps.yt (YouTubeClient); both accesses only
  // type-check because DepsMap now maps those keys to real types, and run's deps
  // arg is the Pick<DepsMap, 'config' | 'yt'> slice (ytAnalytics is absent).
  const fakeEntry: RegistryEntry<
    typeof InputSchema,
    typeof OutputSchema,
    "config" | "yt"
  > = {
    deps: ["config", "yt"],
    description: "fake entry exercising the DepsMap contract",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    run: (input, deps) =>
      Promise.resolve(
        ok({
          channelName: deps.config.identity.meta.channelName,
          echoed: input.value,
          hasVideos: typeof deps.yt.videos === "object",
        })
      ),
  };

  test("run executes with { config, yt } injected and uses both deps", async () => {
    // Given an input parsed through the entry's own schema
    const input = fakeEntry.inputSchema.parse({ value: "hello" });

    // When run is called with the declared deps injected directly
    const result = await fakeEntry.run(input, {
      config: fakeConfig,
      yt: fakeYt,
    });

    // Then it returns an ok Result derived from the injected deps + input.
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.channelName).toBe("Fake Channel");
      expect(result.value.hasVideos).toBe(true);
      expect(result.value.echoed).toBe("hello");
    }
  });

  test("declares exactly its required deps (no ytAnalytics)", () => {
    // Given the entry's deps declaration
    // Then only the keys it consumes are listed — the compile-time mirror is
    // run's deps arg being Pick<DepsMap, 'config' | 'yt'>, free of ytAnalytics.
    expect(fakeEntry.deps).toEqual(["config", "yt"]);
    expect(fakeEntry.deps).not.toContain("ytAnalytics");
  });
});
