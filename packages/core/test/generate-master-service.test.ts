import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
} from "node:fs";
import { basename, dirname, join } from "node:path";

import {
  generateMasterService,
  GenerateMasterInputSchema,
} from "@youtube-automation/core/generate-master";

import {
  inputFilesInCommand,
  installFakeFfmpeg,
  installFakeFfprobe,
  makeTempRoot,
  readFfmpegCalls,
  readFfprobeCalls,
  restoreGenerateMasterFixtures,
  saveGenerateMasterEnv,
  setupCollection,
  writeText,
} from "./generate-master-fixtures.ts";

const runOk = async (rawInput: unknown) => {
  const result = await generateMasterService(rawInput);
  if (!result.ok) {
    throw new Error(`expected ok Result, got ${JSON.stringify(result.error)}`);
  }
  return result.value;
};

beforeEach(saveGenerateMasterEnv);
afterEach(restoreGenerateMasterFixtures);

describe("generateMasterService — audio collection and ffmpeg command", () => {
  test("collects mp3, m4a, and wav inputs sorted by filename", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "02-beta.wav",
      "01-alpha.m4a",
      "03-gamma.mp3",
    ]);
    const logPath = installFakeFfmpeg();
    const output = await runOk({
      bitrate: "256k",
      channel_dir: channelRoot,
      collection: "collections/demo",
      crossfade_duration: 1.5,
    });
    const [args] = readFfmpegCalls(logPath);
    expect(args).toBeDefined();
    expect(
      inputFilesInCommand(args ?? []).map((path) => basename(path))
    ).toEqual(["01-alpha.m4a", "02-beta.wav", "03-gamma.mp3"]);
    expect(args).toContain("-filter_complex");
    expect(args).toContain("-b:a");
    expect(args).not.toContain("-q:a");
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
    const channelRoot = makeTempRoot("generate-master-channel-");
    const collection = setupCollection(channelRoot, "collections/demo", [
      "01-only.mp3",
    ]);
    const logPath = installFakeFfmpeg();
    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });
    expect(readFfmpegCalls(logPath)).toEqual([]);
    expect(output.segmentCount).toBe(1);
    expect(output.outputPath).toBe(join(collection, "01-master", "master.mp3"));
    expect(readFileSync(output.outputPath, "utf-8")).toBe("audio:01-only.mp3");
  });

  test("transcodes a single non-mp3 input to master.mp3", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-only.wav"]);
    const logPath = installFakeFfmpeg();
    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });
    const [args] = readFfmpegCalls(logPath);
    expect(
      inputFilesInCommand(args ?? []).map((path) => basename(path))
    ).toEqual(["01-only.wav"]);
    expect(args).not.toContain("-filter_complex");
    expect(args).toContain("-b:a");
    expect(args).not.toContain("-q:a");
    expect(output.outputPath.endsWith("/01-master/master.mp3")).toBe(true);
    expect(existsSync(output.outputPath)).toBe(true);
  });
});

