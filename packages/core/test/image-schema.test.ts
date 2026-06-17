import { describe, expect, test } from "bun:test";

import {
  generateImageService,
  GenerateImageInput,
} from "@youtube-automation/core/image";
import type {
  GenerateImageInput as ParsedGenerateImageInput,
  ImageProvider,
} from "@youtube-automation/core/image";

const rawInput = () => ({
  aspect_ratio: "16:9",
  image_size: "2K",
  output_path: "collections/planning/demo/main.png",
  prompt: "a quiet desk with warm window light",
  references: ["references/a.png"],
});

describe("GenerateImageInput schema", () => {
  test("transforms snake_case request fields to the camelCase service shape", () => {
    // Given a CLI/API-shaped root request that uses snake_case field names
    const input = rawInput();

    // When the core schema parses the request
    const parsed = GenerateImageInput.parse(input);

    // Then providers receive the normalized camelCase shape
    expect(parsed).toEqual({
      aspectRatio: "16:9",
      imageSize: "2K",
      outputPath: "collections/planning/demo/main.png",
      prompt: "a quiet desk with warm window light",
      references: ["references/a.png"],
    });
    expect("output_path" in parsed).toBe(false);
  });

  test("rejects unknown request keys instead of silently dropping them", () => {
    // Given a root request with an unsupported key
    const input = { ...rawInput(), unexpected: true };

    // When parsing it
    // Then validation fails before the provider can observe ambiguous input
    expect(() => GenerateImageInput.parse(input)).toThrow();
  });

  test("rejects response envelopes passed as request input", () => {
    // Given a response-style envelope instead of the documented root request
    const input = { data: rawInput() };

    // When parsing it as an image generation request
    // Then the schema does not reinterpret envelope payloads as request fields
    expect(() => GenerateImageInput.parse(input)).toThrow();
  });
});

describe("generateImageService input normalization", () => {
  test("passes a transformed snake_case request to the injected provider", async () => {
    // Given a service call at the external boundary with snake_case input
    const seen: ParsedGenerateImageInput[] = [];
    const provider: ImageProvider = {
      generate: (request) => {
        seen.push(request);
        return Promise.resolve(new Uint8Array([1, 2, 3]));
      },
      name: "fake",
      supportedAspectRatios: [],
    };

    // When generating an image through the Result-returning service boundary
    const result = await generateImageService(
      rawInput() as unknown as ParsedGenerateImageInput,
      {
        persist: (outputPath) => Promise.resolve(outputPath),
        provider,
        sleep: () => Promise.resolve(),
      }
    );

    // Then the service succeeds and the provider only sees camelCase fields
    expect(result.ok).toBe(true);
    expect(seen).toEqual([
      {
        aspectRatio: "16:9",
        imageSize: "2K",
        outputPath: "collections/planning/demo/main.png",
        prompt: "a quiet desk with warm window light",
        references: ["references/a.png"],
      },
    ]);
  });
});
