import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";

import {
  generateMasterService,
  GenerateMasterInputSchema,
} from "@youtube-automation/core/generate-master";

import {
  inputFilesInCommand,
  installFakeFfmpeg,
  makeTempRoot,
  readFfmpegCalls,
  restoreGenerateMasterFixtures,
  saveGenerateMasterEnv,
  setupCollection,
} from "./generate-master-fixtures.ts";

const runOk = async (rawInput: unknown) => {
  const input = GenerateMasterInputSchema.parse(rawInput);
  const result = await generateMasterService(input);
  if (!result.ok) {
    throw new Error(`expected ok Result, got ${JSON.stringify(result.error)}`);
  }
  return result.value;
};

beforeEach(saveGenerateMasterEnv);
afterEach(restoreGenerateMasterFixtures);

describe("generateMasterService — audio collection and ffmpeg command", () => {
  test("collects mp3, m4a, and wav inputs sorted by filename", async () => {
    // Given a CHANNEL_DIR-relative collection with mixed supported audio files
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "02-beta.wav",
      "01-alpha.m4a",
      "03-gamma.mp3",
    ]);
    const logPath = installFakeFfmpeg();

    // When the service generates a master
    const output = await runOk({
      bitrate: "256k",
      channel_dir: channelRoot,
      collection: "collections/demo",
      crossfade_duration: 1.5,
    });

    // Then ffmpeg receives all supported files in sorted order.
    const [args] = readFfmpegCalls(logPath);
    expect(args).toBeDefined();
    expect(
      inputFilesInCommand(args ?? []).map((path) => basename(path))
    ).toEqual(["01-alpha.m4a", "02-beta.wav", "03-gamma.mp3"]);
    expect(args).toContain("-filter_complex");
    const expectedFilter = [
      "[0:a][1:a]acrossfade=d=1.5:c1=tri:c2=tri[cf1]",
      "[cf1][2:a]acrossfade=d=1.5:c1=tri:c2=tri[aout]",
    ].join(";");
    expect(args).toContain(expectedFilter);
    expect(args).toContain("libmp3lame");
    expect(args).toContain("256k");
    expect(output.bitrate).toBe("256k");
    expect(output.crossfadeDuration).toBe(1.5);
    expect(output.inputCount).toBe(3);
    expect(output.loopCount).toBe(1);
    expect(output.segmentCount).toBe(3);
    expect(output.outputPath).toBe(
      join(channelRoot, "collections/demo", "01-master", "master.mp3")
    );
  });

  test("copies a single mp3 without invoking ffmpeg", async () => {
    // Given one mp3 input
    const channelRoot = makeTempRoot("generate-master-channel-");
    const collection = setupCollection(channelRoot, "collections/demo", [
      "01-only.mp3",
    ]);
    const logPath = installFakeFfmpeg();

    // When mastering runs
    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    // Then the existing copy fast path is preserved.
    expect(readFfmpegCalls(logPath)).toEqual([]);
    expect(output.segmentCount).toBe(1);
    expect(output.outputPath).toBe(join(collection, "01-master", "master.mp3"));
    expect(readFileSync(output.outputPath, "utf-8")).toBe("audio:01-only.mp3");
  });

  test("transcodes a single non-mp3 input to master.mp3", async () => {
    // Given one wav input
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-only.wav"]);
    const logPath = installFakeFfmpeg();

    // When mastering runs
    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    // Then ffmpeg runs without a crossfade filter and writes master.mp3.
    const [args] = readFfmpegCalls(logPath);
    expect(
      inputFilesInCommand(args ?? []).map((path) => basename(path))
    ).toEqual(["01-only.wav"]);
    expect(args).not.toContain("-filter_complex");
    expect(output.outputPath.endsWith("/01-master/master.mp3")).toBe(true);
    expect(existsSync(output.outputPath)).toBe(true);
  });
});

describe("generateMasterService — pin, shuffle, and loop ordering", () => {
  test("pins before shuffle and repeats the resolved order for each loop", async () => {
    // Given sorted tracks, one pinned first track, shuffle, and two loops
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
      "03-c.mp3",
      "04-d.mp3",
    ]);
    const logPath = installFakeFfmpeg();

    // When mastering runs twice with the same seed
    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
      loop: 2,
      pin_first_count: 1,
      shuffle: true,
      shuffle_seed: 42,
    });
    await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
      loop: 2,
      pin_first_count: 1,
      shuffle: true,
      shuffle_seed: 42,
    });

    // Then both calls use the same resolved order, and each loop starts with
    // the pinned first track rather than shuffling per loop.
    const [firstCall, secondCall] = readFfmpegCalls(logPath).map((args) =>
      inputFilesInCommand(args).map((path) => basename(path))
    );
    expect(firstCall).toEqual(secondCall);
    expect(firstCall?.length).toBe(8);
    expect(firstCall?.slice(0, 4)).toEqual(firstCall?.slice(4, 8));
    expect(firstCall?.[0]).toBe("01-a.mp3");
    expect(firstCall?.[4]).toBe("01-a.mp3");
    expect(output.loopCount).toBe(2);
    expect(output.segmentCount).toBe(8);
    expect(output.messages).toContain("[Shuffle] seed=42");
    expect(output.messages.some((line) => line.includes("[Pin]"))).toBe(true);
  });
});
