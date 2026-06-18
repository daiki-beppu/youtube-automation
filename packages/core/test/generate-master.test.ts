import { afterEach, describe, expect, mock, spyOn, test } from "bun:test";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import * as generateMasterPublicApi from "@youtube-automation/core/generate-master";
import {
  generateMasterService,
  GenerateMasterInputSchema,
} from "@youtube-automation/core/generate-master";
import type {
  GenerateMasterInput,
  GenerateMasterOutput,
} from "@youtube-automation/core/generate-master";
import { REGISTRY } from "@youtube-automation/core/registry";

const tmpDirs: string[] = [];
const repoRoot = join(import.meta.dir, "..", "..", "..");
const masterupDefaultConfigPath = join(
  repoRoot,
  ".claude",
  "skills",
  "masterup",
  "config.default.json"
);

const makeTempDir = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const realDir = realpathSync(dir);
  tmpDirs.push(realDir);
  return realDir;
};

afterEach(() => {
  mock.restore();
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

const makeCollection = (channelDir: string, name = "test"): string => {
  const collectionDir = join(channelDir, "collections", "planning", name);
  mkdirSync(join(collectionDir, "01-master"), { recursive: true });
  mkdirSync(join(collectionDir, "02-Individual-music"), { recursive: true });
  return collectionDir;
};

const writeMasterupOverride = (
  channelDir: string,
  config: Record<string, unknown>
): void => {
  const configDir = join(channelDir, "config", "skills");
  mkdirSync(configDir, { recursive: true });
  writeFileSync(
    join(configDir, "masterup.json"),
    `${JSON.stringify(config, null, 2)}\n`,
    "utf-8"
  );
};

const writeTrack = (
  collectionDir: string,
  filename: string,
  content: string
): string => {
  const path = join(collectionDir, "02-Individual-music", filename);
  writeFileSync(path, content, "utf-8");
  return path;
};

const generateOk = async (
  input: GenerateMasterInput,
  channelDir: string
): Promise<GenerateMasterOutput> => {
  const result = await generateMasterService(input, {
    channelDir,
    masterupDefaultConfigPath,
  });
  if (!result.ok) {
    throw new Error(
      `expected an ok Result, got error: ${JSON.stringify(result.error)}`
    );
  }
  return result.value;
};

const fakeProc = (stdout = "", exitCode = 0) =>
  ({
    exited: Promise.resolve(exitCode),
    stderr: new ReadableStream({
      start(controller) {
        controller.close();
      },
    }),
    stdout: new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(stdout));
        controller.close();
      },
    }),
  }) as ReturnType<typeof Bun.spawn>;

const ffmpegInputsFrom = (argv: readonly string[] | undefined): string[] => {
  if (argv === undefined) {
    throw new Error("expected ffmpeg argv");
  }
  const inputs: string[] = [];
  for (let index = 0; index < argv.length - 1; index += 1) {
    if (argv[index] === "-i") {
      inputs.push(argv[index + 1] as string);
    }
  }
  return inputs;
};

describe("generate-master public API - exports map", () => {
  test("should expose only service boundary runtime symbols", () => {
    expect(Object.keys(generateMasterPublicApi).toSorted()).toEqual([
      "GenerateMasterInputSchema",
      "GenerateMasterOutputSchema",
      "generateMasterService",
    ]);
  });
});

describe("master.generate registry deps - contract", () => {
  test("should require channelDir and default masterup config from adapters", () => {
    const entry = REGISTRY["master.generate"];

    expect(entry.deps).toEqual(["channelDir", "masterupDefaultConfigPath"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("GenerateMasterInputSchema - contract", () => {
  test("should accept snake_case public input and normalize to camelCase", () => {
    const raw = {
      collection: "collections/planning/test",
      loop: 3,
      pin_first_count: 1,
      shuffle: true,
      shuffle_seed: 42,
    };

    const parsed = GenerateMasterInputSchema.parse(raw);

    expect(parsed).toEqual({
      collection: "collections/planning/test",
      loop: 3,
      pinFirstCount: 1,
      shuffle: true,
      shuffleSeed: 42,
    });
  });

  test("should reject channel_dir because channelDir is a registry dependency", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        channel_dir: "/tmp/channel",
        collection: "collections/planning/test",
      })
    ).toThrow();
    expect(() =>
      GenerateMasterInputSchema.parse({
        channelDir: "/tmp/channel",
        collection: "collections/planning/test",
      })
    ).toThrow();
  });

  test("should reject unknown keys", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/planning/test",
        unexpected: true,
      })
    ).toThrow();
  });

  test("should reject loop and target_duration together", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/planning/test",
        loop: 2,
        target_duration: 30,
      })
    ).toThrow();
  });

  test("should reject pin_first and pin_first_count together", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/planning/test",
        pin_first: ["opening.mp3"],
        pin_first_count: 1,
      })
    ).toThrow();
  });
});

