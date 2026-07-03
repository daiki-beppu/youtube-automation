import { describe, expect, test } from "bun:test";

import { REGISTRY } from "@youtube-automation/core/registry";

describe("core registry — masterup.generate-master entry", () => {
  test("is registered under a dotted key with channelDir dependency", () => {
    // Given the core registry
    const entry = REGISTRY["masterup.generate-master"];

    // Then the generate-master service is visible to CLI/MCP adapters and
    // receives channel root resolution through the registry boundary.
    expect(entry).toBeDefined();
    expect(entry.deps).toEqual(["channelDir"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });

  test("parses snake_case input through its own schema and returns a Result", async () => {
    // Given invalid input parsed through the registry entry
    const entry = REGISTRY["masterup.generate-master"];
    const input = entry.inputSchema.parse({
      collection: "/tmp/does-not-exist",
      crossfade_duration: 1,
    });

    // When run is called with its declared deps
    const result = await entry.run(input, { channelDir: "/tmp/channel" });

    // Then the service boundary returns Result.err rather than throwing.
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
    }
  });
});
