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
import { join, resolve } from "node:path";

import { REGISTRY } from "@youtube-automation/core/registry";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const taykBin = join(repoRoot, "packages", "cli", "bin", "tayk.ts");
const tmpDirs: string[] = [];

const makeTempDir = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const realDir = realpathSync(dir);
  tmpDirs.push(realDir);
  return realDir;
};

afterEach(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

const runTayk = (
  options: { cwd?: string; env: Record<string, string | undefined> },
  ...argv: string[]
) => {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) {
      env[key] = value;
    }
  }
  for (const [key, value] of Object.entries(options.env)) {
    if (value === undefined) {
      Reflect.deleteProperty(env, key);
    } else {
      env[key] = value;
    }
  }

  return Bun.spawnSync(["bun", taykBin, ...argv], {
    cwd: options.cwd ?? repoRoot,
    env,
  });
};

const writeFixture = (
  collectionName = "test",
  tracks: readonly string[] = ["01-opening.mp3"]
): { channelDir: string; collectionDir: string } => {
  const channelDir = makeTempDir("cli-master-channel-");
  const collectionDir = join(
    channelDir,
    "collections",
    "planning",
    collectionName
  );
  mkdirSync(join(collectionDir, "01-master"), { recursive: true });
  mkdirSync(join(collectionDir, "02-Individual-music"), { recursive: true });
  for (const track of tracks) {
    writeFileSync(
      join(collectionDir, "02-Individual-music", track),
      track === "01-opening.mp3" ? "single-track-bytes" : `${track}-bytes`,
      "utf-8"
    );
  }
  return { channelDir, collectionDir };
};

const writeFakeFfmpegBin = (): string => {
  const binDir = makeTempDir("cli-master-bin-");
  const ffmpegPath = join(binDir, "ffmpeg");
  writeFileSync(
    ffmpegPath,
    [
      "#!/bin/sh",
      "out=''",
      "prev=''",
      'for arg in "$@"; do',
      '  if [ "$arg" = \'-loglevel\' ]; then out="$prev"; break; fi',
      '  prev="$arg"',
      '  out="$arg"',
      "done",
      "printf 'joined-track-bytes' > \"$out\"",
      "exit 0",
      "",
    ].join("\n"),
    "utf-8"
  );
  chmodSync(ffmpegPath, 0o755);
  return binDir;
};

const cliTest = (name: string, fn: () => void): void => {
  test(name, fn, 15_000);
};