describe("generateMasterService — pin, shuffle, and loop ordering", () => {
  test("reports explicit pinned file names", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-hook.mp3",
      "03-c.mp3",
    ]);
    installFakeFfmpeg();

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
      pin_first: ["02-hook.mp3"],
    });

    expect(output.messages).toContain(
      '[Pin] first 1 track(s) fixed: ["02-hook.mp3"]'
    );
  });

  test("pins before shuffle and repeats the resolved order for each loop", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
      "03-c.mp3",
      "04-d.mp3",
    ]);
    const logPath = installFakeFfmpeg();
    installFakeFfprobe({
      "01-a.mp3": 30,
      "02-b.mp3": 30,
      "03-c.mp3": 30,
      "04-d.mp3": 30,
    });
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
    expect(output.messages).toContain(
      '[Pin] first 1 track(s) fixed: ["01-a.mp3"]'
    );
  });

  test("does not shuffle when config only provides shuffle_seed", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
      "03-c.mp3",
    ]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { shuffle_seed: 42 } })
    );
    const logPath = installFakeFfmpeg();

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    const [args] = readFfmpegCalls(logPath);
    expect(
      inputFilesInCommand(args ?? []).map((path) => basename(path))
    ).toEqual(["01-a.mp3", "02-b.mp3", "03-c.mp3"]);
    expect(output.messages).not.toContain("[Shuffle] seed=42");
  });

  test("uses config shuffle_seed when config enables shuffle", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
      "03-c.mp3",
    ]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { shuffle: true, shuffle_seed: 42 } })
    );
    const logPath = installFakeFfmpeg();

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    const [args] = readFfmpegCalls(logPath);
    expect(
      inputFilesInCommand(args ?? []).map((path) => basename(path))
    ).not.toEqual(["01-a.mp3", "02-b.mp3", "03-c.mp3"]);
    expect(output.messages).toContain("[Shuffle] seed=42");
  });

  test("keeps public parsed camelCase input ahead of config overrides", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { bitrate: "320k", crossfade_duration: 2.5 } })
    );
    const logPath = installFakeFfmpeg();

    const input = GenerateMasterInputSchema.parse({
      bitrate: "192k",
      collection: "collections/demo",
      crossfade_duration: 1,
    });
    const result = await generateMasterService(input, {
      channelDir: channelRoot,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(
        `expected ok Result, got ${JSON.stringify(result.error)}`
      );
    }
    const [args] = readFfmpegCalls(logPath);
    expect(args).toContain("192k");
    expect(args).toContain("[0:a][1:a]acrossfade=d=1:c1=tri:c2=tri[aout]");
    expect(result.value.bitrate).toBe("192k");
    expect(result.value.crossfadeDuration).toBe(1);
  });
});

describe("generateMasterService — target duration probing", () => {
  test("calculates loop count from ffprobe durations for target_duration_min", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["-dash.mp3", "02-b.mp3"]);
    const ffmpegLog = installFakeFfmpeg();
    const ffprobeLog = installFakeFfprobe({
      "-dash.mp3": 30,
      "02-b.mp3": 30,
    });

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
      target_duration_min: 3,
    });

    const [args] = readFfmpegCalls(ffmpegLog);
    expect(output.loopCount).toBe(4);
    expect(output.segmentCount).toBe(8);
    expect(inputFilesInCommand(args ?? [])).toHaveLength(8);
    const probeCalls = readFfprobeCalls(ffprobeLog);
    expect(probeCalls).toHaveLength(2);
    for (const probeArgs of probeCalls) {
      expect(probeArgs.at(-2)).toBe("--");
    }
  });

  test("accounts for every segment crossfade when calculating target loops", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
      "03-c.mp3",
      "04-d.mp3",
    ]);
    installFakeFfmpeg();
    installFakeFfprobe({
      "01-a.mp3": 45,
      "02-b.mp3": 45,
      "03-c.mp3": 45,
      "04-d.mp3": 45,
    });

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
      crossfade_duration: 30,
      target_duration_min: 5,
    });

    expect(output.loopCount).toBe(5);
    expect(output.segmentCount).toBe(20);
    expect(output.durationPreview?.estimatedSeconds).toBe(330);
  });

  test("uses config target_duration_min when loop and no_loop are absent", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { target_duration_min: 3 } })
    );
    const ffmpegLog = installFakeFfmpeg();
    const ffprobeLog = installFakeFfprobe({
      "01-a.mp3": 30,
      "02-b.mp3": 30,
    });

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(output.loopCount).toBe(4);
    expect(readFfmpegCalls(ffmpegLog)).toHaveLength(1);
    expect(readFfprobeCalls(ffprobeLog)).toHaveLength(2);
  });

  test("ignores config target_duration_min when no_loop is explicit", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { target_duration_min: 3 } })
    );
    const ffmpegLog = installFakeFfmpeg();
    const ffprobeLog = installFakeFfprobe({
      "01-a.mp3": 30,
      "02-b.mp3": 30,
    });

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
      no_loop: true,
    });

    const [args] = readFfmpegCalls(ffmpegLog);
    expect(output.loopCount).toBe(1);
    expect(output.segmentCount).toBe(2);
    expect(output.durationPreview?.targetSeconds).toBeUndefined();
    expect(inputFilesInCommand(args ?? [])).toHaveLength(2);
    expect(readFfprobeCalls(ffprobeLog)).toHaveLength(2);
  });

  test("does not probe config target_duration_min when explicit loop wins", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { target_duration_min: 3 } })
    );
    installFakeFfmpeg();
    const ffprobeLog = installFakeFfprobe({
      "01-a.mp3": 30,
      "02-b.mp3": 30,
    });

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
      loop: 2,
    });

    expect(output.loopCount).toBe(2);
    expect(readFfprobeCalls(ffprobeLog)).toHaveLength(2);
  });

  test("returns validation error and does not run ffmpeg when ffprobe fails", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    const ffmpegLog = installFakeFfmpeg();
    installFakeFfprobe({}, 42);

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
      target_duration_min: 3,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("failed to probe");
    }
    expect(readFfmpegCalls(ffmpegLog)).toEqual([]);
  });

  test("returns validation error and does not run ffmpeg when ffprobe is missing", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    const ffmpegLog = installFakeFfmpeg();
    process.env.PATH = dirname(ffmpegLog);

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
      target_duration_min: 3,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("ffprobe not found");
    }
    expect(readFfmpegCalls(ffmpegLog)).toEqual([]);
  });
});