describe("generateMasterService - file generation", () => {
  test("should copy a single source track without requiring ffmpeg", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeTrack(collectionDir, "01-opening.mp3", "single-track-bytes");
    const spawnSpy = spyOn(Bun, "spawn");

    const output = await generateOk({ collection: collectionDir }, channelDir);

    const outputPath = join(collectionDir, "01-master", "master.mp3");
    expect(output).toMatchObject({
      audioExt: "mp3",
      copied: true,
      inputCount: 1,
      outputPath,
    });
    expect(readFileSync(outputPath, "utf-8")).toBe("single-track-bytes");
    expect(spawnSpy).not.toHaveBeenCalled();
  });

  test("should reject mixed MP3 and WAV inputs as validation", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeTrack(collectionDir, "01-opening.mp3", "mp3");
    writeTrack(collectionDir, "02-opening.wav", "wav");

    const result = await generateMasterService(
      { collection: collectionDir },
      { channelDir, masterupDefaultConfigPath }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("mixed");
    }
  });

  test("should build an acrossfade command for sorted tracks and looped order", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupOverride(channelDir, {
      audio: { bitrate: "256k", crossfade_duration: 2 },
    });
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    const output = await generateOk(
      { collection: collectionDir, loop: 3 },
      channelDir
    );

    expect(whichSpy).toHaveBeenCalledWith("ffmpeg");
    expect(spawnSpy).toHaveBeenCalledTimes(1);
    const argv = spawnSpy.mock.calls[0]?.[0];
    expect(argv).toEqual(
      expect.arrayContaining([
        "ffmpeg",
        "-i",
        first,
        "-i",
        second,
        "-i",
        first,
        "-i",
        second,
        "-i",
        first,
        "-i",
        second,
        "-b:a",
        "256k",
        "-q:a",
        "0",
      ])
    );
    expect(argv?.join(" ")).toContain("acrossfade=d=2");
    expect(output).toMatchObject({
      audioExt: "mp3",
      copied: false,
      inputCount: 2,
      loops: 3,
      segmentCount: 6,
    });
  });

  test("should use bundled default masterup config when channel override is absent", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    await generateOk({ collection: collectionDir }, channelDir);

    const argv = spawnSpy.mock.calls[0]?.[0];
    expect(argv).toEqual(
      expect.arrayContaining(["-i", first, "-i", second, "-b:a", "192k"])
    );
    expect(argv?.join(" ")).toContain("acrossfade=d=1");
  });

  test("should match the legacy Python ffmpeg argv contract", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupOverride(channelDir, {
      audio: { bitrate: "256k", crossfade_duration: 2 },
    });
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const outputPath = join(collectionDir, "01-master", "master.mp3");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    await generateOk({ collection: collectionDir }, channelDir);

    expect(spawnSpy.mock.calls[0]?.[0]).toEqual([
      "ffmpeg",
      "-y",
      "-i",
      first,
      "-i",
      second,
      "-filter_complex",
      "[0:a][1:a]acrossfade=d=2:c1=tri:c2=tri[aout]",
      "-map",
      "[aout]",
      "-c:a",
      "libmp3lame",
      "-b:a",
      "256k",
      "-q:a",
      "0",
      outputPath,
      "-loglevel",
      "error",
    ]);
  });

  test("should shuffle tracks deterministically when shuffle and seed are set", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const third = writeTrack(collectionDir, "03-ending.mp3", "third");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    await generateOk(
      { collection: collectionDir, shuffle: true, shuffleSeed: 42 },
      channelDir
    );

    const argv = spawnSpy.mock.calls[0]?.[0];
    const inputs = Array.isArray(argv) ? ffmpegInputsFrom(argv) : undefined;
    expect(inputs).toEqual([third, first, second]);
  });

  test("should enable shuffle when shuffle_seed is provided", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const third = writeTrack(collectionDir, "03-ending.mp3", "third");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    await generateOk(
      { collection: collectionDir, shuffleSeed: 42 },
      channelDir
    );

    const argv = spawnSpy.mock.calls[0]?.[0];
    const inputs = Array.isArray(argv) ? ffmpegInputsFrom(argv) : undefined;
    expect(inputs).toEqual([third, first, second]);
  });

  test("should use skill config shuffle and shuffle_seed when CLI shuffle is omitted", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupOverride(channelDir, {
      audio: { shuffle: true, shuffle_seed: 42 },
    });
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const third = writeTrack(collectionDir, "03-ending.mp3", "third");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    const output = await generateOk({ collection: collectionDir }, channelDir);

    const argv = spawnSpy.mock.calls[0]?.[0];
    const inputs = Array.isArray(argv) ? ffmpegInputsFrom(argv) : undefined;
    expect(inputs).toEqual([third, first, second]);
    expect(output.shuffleSeed).toBe(42);
  });

  test("should not enable shuffle from skill config shuffle_seed alone", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupOverride(channelDir, { audio: { shuffle_seed: 42 } });
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const third = writeTrack(collectionDir, "03-ending.mp3", "third");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    const output = await generateOk({ collection: collectionDir }, channelDir);

    const argv = spawnSpy.mock.calls[0]?.[0];
    const inputs = Array.isArray(argv) ? ffmpegInputsFrom(argv) : undefined;
    expect(inputs).toEqual([first, second, third]);
    expect(output.shuffleSeed).toBeUndefined();
  });

  test("should auto-generate a shuffle seed when shuffle is set without seed", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeTrack(collectionDir, "01-opening.mp3", "first");
    writeTrack(collectionDir, "02-middle.mp3", "second");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    const output = await generateOk(
      { collection: collectionDir, shuffle: true },
      channelDir
    );

    expect(spawnSpy).toHaveBeenCalledTimes(1);
    expect(output.shuffleSeed).toBeInteger();
  });

  test("should move pin_first tracks before building the ffmpeg command", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const third = writeTrack(collectionDir, "03-ending.mp3", "third");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    await generateOk(
      {
        collection: collectionDir,
        pinFirst: ["03-ending.mp3", "01-opening.mp3"],
      },
      channelDir
    );

    const argv = spawnSpy.mock.calls[0]?.[0];
    const inputs = Array.isArray(argv) ? ffmpegInputsFrom(argv) : undefined;
    expect(inputs).toEqual([third, first, second]);
  });

  test("should keep pin_first_count tracks fixed while shuffling the rest", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const third = writeTrack(collectionDir, "03-bridge.mp3", "third");
    const fourth = writeTrack(collectionDir, "04-ending.mp3", "fourth");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    await generateOk(
      {
        collection: collectionDir,
        pinFirstCount: 1,
        shuffle: true,
        shuffleSeed: 42,
      },
      channelDir
    );

    const argv = spawnSpy.mock.calls[0]?.[0];
    const inputs = Array.isArray(argv) ? ffmpegInputsFrom(argv) : undefined;
    expect(inputs).toEqual([first, fourth, second, third]);
  });

  test("should use skill config pin_first_count when CLI pin flags are omitted", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupOverride(channelDir, { audio: { pin_first_count: 1 } });
    const first = writeTrack(collectionDir, "01-opening.mp3", "first");
    const second = writeTrack(collectionDir, "02-middle.mp3", "second");
    const third = writeTrack(collectionDir, "03-bridge.mp3", "third");
    const fourth = writeTrack(collectionDir, "04-ending.mp3", "fourth");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    await generateOk(
      { collection: collectionDir, shuffle: true, shuffleSeed: 42 },
      channelDir
    );

    const argv = spawnSpy.mock.calls[0]?.[0];
    const inputs = Array.isArray(argv) ? ffmpegInputsFrom(argv) : undefined;
    expect(inputs).toEqual([first, fourth, second, third]);
  });

  test("should use target_duration and ffprobe durations to calculate loop count", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupOverride(channelDir, {
      audio: { crossfade_duration: 1 },
    });
    writeTrack(collectionDir, "01-opening.wav", "first");
    writeTrack(collectionDir, "02-middle.wav", "second");
    spyOn(Bun, "which").mockImplementation((name: string) =>
      name === "ffmpeg" || name === "ffprobe" ? `/usr/bin/${name}` : null
    );
    const spawnSpy = spyOn(Bun, "spawn").mockImplementation((argv) => {
      if (Array.isArray(argv) && argv[0] === "ffprobe") {
        return fakeProc("10\n");
      }
      return fakeProc();
    });

    const output = await generateOk(
      { collection: collectionDir, targetDuration: 1 },
      channelDir
    );

    const ffprobeCalls = spawnSpy.mock.calls.filter(
      ([argv]) => Array.isArray(argv) && argv[0] === "ffprobe"
    );
    const ffmpegCall = spawnSpy.mock.calls.find(
      ([argv]) => Array.isArray(argv) && argv[0] === "ffmpeg"
    );
    const ffmpegArgv = Array.isArray(ffmpegCall?.[0])
      ? ffmpegCall[0]
      : undefined;
    expect(ffprobeCalls).toHaveLength(2);
    expect(ffmpegArgv?.join(" ")).toContain("-c:a pcm_s16le");
    expect(output).toMatchObject({
      audioExt: "wav",
      copied: false,
      inputCount: 2,
      loops: 4,
      segmentCount: 8,
    });
  });

  test("should reject target_duration above the bounded maximum", () => {
    expect(() =>
      GenerateMasterInputSchema.parse({
        collection: "collections/planning/test",
        target_duration: 1441,
      })
    ).toThrow();
  });

  test("should surface ffprobe failures as validation errors", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeTrack(collectionDir, "01-opening.wav", "first");
    writeTrack(collectionDir, "02-middle.wav", "second");
    spyOn(Bun, "which").mockImplementation((name: string) =>
      name === "ffprobe" ? `/usr/bin/${name}` : null
    );
    spyOn(Bun, "spawn").mockImplementation(() => fakeProc("", 1));

    const result = await generateMasterService(
      { collection: collectionDir, targetDuration: 1 },
      { channelDir, masterupDefaultConfigPath }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("ffprobe failed");
    }
  });

  test("should surface ffmpeg failures as io errors", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeTrack(collectionDir, "01-opening.mp3", "first");
    writeTrack(collectionDir, "02-middle.mp3", "second");
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    spyOn(Bun, "spawn").mockReturnValue(fakeProc("", 1));

    const result = await generateMasterService(
      { collection: collectionDir },
      { channelDir, masterupDefaultConfigPath }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("io");
      expect(result.error.message).toContain("ffmpeg failed");
    }
  });

  test("should reject loop expansion above the segment limit before spawning ffmpeg", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    for (let index = 1; index <= 11; index += 1) {
      writeTrack(
        collectionDir,
        `${String(index).padStart(2, "0")}-track.mp3`,
        `track-${index}`
      );
    }
    spyOn(Bun, "which").mockReturnValue("/usr/bin/ffmpeg");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc());

    const result = await generateMasterService(
      { collection: collectionDir, loop: 1000 },
      { channelDir, masterupDefaultConfigPath }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("segment count");
    }
    expect(spawnSpy).not.toHaveBeenCalled();
  });

  test("should use skill config target_duration_min when CLI loop and target are omitted", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupOverride(channelDir, { audio: { target_duration_min: 1 } });
    writeTrack(collectionDir, "01-opening.wav", "first");
    writeTrack(collectionDir, "02-middle.wav", "second");
    spyOn(Bun, "which").mockImplementation((name: string) =>
      name === "ffmpeg" || name === "ffprobe" ? `/usr/bin/${name}` : null
    );
    const spawnSpy = spyOn(Bun, "spawn").mockImplementation((argv) => {
      if (Array.isArray(argv) && argv[0] === "ffprobe") {
        return fakeProc("10\n");
      }
      return fakeProc();
    });

    const output = await generateOk({ collection: collectionDir }, channelDir);

    expect(
      spawnSpy.mock.calls.some(
        ([argv]) => Array.isArray(argv) && argv[0] === "ffprobe"
      )
    ).toBe(true);
    expect(output.loops).toBe(4);
    expect(output.segmentCount).toBe(8);
  });

  test("should keep increasing loops until expanded crossfades meet target duration", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupOverride(channelDir, {
      audio: { crossfade_duration: 1 },
    });
    writeTrack(collectionDir, "01-opening.mp3", "first");
    writeTrack(collectionDir, "02-middle.mp3", "second");
    writeTrack(collectionDir, "03-ending.mp3", "third");
    spyOn(Bun, "which").mockImplementation((name: string) =>
      name === "ffmpeg" || name === "ffprobe" ? `/usr/bin/${name}` : null
    );
    spyOn(Bun, "spawn").mockImplementation((argv) => {
      if (Array.isArray(argv) && argv[0] === "ffprobe") {
        return fakeProc("10\n");
      }
      return fakeProc();
    });

    const output = await generateOk(
      { collection: collectionDir, targetDuration: 56 / 60 },
      channelDir
    );

    expect(output.loops).toBe(3);
    expect(output.segmentCount).toBe(9);
  });

  test("should fail fast when pin_first names a missing track", async () => {
    const channelDir = makeTempDir("master-channel-");
    const collectionDir = makeCollection(channelDir);
    writeTrack(collectionDir, "01-opening.mp3", "first");
    writeTrack(collectionDir, "02-middle.mp3", "second");

    const result = await generateMasterService(
      { collection: collectionDir, pinFirst: ["missing.mp3"] },
      { channelDir, masterupDefaultConfigPath }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("pin");
      expect(existsSync(join(collectionDir, "01-master", "master.mp3"))).toBe(
        false
      );
    }
  });
});