describe("core registry - master.generate entry visible from cli package", () => {
  test("should expose the registry entry consumed by the CLI adapter", () => {
    const entry = REGISTRY["master.generate"];

    expect(entry.deps).toEqual(["channelDir", "masterupDefaultConfigPath"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk generate-master - smoke", () => {
  cliTest(
    "should generate a master file through the dispatcher and print JSON output",
    () => {
      const { channelDir, collectionDir } = writeFixture();

      const proc = runTayk(
        { env: { CHANNEL_DIR: channelDir } },
        "generate-master",
        collectionDir,
        "--json"
      );

      expect(proc.exitCode).toBe(0);
      const parsed = JSON.parse(proc.stdout.toString()) as {
        audioExt: string;
        copied: boolean;
        inputCount: number;
        outputPath: string;
      };
      expect(parsed).toMatchObject({
        audioExt: "mp3",
        copied: true,
        inputCount: 1,
        outputPath: join(collectionDir, "01-master", "master.mp3"),
      });
      expect(existsSync(parsed.outputPath)).toBe(true);
      expect(readFileSync(parsed.outputPath, "utf-8")).toBe(
        "single-track-bytes"
      );
    }
  );

  cliTest(
    "should generate a multi-track master through ffmpeg from the dispatcher",
    () => {
      const { channelDir, collectionDir } = writeFixture("test", [
        "01-opening.mp3",
        "02-middle.mp3",
      ]);
      const fakeBin = writeFakeFfmpegBin();

      const proc = runTayk(
        {
          env: {
            CHANNEL_DIR: channelDir,
            PATH: `${fakeBin}:${process.env.PATH}`,
          },
        },
        "generate-master",
        collectionDir,
        "--loop",
        "2",
        "--json"
      );

      expect(proc.exitCode).toBe(0);
      const parsed = JSON.parse(proc.stdout.toString()) as {
        copied: boolean;
        inputCount: number;
        loops: number;
        outputPath: string;
        segmentCount: number;
      };
      expect(parsed).toMatchObject({
        copied: false,
        inputCount: 2,
        loops: 2,
        outputPath: join(collectionDir, "01-master", "master.mp3"),
        segmentCount: 4,
      });
      expect(readFileSync(parsed.outputPath, "utf-8")).toBe(
        "joined-track-bytes"
      );
    }
  );

  cliTest("should suppress text output when quiet is set", () => {
    const { channelDir, collectionDir } = writeFixture();

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-master",
      collectionDir,
      "--quiet"
    );

    expect(proc.exitCode).toBe(0);
    expect(proc.stdout.toString()).toBe("");
    expect(existsSync(join(collectionDir, "01-master", "master.mp3"))).toBe(
      true
    );
  });

  cliTest("should accept a collection path relative to CHANNEL_DIR", () => {
    const { channelDir, collectionDir } = writeFixture();
    const relativeCollectionDir = collectionDir.slice(channelDir.length + 1);

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-master",
      relativeCollectionDir,
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      outputPath: string;
    };
    expect(parsed.outputPath).toBe(
      join(collectionDir, "01-master", "master.mp3")
    );
    expect(existsSync(parsed.outputPath)).toBe(true);
  });

  cliTest("should use CWD when collection path is omitted", () => {
    const { channelDir, collectionDir } = writeFixture();

    const proc = runTayk(
      { cwd: collectionDir, env: { CHANNEL_DIR: channelDir } },
      "generate-master",
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      outputPath: string;
    };
    expect(parsed.outputPath).toBe(
      join(collectionDir, "01-master", "master.mp3")
    );
    expect(existsSync(parsed.outputPath)).toBe(true);
  });

  cliTest("should accept generate-master as the collection positional", () => {
    const { channelDir, collectionDir } = writeFixture("generate-master");
    const relativeCollectionDir = collectionDir.slice(channelDir.length + 1);

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-master",
      relativeCollectionDir,
      "--json"
    );

    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      outputPath: string;
    };
    expect(parsed.outputPath).toBe(
      join(collectionDir, "01-master", "master.mp3")
    );
    expect(existsSync(parsed.outputPath)).toBe(true);
  });

  cliTest(
    "should format dependency resolution errors through the command helper",
    () => {
      const proc = runTayk(
        { env: { CHANNEL_DIR: undefined } },
        "generate-master",
        "--json"
      );

      expect(proc.exitCode).toBe(1);
      expect(proc.stderr.toString()).toStartWith("[config] ");
      expect(proc.stderr.toString()).toContain("CHANNEL_DIR");
      expect(proc.stderr.toString()).not.toContain("at ");
    }
  );

  cliTest("should reject unknown generate-master flags", () => {
    const { channelDir, collectionDir } = writeFixture();

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-master",
      collectionDir,
      "--targt-duration",
      "120",
      "--json"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toStartWith("[validation] ");
    expect(proc.stderr.toString()).toContain("unknown option --targt-duration");
    expect(existsSync(join(collectionDir, "01-master", "master.mp3"))).toBe(
      false
    );
  });

  cliTest("should reject extra positional arguments", () => {
    const { channelDir, collectionDir } = writeFixture();
    const otherCollection = join(
      channelDir,
      "collections",
      "planning",
      "other"
    );

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-master",
      collectionDir,
      otherCollection,
      "--json"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toStartWith("[validation] ");
    expect(proc.stderr.toString()).toContain(
      `unexpected argument ${otherCollection}`
    );
    expect(existsSync(join(collectionDir, "01-master", "master.mp3"))).toBe(
      false
    );
  });

  cliTest("should list generate-master in dispatcher help", () => {
    const proc = runTayk({ env: {} }, "--help");

    expect(proc.exitCode).toBe(0);
    expect(proc.stdout.toString()).toContain("generate-master");
  });

  cliTest(
    "should pass mastering flags through to validation instead of treating them as paths",
    () => {
      const { channelDir, collectionDir } = writeFixture();

      const proc = runTayk(
        { env: { CHANNEL_DIR: channelDir } },
        "generate-master",
        collectionDir,
        "--loop",
        "2",
        "--target-duration",
        "30",
        "--json"
      );

      expect(proc.exitCode).toBe(1);
      expect(proc.stderr.toString()).toStartWith("[validation] ");
      expect(proc.stderr.toString()).toContain("target_duration");
      expect(proc.stderr.toString()).not.toContain("No such file");
    }
  );

  cliTest(
    "should accept equals-form value flags before schema validation",
    () => {
      const { channelDir, collectionDir } = writeFixture();

      const proc = runTayk(
        { env: { CHANNEL_DIR: channelDir } },
        "generate-master",
        collectionDir,
        "--loop=1",
        "--target-duration=1",
        "--json"
      );

      expect(proc.exitCode).toBe(1);
      expect(proc.stderr.toString()).toStartWith("[validation] ");
      expect(proc.stderr.toString()).toContain(
        "loop and target_duration cannot be used together"
      );
      expect(proc.stderr.toString()).not.toContain("unknown option");
      expect(existsSync(join(collectionDir, "01-master", "master.mp3"))).toBe(
        false
      );
    }
  );

  cliTest(
    "should pass repeated pin-first values without treating them as collection paths",
    () => {
      const { channelDir, collectionDir } = writeFixture();

      const proc = runTayk(
        { cwd: collectionDir, env: { CHANNEL_DIR: channelDir } },
        "generate-master",
        "--pin-first",
        "01-opening.mp3",
        "--pin-first",
        "missing.mp3",
        "--json"
      );

      expect(proc.exitCode).toBe(1);
      expect(proc.stderr.toString()).toStartWith("[validation] ");
      expect(proc.stderr.toString()).toContain("missing.mp3");
      expect(proc.stderr.toString()).not.toContain("No such file");
    }
  );

  cliTest("should accept multiple pin-first values after one flag", () => {
    const { channelDir, collectionDir } = writeFixture();

    const proc = runTayk(
      { cwd: collectionDir, env: { CHANNEL_DIR: channelDir } },
      "generate-master",
      "--pin-first",
      "01-opening.mp3",
      "missing.mp3",
      "--json"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toStartWith("[validation] ");
    expect(proc.stderr.toString()).toContain("missing.mp3");
    expect(proc.stderr.toString()).not.toContain("unexpected argument");
    expect(proc.stderr.toString()).not.toContain("No such file");
  });

  cliTest("should keep collection positional separate from pin-first", () => {
    const { channelDir, collectionDir } = writeFixture();

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir } },
      "generate-master",
      "--pin-first",
      "missing.mp3",
      collectionDir,
      "--json"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toStartWith("[validation] ");
    expect(proc.stderr.toString()).toContain("missing.mp3");
    expect(proc.stderr.toString()).not.toContain("unexpected argument");
    expect(proc.stderr.toString()).not.toContain("No such file");
  });

  cliTest(
    "should reject missing value for value flags before generating output",
    () => {
      const { channelDir, collectionDir } = writeFixture();

      const proc = runTayk(
        { env: { CHANNEL_DIR: channelDir } },
        "generate-master",
        collectionDir,
        "--loop",
        "--json"
      );

      expect(proc.exitCode).toBe(1);
      expect(proc.stderr.toString()).toStartWith("[validation] ");
      expect(proc.stderr.toString()).toContain("missing value for --loop");
      expect(existsSync(join(collectionDir, "01-master", "master.mp3"))).toBe(
        false
      );
    }
  );

  cliTest(
    "should reject missing value for pin-first before generating output",
    () => {
      const { channelDir, collectionDir } = writeFixture();

      const proc = runTayk(
        { env: { CHANNEL_DIR: channelDir } },
        "generate-master",
        collectionDir,
        "--pin-first",
        "--json"
      );

      expect(proc.exitCode).toBe(1);
      expect(proc.stderr.toString()).toStartWith("[validation] ");
      expect(proc.stderr.toString()).toContain("missing value for --pin-first");
      expect(existsSync(join(collectionDir, "01-master", "master.mp3"))).toBe(
        false
      );
    }
  );
});
