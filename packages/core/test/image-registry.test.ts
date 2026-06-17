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
    // Given the public core registry consumed by CLI/MCP adapters
    const registry = REGISTRY as unknown as Record<
      string,
      RegistryEntryForTest
    >;

    // When resolving the image generation operation
    const entry = registry["image.generate"];

    // Then the entry declares the service contract and its provider dependency
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("image.generate registry entry is required");
    }
    expect(entry.deps).toEqual(["imageProvider"]);
    expect(entry.description.length).toBeGreaterThan(0);
    expect(entry.inputSchema).toBeDefined();
    expect(entry.outputSchema).toBeDefined();
  });

  test("parses snake_case input at the registry boundary", () => {
    // Given the registry entry that backs `tayk generate-image`
    const registry = REGISTRY as unknown as Record<
      string,
      RegistryEntryForTest
    >;
    const entry = registry["image.generate"];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("image.generate registry entry is required");
    }

    // When parsing the raw command/service input
    const parsed = entry.inputSchema.parse({
      aspect_ratio: "9:16",
      image_size: "2K",
      output_path: "out.png",
      prompt: "a vertical rainy city thumbnail",
    });

    // Then the registry passes normalized camelCase input to run()
    expect(parsed).toMatchObject({
      aspectRatio: "9:16",
      imageSize: "2K",
      outputPath: "out.png",
      prompt: "a vertical rainy city thumbnail",
    });
  });
});
