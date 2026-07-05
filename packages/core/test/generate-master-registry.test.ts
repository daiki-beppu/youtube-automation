import { describe, expect, test } from "bun:test";

import { REGISTRY } from "@youtube-automation/core/registry";

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
});
