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
    const input = rawInput();

    const parsed = GenerateImageInput.parse(input);

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
    const input = { ...rawInput(), unexpected: true };

    expect(() => GenerateImageInput.parse(input)).toThrow();
  });

  test("rejects response envelopes passed as request input", () => {
    const input = { data: rawInput() };

    expect(() => GenerateImageInput.parse(input)).toThrow();
  });
});

describe("generateImageService input normalization", () => {
  test("passes a transformed snake_case request to the injected provider", async () => {
    const seen: ParsedGenerateImageInput[] = [];
    const provider: ImageProvider = {
      generate: (request) => {
        seen.push(request);
        return Promise.resolve(new Uint8Array([1, 2, 3]));
      },
      name: "fake",
      supportedAspectRatios: [],
    };

    const result = await generateImageService(
      rawInput() as unknown as ParsedGenerateImageInput,
      {
        persist: (outputPath) => Promise.resolve(outputPath),
        provider,
        sleep: () => Promise.resolve(),
      }
    );

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
