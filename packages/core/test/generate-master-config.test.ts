import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, symlinkSync } from "node:fs";
import { join } from "node:path";

import { generateMasterService } from "@youtube-automation/core/generate-master";

import {
  installFakeFfmpeg,
  makeTempRoot,
  readFfmpegCalls,
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

describe("generateMasterService — skill config override", () => {
  test("uses config/skills/masterup.json before masterup.yaml", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.yaml"),
      "audio:\n  crossfade_duration: 9\n  bitrate: 64k\n"
    );
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({
        audio: { bitrate: "320k", crossfade_duration: 2.5 },
      })
    );
    const logPath = installFakeFfmpeg();
    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });
    const [args] = readFfmpegCalls(logPath);
    expect(args).toContain("[0:a][1:a]acrossfade=d=2.5:c1=tri:c2=tri[aout]");
    expect(args).toContain("320k");
    expect(output.crossfadeDuration).toBe(2.5);
    expect(output.bitrate).toBe("320k");
  });

  test("falls back to config/skills/masterup.yaml when JSON is absent", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", [
      "01-a.mp3",
      "02-b.mp3",
      "03-c.mp3",
    ]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.yaml"),
      [
        "audio:",
        "  bitrate: 224k",
        "  crossfade_duration: 2",
        "  pin_first_count: 1",
        "  shuffle: true",
        "  shuffle_seed: 0",
      ].join("\n")
    );
    installFakeFfmpeg();
    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });
    expect(output.bitrate).toBe("224k");
    expect(output.crossfadeDuration).toBe(2);
    expect(output.messages).toContain("[Shuffle] seed=0");
    expect(output.messages.some((line) => line.includes("[Pin]"))).toBe(true);
  });

  test("ignores legacy audio.finalize YAML values", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.yaml"),
      [
        "audio:",
        "  bitrate: 224k",
        "  crossfade_duration: 2",
        "  finalize:",
        "    bitrate: 256k",
        "    crossfade_duration: 3",
        "    target_duration_min: 3",
        "    ambient_layers:",
        "      enabled: true",
      ].join("\n")
    );
    const ffmpegLog = installFakeFfmpeg();

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    const [args] = readFfmpegCalls(ffmpegLog);
    expect(args).toBeDefined();
    expect(args).toContain("224k");
    expect((args ?? []).join(" ")).toContain("acrossfade=d=2");
    expect(output.loopCount).toBe(1);
    expect(output.bitrate).toBe("224k");
    expect(output.crossfadeDuration).toBe(2);
  });

  test("parses quoted YAML scalars and inline comments", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.yaml"),
      [
        "audio:",
        '  bitrate: "256k" # keep ffmpeg bitrate unquoted',
        "  crossfade_duration: 2 # seconds",
      ].join("\n")
    );
    const logPath = installFakeFfmpeg();

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    const [args] = readFfmpegCalls(logPath);
    expect(args).toContain("256k");
    expect(args).not.toContain('"256k"');
    expect(output.bitrate).toBe("256k");
    expect(output.crossfadeDuration).toBe(2);
  });

  test("returns config error for unsupported audio YAML lines before ffmpeg", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.yaml"),
      ["audio:", "  bitrate:"].join("\n")
    );
    const logPath = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("unsupported masterup audio YAML");
    }
    expect(readFfmpegCalls(logPath)).toEqual([]);
  });

  test("returns config error for inline or scalar audio YAML before ffmpeg", async () => {
    for (const yaml of ["audio: {}", "audio: null"]) {
      const channelRoot = makeTempRoot("generate-master-channel-");
      setupCollection(channelRoot, "collections/demo", [
        "01-a.mp3",
        "02-b.mp3",
      ]);
      writeText(join(channelRoot, "config", "skills", "masterup.yaml"), yaml);
      const logPath = installFakeFfmpeg();

      const result = await generateMasterService({
        channel_dir: channelRoot,
        collection: "collections/demo",
      });

      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.error.domain).toBe("config");
        expect(result.error.message).toContain("audio YAML must be a mapping");
      }
      expect(readFfmpegCalls(logPath)).toEqual([]);
    }
  });

  test("treats missing audio section as an empty compatibility override", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ post_processing: { enabled: true } })
    );
    const logPath = installFakeFfmpeg();

    const output = await runOk({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    const [args] = readFfmpegCalls(logPath);
    expect(args).toContain("192k");
    expect(output.crossfadeDuration).toBe(1);
  });

  test("returns config error before ffmpeg when audio section is not an object", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: null })
    );
    const logPath = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("audio must be an object");
    }
    expect(readFfmpegCalls(logPath)).toEqual([]);
  });

  test("returns config error before ffmpeg when root config is not an object", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify([])
    );
    const logPath = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("must contain an object");
    }
    expect(readFfmpegCalls(logPath)).toEqual([]);
  });

  test("does not fall back to YAML when masterup.json is a directory", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    mkdirSync(join(channelRoot, "config", "skills", "masterup.json"), {
      recursive: true,
    });
    writeText(
      join(channelRoot, "config", "skills", "masterup.yaml"),
      "audio:\n  bitrate: 64k\n"
    );
    const logPath = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("must be a regular file");
    }
    expect(readFfmpegCalls(logPath)).toEqual([]);
  });

  test("does not fall back to YAML when masterup.json is a broken symlink", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    mkdirSync(join(channelRoot, "config", "skills"), { recursive: true });
    symlinkSync(
      join(channelRoot, "missing-masterup.json"),
      join(channelRoot, "config", "skills", "masterup.json")
    );
    writeText(
      join(channelRoot, "config", "skills", "masterup.yaml"),
      "audio:\n  bitrate: 64k\n"
    );
    const logPath = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("must be a regular file");
    }
    expect(readFfmpegCalls(logPath)).toEqual([]);
  });

  test("keeps explicit CLI default values above config overrides", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({
        audio: { bitrate: "320k", crossfade_duration: 2.5 },
      })
    );
    const logPath = installFakeFfmpeg();
    const output = await runOk({
      bitrate: "192k",
      channel_dir: channelRoot,
      collection: "collections/demo",
      crossfade_duration: 1,
    });
    const [args] = readFfmpegCalls(logPath);
    expect(args).toContain("[0:a][1:a]acrossfade=d=1:c1=tri:c2=tri[aout]");
    expect(args).toContain("192k");
    expect(output.crossfadeDuration).toBe(1);
    expect(output.bitrate).toBe("192k");
  });

  test("returns config error for blank masterup bitrate before ffmpeg", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { bitrate: "   " } })
    );
    const logPath = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("invalid masterup audio config");
    }
    expect(readFfmpegCalls(logPath)).toEqual([]);
  });
});

