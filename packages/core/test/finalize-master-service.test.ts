import { afterEach, describe, expect, test } from "bun:test";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";

import { finalizeMasterService } from "@youtube-automation/core/finalize-master";
import type {
  FinalizeMasterInput,
  FinalizeMasterOutput,
} from "@youtube-automation/core/finalize-master";

let tmpDirs: string[] = [];
const originalPath = process.env.PATH;

const makeTempDir = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const realDir = realpathSync(dir);
  tmpDirs = [...tmpDirs, realDir];
  return realDir;
};

afterEach(() => {
  process.env.PATH = originalPath;
  delete process.env.FAKE_FFMPEG_LOG;
  delete process.env.FAKE_FFMPEG_MODE;
  for (const dir of tmpDirs) {
    rmSync(dir, { force: true, recursive: true });
  }
  tmpDirs = [];
});

const makeCollection = (channelDir: string): string => {
  const collectionDir = join(channelDir, "collections", "planning", "test");
  mkdirSync(join(collectionDir, "01-master"), { recursive: true });
  writeFileSync(join(collectionDir, "01-master", "master.mp3"), "master");
  return collectionDir;
};

const writeDefaultLayer = (channelDir: string, name = "rain_001.wav"): void => {
  const layerDir = join(channelDir, "branding", "rain_layers");
  mkdirSync(layerDir, { recursive: true });
  writeFileSync(join(layerDir, name), "");
};

const writeMasterupConfig = (channelDir: string, text: string): void => {
  const configDir = join(channelDir, "config", "skills");
  mkdirSync(configDir, { recursive: true });
  writeFileSync(join(configDir, "masterup.json"), text, "utf-8");
};

const masterPathFor = (collectionDir: string): string =>
  join(collectionDir, "01-master", "master.mp3");

const tmpPathFor = (collectionDir: string): string =>
  join(collectionDir, "01-master", "master.tmp.mp3");

const installFakeFfmpeg = (mode = "ok"): string => {
  const binDir = makeTempDir("finalize-ffmpeg-bin-");
  const logPath = join(binDir, "ffmpeg.log");
  const scriptPath = join(binDir, "ffmpeg");
  writeFileSync(
    scriptPath,
    [
      "#!/bin/sh",
      'printf "CALL %s\\n" "$*" >> "$FAKE_FFMPEG_LOG"',
      'case "$FAKE_FFMPEG_MODE" in',
      '  pass1-fail) echo " $* " | grep -q " -f null -" && { echo "pass1 failed" >&2; exit 12; } ;;',
      '  pass2-fail) echo " $* " | grep -q " -f null -" || { echo "pass2 failed" >&2; exit 13; } ;;',
      '  parse-fail) echo " $* " | grep -q " -f null -" && { echo "no measurements" >&2; exit 0; } ;;',
      "esac",
      'if echo " $* " | grep -q " -f null -"; then',
      '  echo "{\\"input_i\\":-23,\\"input_tp\\":-2.1,\\"input_lra\\":10.5,\\"input_thresh\\":-33,\\"target_offset\\":0.5}" >&2',
      "  exit 0",
      "fi",
      'for arg in "$@"; do out="$arg"; done',
      'printf "encoded" > "$out"',
      "exit 0",
      "",
    ].join("\n")
  );
  chmodSync(scriptPath, 0o755);
  process.env.PATH = [binDir, originalPath].filter(Boolean).join(delimiter);
  process.env.FAKE_FFMPEG_LOG = logPath;
  process.env.FAKE_FFMPEG_MODE = mode;
  return logPath;
};

const readFfmpegCalls = (logPath: string): string[] =>
  readFileSync(logPath, "utf-8").trim().split("\n");

const serviceOk = async (
  input: FinalizeMasterInput,
  channelDir: string
): Promise<FinalizeMasterOutput> => {
  const result = await finalizeMasterService(input, { channelDir });
  if (!result.ok) {
    throw new Error(
      `expected an ok Result, got error: ${JSON.stringify(result.error)}`
    );
  }
  return result.value;
};

