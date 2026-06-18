import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import * as finalizeMasterPublicApi from "@youtube-automation/core/finalize-master";
import {
  buildFinalizeFilter,
  FinalizeMasterInputSchema,
  parseLoudnormJson,
} from "@youtube-automation/core/finalize-master";
import { REGISTRY } from "@youtube-automation/core/registry";

const fixtureDir = resolve(import.meta.dir, "fixtures", "finalize-master");
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

const defaultLoudnorm = { I: -14, LRA: 11, TP: -1.5 };
const pass2Measured = {
  input_i: "-23.0",
  input_lra: "10.5",
  input_thresh: "-33.0",
  input_tp: "-2.1",
  target_offset: "0.5",
};

const readFixture = (name: string): string =>
  readFileSync(join(fixtureDir, name), "utf-8").trimEnd();

const readSource = (path: string): string =>
  readFileSync(join(repoRoot, path), "utf-8");

describe("finalize-master public API — exports map", () => {
  test("should expose service, schema, filter, parser, and config resolver", () => {
    expect(Object.keys(finalizeMasterPublicApi).toSorted()).toEqual([
      "FinalizeMasterInputSchema",
      "FinalizeMasterOutputSchema",
      "buildFinalizeFilter",
      "finalizeMasterService",
      "parseLoudnormJson",
      "resolveFinalizeConfig",
    ]);
  });
});