describe("generateMasterService — Result error contract", () => {
  test("returns a validation-domain error when no supported audio files exist", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", []);
    installFakeFfmpeg();
    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("02-Individual-music");
    }
  });

  test("returns a validation-domain error for a missing pin_first file", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    installFakeFfmpeg();
    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
      pin_first: ["missing.mp3"],
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("pin-first");
    }
  });

  test("normalizes ffmpeg subprocess failure through ServiceError", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    installFakeFfmpeg(42);
    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("io");
      expect(result.error.message).toContain("ffmpeg");
    }
  });

  test("returns a config-domain error before ffmpeg for invalid masterup audio config", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      JSON.stringify({ audio: { crossfade_duration: "bad" } })
    );
    const logPath = installFakeFfmpeg();
    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("masterup audio config");
    }
    expect(readFfmpegCalls(logPath)).toEqual([]);
  });

  test("returns a config-domain error for malformed masterup.json", async () => {
    const channelRoot = makeTempRoot("generate-master-channel-");
    setupCollection(channelRoot, "collections/demo", ["01-a.mp3", "02-b.mp3"]);
    writeText(
      join(channelRoot, "config", "skills", "masterup.json"),
      '{"audio":{"bitrate":"320k"'
    );
    const logPath = installFakeFfmpeg();

    const result = await generateMasterService({
      channel_dir: channelRoot,
      collection: "collections/demo",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("failed to parse");
      expect(result.error.message).toContain("masterup.json");
    }
    expect(readFfmpegCalls(logPath)).toEqual([]);
  });
});