describe("finalizeMasterService — pass-through gates", () => {
  test("should pass through before reading invalid config when default layers are absent", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeMasterupConfig(channelDir, "{not-json");

    const output = await serviceOk({ collectionDir }, channelDir);

    expect(output).toEqual({
      layersApplied: 0,
      loudnormApplied: false,
      masterPath: join(collectionDir, "01-master", "master.mp3"),
      passThrough: true,
      warnings: [],
    });
  });

  test("should pass through after resolved custom glob yields no layers", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeDefaultLayer(channelDir);
    writeMasterupConfig(
      channelDir,
      JSON.stringify({
        audio: {
          finalize: {
            ambient_layers: { dirname: "ambient", glob: "amb_*.wav" },
          },
        },
      })
    );

    const output = await serviceOk({ collectionDir }, channelDir);

    expect(output).toEqual({
      layersApplied: 0,
      loudnormApplied: false,
      masterPath: join(collectionDir, "01-master", "master.mp3"),
      passThrough: true,
      warnings: [],
    });
  });

  test("should surface config errors after gate1 finds a default layer", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeDefaultLayer(channelDir);
    writeMasterupConfig(
      channelDir,
      JSON.stringify({
        audio: { finalize: { loudnorm: { mode: "dynamic" } } },
      })
    );

    const result = await finalizeMasterService(
      { collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toMatch(/dynamic.*not implemented/iu);
    }
  });
});

describe("finalizeMasterService — service boundary", () => {
  test("should return validation Result instead of rejecting invalid input", async () => {
    const channelDir = makeTempDir("finalize-channel-");

    const result = await finalizeMasterService({} as FinalizeMasterInput, {
      channelDir,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
      expect(result.error.message).toContain("collectionDir");
    }
  });
});

describe("finalizeMasterService — ffmpeg orchestration and atomic overwrite", () => {
  test("should run 2-pass loudnorm and atomically replace master on success", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeDefaultLayer(channelDir);
    const logPath = installFakeFfmpeg();

    const output = await serviceOk({ collectionDir }, channelDir);

    expect(output).toEqual({
      layersApplied: 1,
      loudnormApplied: true,
      masterPath: masterPathFor(collectionDir),
      passThrough: false,
      warnings: [],
    });
    expect(readFileSync(masterPathFor(collectionDir), "utf-8")).toBe("encoded");
    expect(existsSync(tmpPathFor(collectionDir))).toBe(false);
    const calls = readFfmpegCalls(logPath);
    expect(calls).toHaveLength(2);
    expect(calls[0]).toContain("-f null -");
    expect(calls[1]).toContain("master.tmp.mp3");
  });

  test("should run single-pass encode when loudnorm is disabled", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeDefaultLayer(channelDir);
    writeMasterupConfig(
      channelDir,
      JSON.stringify({ audio: { finalize: { loudnorm: { enabled: false } } } })
    );
    const logPath = installFakeFfmpeg();

    const output = await serviceOk({ collectionDir }, channelDir);

    expect(output.loudnormApplied).toBe(false);
    expect(readFileSync(masterPathFor(collectionDir), "utf-8")).toBe("encoded");
    const calls = readFfmpegCalls(logPath);
    expect(calls).toHaveLength(1);
    expect(calls[0]).not.toContain("-f null -");
  });

  test("should keep master unchanged and clean tmp when pass2 fails", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeDefaultLayer(channelDir);
    const logPath = installFakeFfmpeg("pass2-fail");

    const result = await finalizeMasterService(
      { collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    expect(readFileSync(masterPathFor(collectionDir), "utf-8")).toBe("master");
    expect(existsSync(tmpPathFor(collectionDir))).toBe(false);
    expect(readFfmpegCalls(logPath)).toHaveLength(2);
  });

  test("should keep master unchanged when pass1 fails before tmp creation", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeDefaultLayer(channelDir);
    installFakeFfmpeg("pass1-fail");

    const result = await finalizeMasterService(
      { collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    expect(readFileSync(masterPathFor(collectionDir), "utf-8")).toBe("master");
    expect(existsSync(tmpPathFor(collectionDir))).toBe(false);
  });

  test("should surface loudnorm parser failure and keep master unchanged", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeDefaultLayer(channelDir);
    installFakeFfmpeg("parse-fail");

    const result = await finalizeMasterService(
      { collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
    }
    expect(readFileSync(masterPathFor(collectionDir), "utf-8")).toBe("master");
    expect(existsSync(tmpPathFor(collectionDir))).toBe(false);
  });

  test("should report ffmpeg absence after layer gates pass", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    writeDefaultLayer(channelDir);
    process.env.PATH = "";

    const result = await finalizeMasterService(
      { collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("io");
      expect(result.error.message).toMatch(/ffmpeg not found/iu);
    }
  });

  test("should report missing master after layer gates and ffmpeg check pass", async () => {
    const channelDir = makeTempDir("finalize-channel-");
    const collectionDir = makeCollection(channelDir);
    rmSync(masterPathFor(collectionDir), { force: true });
    writeDefaultLayer(channelDir);
    installFakeFfmpeg();

    const result = await finalizeMasterService(
      { collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("io");
      expect(result.error.message).toMatch(/master.*not found|ENOENT/iu);
    }
  });
});