describe("generateMasterService — filesystem safety and output errors", () => {
  test("rejects channel-dir-relative collection paths that escape the channel root", async () => {
    const parent = makeTempRoot("generate-master-parent-");
    const channelRoot = join(parent, "channel");
    mkdirSync(channelRoot, { recursive: true });
    const outsideCollection = setupCollection(parent, "victim", [
      "01-outside.mp3",
    ]);
    const ffmpegLog = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "../victim",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("collection escapes channel_dir");
    }
    expect(readFfmpegCalls(ffmpegLog)).toEqual([]);
    expect(existsSync(join(outsideCollection, "01-master", "master.mp3"))).toBe(
      false
    );
  });

  test("surfaces channel root inspection errors instead of treating them as not found", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    const collection = setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
    ]);
    mkdirSync(join(channelRoot, "config"), { recursive: true });
    symlinkSync("channel", join(channelRoot, "config", "channel"), "dir");
    const ffmpegLog = installFakeFfmpeg();

    const result = await generateMasterService({
      collection,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("io");
      expect(result.error.message).toContain("failed to inspect channel root");
    }
    expect(readFfmpegCalls(ffmpegLog)).toEqual([]);
  });

  test("rejects parsed-like invalid input at the service boundary", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3"]);
    const ffmpegLog = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
      crossfade_duration: -1,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
    }
    expect(readFfmpegCalls(ffmpegLog)).toEqual([]);
  });

  test("rejects symlink audio inputs before ffmpeg", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    const collection = setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
    ]);
    const outside = join(channelRoot, "outside.mp3");
    writeText(outside, "outside");
    symlinkSync(
      outside,
      join(collection, "02-Individual-music", "02-link.mp3")
    );
    const ffmpegLog = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("unsafe audio input");
    }
    expect(readFfmpegCalls(ffmpegLog)).toEqual([]);
  });

  test("rejects symlink audio directory before scanning entries", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    const collection = setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
    ]);
    const outside = join(channelRoot, "outside-music");
    mkdirSync(outside, { recursive: true });
    writeText(join(outside, "01-outside.mp3"), "outside");
    rmSync(join(collection, "02-Individual-music"), {
      force: true,
      recursive: true,
    });
    symlinkSync(outside, join(collection, "02-Individual-music"), "dir");
    const ffmpegLog = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("unsafe audio directory");
    }
    expect(readFfmpegCalls(ffmpegLog)).toEqual([]);
  });

  test("rejects symlink master output before writing", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    const collection = setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
    ]);
    const outside = join(channelRoot, "outside-master.mp3");
    writeText(outside, "outside");
    symlinkSync(outside, join(collection, "01-master", "master.mp3"));
    const ffmpegLog = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("unsafe symlink output path");
    }
    expect(readFfmpegCalls(ffmpegLog)).toEqual([]);
  });

  test("returns io error when ffmpeg exits zero without creating output", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    installFakeFfmpeg({ writeOutput: false });

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("io");
      expect(result.error.message).toContain("master output was not created");
    }
  });

  test("removes temp master output when ffmpeg fails after writing it", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    const collection = setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
    ]);
    installFakeFfmpeg({ exitCode: 42, writeOutput: true });

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    const masterDir = join(collection, "01-master");
    expect(existsSync(join(masterDir, "master.mp3"))).toBe(false);
    expect(
      readdirSync(masterDir).filter((name) => name.includes(".tmp-"))
    ).toEqual([]);
  });
});
