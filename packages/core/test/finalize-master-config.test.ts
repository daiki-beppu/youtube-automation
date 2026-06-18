import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { resolveFinalizeConfig } from "@youtube-automation/core/finalize-master";
import type { FinalizeMasterConfigResult } from "@youtube-automation/core/finalize-master";

const fixtureDir = resolve(import.meta.dir, "fixtures", "finalize-master");

const readJsonFixture = (name: string): FinalizeMasterConfigResult =>
  JSON.parse(
    readFileSync(join(fixtureDir, name), "utf-8")
  ) as FinalizeMasterConfigResult;

describe("resolveFinalizeConfig — golden contract", () => {
  test("should resolve default config", () => {
    const result = resolveFinalizeConfig({});

    expect(result).toEqual(readJsonFixture("config-default.json"));
  });

  test("should resolve full audio.finalize override", () => {
    const raw = {
      audio: {
        bitrate: "256k",
        finalize: {
          ambient_layers: {
            dirname: "ambient",
            fadein_curve: "log",
            fadein_s: 1.5,
            glob: "amb_*.wav",
            layers: {
              "amb_001.wav": { fadein_s: 2, volume_db: -10 },
            },
            volume_db: -22.5,
          },
          bitrate: "320k",
          codec: "aac",
          loudnorm: { I: -16, LRA: 8, TP: -2, enabled: true, mode: "linear" },
          mix: { duration: "longest", normalize: 1 },
          sample_rate: 48_000,
        },
      },
    };

    const result = resolveFinalizeConfig(raw);

    expect(result).toEqual(readJsonFixture("config-full-override.json"));
  });

  test("should resolve legacy rain_layer alias with a structured warning", () => {
    const raw = {
      rain_layer: {
        fadein_s: 0.75,
        loudnorm: { I: -16.5, LRA: 9.5, TP: -2.5 },
        volume_db: -25.5,
      },
    };

    const result = resolveFinalizeConfig(raw);

    expect(result).toEqual(readJsonFixture("config-legacy-alias.json"));
  });

  test("should prefer audio.finalize over legacy rain_layer without warning", () => {
    const raw = {
      audio: { finalize: { ambient_layers: { volume_db: -10 } } },
      rain_layer: { volume_db: -25.5 },
    };

    const result = resolveFinalizeConfig(raw);

    expect(result).toEqual(readJsonFixture("config-new-priority.json"));
  });

  test("should ignore legacy rain_layer when any audio.finalize key exists", () => {
    const result = resolveFinalizeConfig({
      audio: { finalize: { mix: { duration: "longest" } } },
      rain_layer: {
        loudnorm: { I: -16.5 },
        volume_db: -25.5,
      },
    });

    expect(result.config.ambientLayers.volumeDb).toBe(-19);
    expect(result.config.loudnorm.I).toBe(-14);
    expect(result.config.mix.duration).toBe("longest");
    expect(result.warnings).toEqual([]);
  });
});

describe("resolveFinalizeConfig — fail loud branches", () => {
  test("should reject dynamic loudnorm mode as not implemented", () => {
    expect(() =>
      resolveFinalizeConfig({
        audio: { finalize: { loudnorm: { mode: "dynamic" } } },
      })
    ).toThrow(/config:.*dynamic.*not implemented/iu);
  });

  test("should reject invalid loudnorm mode", () => {
    expect(() =>
      resolveFinalizeConfig({
        audio: { finalize: { loudnorm: { mode: "garbage" } } },
      })
    ).toThrow(/config:.*loudnorm.*mode/iu);
  });

  test("should reject invalid mix duration", () => {
    expect(() =>
      resolveFinalizeConfig({
        audio: { finalize: { mix: { duration: "forever" } } },
      })
    ).toThrow(/config:.*mix.*duration/iu);
  });

  test("should reject invalid mix normalize", () => {
    expect(() =>
      resolveFinalizeConfig({
        audio: { finalize: { mix: { normalize: 2 } } },
      })
    ).toThrow(/config:.*mix.*normalize/iu);
  });

  test("should reject non-record layer overrides", () => {
    expect(() =>
      resolveFinalizeConfig({
        audio: { finalize: { ambient_layers: { layers: ["not-a-record"] } } },
      })
    ).toThrow(/config:.*layers/iu);
  });
});

describe("type contracts — compile-time smoke", () => {
  test("resolved config result type carries config and warnings", () => {
    const result: FinalizeMasterConfigResult = resolveFinalizeConfig({});

    expect(result.config.output.bitrate).toBe("192k");
    expect(result.warnings).toEqual([]);
  });
});
