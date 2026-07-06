import { describe, expect, test } from "bun:test";

import {
  GenerateMasterInputSchema,
  GenerateMasterOutputSchema,
  GenerateMasterServiceInputSchema,
} from "@youtube-automation/core/generate-master";

describe("GenerateMasterInputSchema — snake_case input contract", () => {
  test("transforms snake_case CLI/config input into camelCase service input", () => {
    const parsed = GenerateMasterInputSchema.parse({
      bitrate: "256k",
      channel_dir: "/tmp/channel",
      collection: "collections/demo",
      crossfade_duration: 1.5,
      no_loop: false,
      pin_first: ["03-track.mp3", "01-track.mp3"],
      pin_first_count: undefined,
      shuffle_seed: 0,
      target_duration_min: 120,
    });
    expect(parsed.bitrate).toBe("256k");
    expect(parsed.channelDir).toBe("/tmp/channel");
    expect(parsed.collection).toBe("collections/demo");
    expect(parsed.crossfadeDuration).toBe(1.5);
    expect(parsed.noLoop).toBe(false);
    expect(parsed.pinFirst).toEqual(["03-track.mp3", "01-track.mp3"]);
    expect(parsed.shuffleSeed).toBe(0);
    expect(parsed.targetDurationMin).toBe(120);
    expect(parsed.specified.bitrate).toBe(true);
    expect(parsed.specified.crossfadeDuration).toBe(true);
    expect(parsed.specified.pinFirstCount).toBe(true);
    expect(parsed.specified.shuffleSeed).toBe(true);
    expect(parsed.specified.targetDurationMin).toBe(true);
  });

  test("declares runtime defaults in zod, not a config.default file", () => {
    const parsed = GenerateMasterInputSchema.parse({
      collection: "collections/demo",
    });
    expect(parsed.crossfadeDuration).toBe(1);
    expect(parsed.bitrate).toBe("192k");
    expect(parsed.loop).toBeUndefined();
    expect(parsed.noLoop).toBe(false);
    expect(parsed.pinFirst).toEqual([]);
    expect(parsed.pinFirstCount).toBeUndefined();
    expect(parsed.shuffle).toBe(false);
    expect(parsed.shuffleSeed).toBeUndefined();
    expect(parsed.targetDurationMin).toBeUndefined();
  });

  test("service input schema preserves explicit field presence for config overrides", () => {
    const parsed = GenerateMasterServiceInputSchema.parse({
      bitrate: "256k",
      collection: "collections/demo",
      crossfade_duration: 1.5,
      shuffle_seed: 0,
    });

    expect(parsed.bitrate).toBe("256k");
    expect(parsed.crossfadeDuration).toBe(1.5);
    expect(parsed.shuffleSeed).toBe(0);
    expect(parsed.specified.bitrate).toBe(true);
    expect(parsed.specified.crossfadeDuration).toBe(true);
    expect(parsed.specified.shuffleSeed).toBe(true);
    expect(parsed.specified.shuffle).toBe(false);
    expect(parsed.specified.targetDurationMin).toBe(false);
  });

  test("rejects blank bitrate values", () => {
    for (const bitrate of ["", "   "]) {
      expect(() =>
        GenerateMasterInputSchema.parse({
          bitrate,
          collection: "collections/demo",
        })
      ).toThrow();
      expect(() =>
        GenerateMasterServiceInputSchema.parse({
          bitrate,
          collection: "collections/demo",
        })
      ).toThrow();
    }
  });

  test("rejects blank channel_dir values", () => {
    for (const channelDir of ["", "   "]) {
      expect(() =>
        GenerateMasterInputSchema.parse({
          channel_dir: channelDir,
          collection: "/tmp/collection",
        })
      ).toThrow();
      expect(() =>
        GenerateMasterServiceInputSchema.parse({
          channelDir,
          collection: "/tmp/collection",
        })
      ).toThrow();
    }
  });

  test("rejects unknown keys instead of silently dropping them", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/demo",
        extra: true,
      })
    ).toThrow();
  });
});

describe("GenerateMasterInputSchema — validation boundaries", () => {
  test("rejects loop and target_duration_min together", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/demo",
        loop: 2,
        target_duration_min: 120,
      })
    ).toThrow();
  });

  test("rejects no_loop and target_duration_min together", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/demo",
        no_loop: true,
        target_duration_min: 120,
      })
    ).toThrow();
  });

  test("rejects pin_first and pin_first_count together", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/demo",
        pin_first: ["01-track.mp3"],
        pin_first_count: 1,
      })
    ).toThrow();
  });

  test("rejects non-positive loop and target duration values", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/demo",
        loop: 0,
      })
    ).toThrow();
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/demo",
        target_duration_min: 0,
      })
    ).toThrow();
  });

  test("rejects negative pin_first_count", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/demo",
        pin_first_count: -1,
      })
    ).toThrow();
  });
});

describe("GenerateMasterOutputSchema — service output contract", () => {
  test("accepts the machine-readable mastering summary", () => {
    const parsed = GenerateMasterOutputSchema.parse({
      bitrate: "192k",
      crossfadeDuration: 1,
      inputCount: 3,
      loopCount: 2,
      messages: ["[Shuffle] seed=42"],
      outputPath: "/tmp/channel/collections/demo/01-master/master.mp3",
      segmentCount: 6,
    });

    expect(parsed.outputPath.endsWith("/01-master/master.mp3")).toBe(true);
    expect(parsed.segmentCount).toBe(6);
    expect(parsed.messages).toEqual(["[Shuffle] seed=42"]);
  });

  test("rejects unknown output keys", () => {
    expect(() =>
      GenerateMasterOutputSchema.parse({
        bitrate: "192k",
        crossfadeDuration: 1,
        extra: true,
        inputCount: 1,
        loopCount: 1,
        messages: [],
        outputPath: "/tmp/master.mp3",
        segmentCount: 1,
      })
    ).toThrow();
  });
});
