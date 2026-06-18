import { describe, expect, test } from "bun:test";

import { REGISTRY } from "@youtube-automation/core/registry";

interface RegistryEntryForTest {
  readonly deps: readonly string[];
  readonly description: string;
  readonly inputSchema: { parse(input: unknown): unknown };
  readonly outputSchema: unknown;
}

describe("core registry — image.generate", () => {
  test("exposes image generation through a dotted registry entry", () => {
    const registry = REGISTRY as unknown as Record<
      string,
      RegistryEntryForTest
    >;

    const entry = registry["image.generate"];

    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("image.generate registry entry is required");
    }
    expect(entry.deps).toEqual(["channelDir", "imageProvider"]);
    expect(entry.description.length).toBeGreaterThan(0);
    expect(entry.inputSchema).toBeDefined();
    expect(entry.outputSchema).toBeDefined();
  });

  test("parses snake_case input at the registry boundary", () => {
    const registry = REGISTRY as unknown as Record<
      string,
      RegistryEntryForTest
    >;
    const entry = registry["image.generate"];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("image.generate registry entry is required");
    }

    const parsed = entry.inputSchema.parse({
      aspect_ratio: "9:16",
      image_size: "2K",
      output_path: "out.png",
      prompt: "a vertical rainy city thumbnail",
    });

    expect(parsed).toMatchObject({
      aspectRatio: "9:16",
      imageSize: "2K",
      outputPath: "out.png",
      prompt: "a vertical rainy city thumbnail",
    });
  });
});