describe("finalize.master registry entry — contract", () => {
  test("should require only channelDir from adapters", () => {
    const entry = REGISTRY["finalize.master"];

    expect(entry.deps).toEqual(["channelDir"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("finalize-master implementation policy — mutation guard", () => {
  test("should not use array mutator calls in finalize-master implementation files", () => {
    const sourceByPath = {
      "packages/cli/src/commands/finalize-master/cli.ts": readSource(
        "packages/cli/src/commands/finalize-master/cli.ts"
      ),
      "packages/core/src/finalize-master/config.ts": readSource(
        "packages/core/src/finalize-master/config.ts"
      ),
      "packages/core/src/finalize-master/filter.ts": readSource(
        "packages/core/src/finalize-master/filter.ts"
      ),
      "packages/core/src/finalize-master/service.ts": readSource(
        "packages/core/src/finalize-master/service.ts"
      ),
      "packages/core/test/finalize-master-service.test.ts": readSource(
        "packages/core/test/finalize-master-service.test.ts"
      ),
    };

    expect(
      Object.fromEntries(
        Object.entries(sourceByPath).map(([path, source]) => [
          path,
          source.match(/\.(?:push|pop|splice|reverse|sort)\(/gu) ?? [],
        ])
      )
    ).toEqual({
      "packages/cli/src/commands/finalize-master/cli.ts": [],
      "packages/core/src/finalize-master/config.ts": [],
      "packages/core/src/finalize-master/filter.ts": [],
      "packages/core/src/finalize-master/service.ts": [],
      "packages/core/test/finalize-master-service.test.ts": [],
    });
  });
});

describe("FinalizeMasterInputSchema — contract", () => {
  test("should accept only the resolved collection directory", () => {
    const parsed = FinalizeMasterInputSchema.parse({
      collectionDir: "/tmp/channel/collections/planning/test",
    });

    expect(parsed).toEqual({
      collectionDir: "/tmp/channel/collections/planning/test",
    });
  });

  test("should reject omitted collectionDir because adapters resolve CWD", () => {
    expect(() => FinalizeMasterInputSchema.parse({})).toThrow();
  });

  test("should reject channelDir and quiet because they are not public input", () => {
    expect(() =>
      FinalizeMasterInputSchema.parse({
        channelDir: "/tmp/channel",
        collectionDir: "/tmp/channel/collections/planning/test",
      })
    ).toThrow();
    expect(() =>
      FinalizeMasterInputSchema.parse({
        collectionDir: "/tmp/channel/collections/planning/test",
        quiet: true,
      })
    ).toThrow();
  });
});

describe("buildFinalizeFilter — golden contract", () => {
  test("should match one-layer pass1 filter_complex", () => {
    const result = buildFinalizeFilter({
      applyLoudnorm: true,
      fadeinCurve: "tri",
      fadeinS: 0.5,
      layerCount: 1,
      layerOverrides: [null],
      loudnorm: defaultLoudnorm,
      measured: null,
      mixDuration: "first",
      mixNormalize: 0,
      volumeDb: -19,
    });

    expect(result).toBe(readFixture("filter-one-layer-pass1.txt"));
  });

  test("should match three-layer pass1 filter_complex", () => {
    const result = buildFinalizeFilter({
      applyLoudnorm: true,
      fadeinCurve: "tri",
      fadeinS: 0.5,
      layerCount: 3,
      layerOverrides: [null, null, null],
      loudnorm: defaultLoudnorm,
      measured: null,
      mixDuration: "first",
      mixNormalize: 0,
      volumeDb: -19,
    });

    expect(result).toBe(readFixture("filter-three-layer-pass1.txt"));
  });

  test("should inject pass1 measurements into pass2 filter_complex", () => {
    const result = buildFinalizeFilter({
      applyLoudnorm: true,
      fadeinCurve: "tri",
      fadeinS: 0.5,
      layerCount: 1,
      layerOverrides: [null],
      loudnorm: defaultLoudnorm,
      measured: pass2Measured,
      mixDuration: "first",
      mixNormalize: 0,
      volumeDb: -19,
    });

    expect(result).toBe(readFixture("filter-pass2.txt"));
  });

  test("should omit loudnorm stage in single-pass mode", () => {
    const result = buildFinalizeFilter({
      applyLoudnorm: false,
      fadeinCurve: "tri",
      fadeinS: 0.5,
      layerCount: 2,
      layerOverrides: [null, null],
      loudnorm: defaultLoudnorm,
      measured: null,
      mixDuration: "first",
      mixNormalize: 0,
      volumeDb: -19,
    });

    expect(result).toBe(readFixture("filter-single-pass.txt"));
    expect(result).not.toContain("loudnorm=");
  });

  test("should apply per-file layer overrides by layer order", () => {
    const result = buildFinalizeFilter({
      applyLoudnorm: true,
      fadeinCurve: "tri",
      fadeinS: 0.5,
      layerCount: 2,
      layerOverrides: [{ fadeinS: 2, volumeDb: -3.5 }, null],
      loudnorm: defaultLoudnorm,
      measured: null,
      mixDuration: "first",
      mixNormalize: 0,
      volumeDb: -19,
    });

    expect(result).toBe(readFixture("filter-per-file-override.txt"));
  });

  test("should propagate custom fade curve, mix, and loudnorm targets", () => {
    const result = buildFinalizeFilter({
      applyLoudnorm: true,
      fadeinCurve: "exp",
      fadeinS: 1.25,
      layerCount: 2,
      layerOverrides: [null, null],
      loudnorm: { I: -16, LRA: 8, TP: -2 },
      measured: null,
      mixDuration: "longest",
      mixNormalize: 1,
      volumeDb: -12.5,
    });

    expect(result).toBe(readFixture("filter-custom-curve-mix.txt"));
  });

  test("should fail loud when layerOverrides length mismatches layerCount", () => {
    expect(() =>
      buildFinalizeFilter({
        applyLoudnorm: true,
        fadeinCurve: "tri",
        fadeinS: 0.5,
        layerCount: 2,
        layerOverrides: [null],
        loudnorm: defaultLoudnorm,
        measured: null,
        mixDuration: "first",
        mixNormalize: 0,
        volumeDb: -19,
      })
    ).toThrow(/validation:.*layerOverrides/iu);
  });
});

describe("parseLoudnormJson — stderr parser", () => {
  test("should extract the last JSON object and stringify values", () => {
    const stderr = [
      "ffmpeg banner",
      '{"ignored": true}',
      '{"input_i": -23, "input_tp": -2.1, "input_lra": 10.5, "input_thresh": -33, "target_offset": 0.5}',
    ].join("\n");

    expect(parseLoudnormJson(stderr)).toEqual({
      input_i: "-23",
      input_lra: "10.5",
      input_thresh: "-33",
      input_tp: "-2.1",
      target_offset: "0.5",
    });
  });

  test("should ignore ffmpeg bracketed logs after the loudnorm JSON object", () => {
    const stderr = [
      "ffmpeg banner",
      '{"input_i": -23, "input_tp": -2.1, "input_lra": 10.5, "input_thresh": -33, "target_offset": 0.5}',
      "[out#0/null @ 0x600001] video:0KiB audio:0KiB subtitle:0KiB",
    ].join("\n");

    expect(parseLoudnormJson(stderr)).toEqual({
      input_i: "-23",
      input_lra: "10.5",
      input_thresh: "-33",
      input_tp: "-2.1",
      target_offset: "0.5",
    });
  });

  test("should reject stderr without a JSON object", () => {
    expect(() => parseLoudnormJson("ffmpeg failed silently")).toThrow(
      /validation:/iu
    );
  });

  test("should reject a non-object JSON payload", () => {
    expect(() => parseLoudnormJson("prefix\n[1, 2, 3]\n")).toThrow(
      /validation:.*object/iu
    );
  });
});
