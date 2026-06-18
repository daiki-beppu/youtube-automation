import { describe, expect, test } from "bun:test";
import {
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

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
    const channelDir = mkdtempSync(join(tmpdir(), "image-schema-"));
    mkdirSync(join(channelDir, "references"), { recursive: true });
    writeFileSync(
      join(channelDir, "references", "a.png"),
      new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    );
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
        channelDir,
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
        outputPath: join(
          realpathSync(channelDir),
          "collections/planning/demo/main.png"
        ),
        prompt: "a quiet desk with warm window light",
        references: [join(realpathSync(channelDir), "references/a.png")],
      },
    ]);
    rmSync(channelDir, { force: true, recursive: true });
  });
});

describe("generateImageService path validation", () => {
  const pngBytes = new Uint8Array([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  ]);

  const makeChannel = (): string => {
    const channelDir = mkdtempSync(join(tmpdir(), "image-paths-"));
    mkdirSync(join(channelDir, "collections/planning/demo"), {
      recursive: true,
    });
    mkdirSync(join(channelDir, "references"), { recursive: true });
    writeFileSync(join(channelDir, "references", "ok.png"), pngBytes);
    return channelDir;
  };

  const callService = async (
    channelDir: string,
    input: Partial<ParsedGenerateImageInput>
  ) => {
    let calls = 0;
    const provider: ImageProvider = {
      generate: () => {
        calls += 1;
        return Promise.resolve(pngBytes);
      },
      name: "fake",
      supportedAspectRatios: [],
    };
    const result = await generateImageService(
      {
        aspectRatio: "16:9",
        imageSize: "2K",
        outputPath: "collections/planning/demo/main.png",
        prompt: "a quiet desk with warm window light",
        ...input,
      },
      {
        channelDir,
        persist: (outputPath) => Promise.resolve(outputPath),
        provider,
        sleep: () => Promise.resolve(),
      }
    );
    return { calls, result };
  };

  test("rejects absolute output paths before provider execution", async () => {
    const channelDir = makeChannel();

    const { calls, result } = await callService(channelDir, {
      outputPath: join(channelDir, "collections/planning/demo/main.png"),
    });

    expect(result.ok).toBe(false);
    expect(calls).toBe(0);
    rmSync(channelDir, { force: true, recursive: true });
  });

  test("rejects traversal output paths before provider execution", async () => {
    const channelDir = makeChannel();

    const { calls, result } = await callService(channelDir, {
      outputPath: "collections/../outside.png",
    });

    expect(result.ok).toBe(false);
    expect(calls).toBe(0);
    rmSync(channelDir, { force: true, recursive: true });
  });

  test("rejects reference files that are not images", async () => {
    const channelDir = makeChannel();
    writeFileSync(join(channelDir, "references", "secret.png"), "not image");

    const { calls, result } = await callService(channelDir, {
      references: ["references/secret.png"],
    });

    expect(result.ok).toBe(false);
    expect(calls).toBe(0);
    rmSync(channelDir, { force: true, recursive: true });
  });

  test("rejects symlinked output targets", async () => {
    const channelDir = makeChannel();
    const outside = mkdtempSync(join(tmpdir(), "image-outside-"));
    symlinkSync(
      join(outside, "escape.png"),
      join(channelDir, "collections/planning/demo/link.png")
    );

    const { calls, result } = await callService(channelDir, {
      outputPath: "collections/planning/demo/link.png",
    });

    expect(result.ok).toBe(false);
    expect(calls).toBe(0);
    rmSync(channelDir, { force: true, recursive: true });
    rmSync(outside, { force: true, recursive: true });
  });
});
