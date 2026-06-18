import { afterEach, describe, expect, spyOn, test } from "bun:test";
import {
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { ok } from "@youtube-automation/core";
import { REGISTRY } from "@youtube-automation/core/registry";

import {
  createGenerateImageCommand,
  referencesFromArg,
} from "../src/commands/generate-image/cli.ts";

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
  options: { env: Record<string, string | undefined> },
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
    cwd: repoRoot,
    env,
  });
};

const writeOpenAIChannel = (): string => {
  const channelDir = makeTempDir("cli-image-channel-");
  mkdirSync(join(channelDir, "config", "skills"), { recursive: true });
  writeFileSync(
    join(channelDir, "config", "skills", "thumbnail.yaml"),
    ["image_generation:", "  provider: openai"].join("\n"),
    "utf-8"
  );
  return channelDir;
};

describe("core registry — image.generate entry visible from cli package", () => {
  test("should expose the registry entry consumed by the CLI adapter", () => {
    const registry = REGISTRY as Record<
      string,
      { deps: readonly string[]; description: string }
    >;
    const entry = registry["image.generate"];

    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("image.generate registry entry is required");
    }
    expect(entry.deps).toEqual(["channelDir", "imageProvider"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk generate-image — smoke", () => {
  test("wraps a single reference argument into the service input array", () => {
    expect(referencesFromArg("ref.png")).toEqual(["ref.png"]);
  });

  test("rejects invalid reference argument values before service execution", () => {
    expect(() => referencesFromArg([123])).toThrow(
      "validation: --reference は文字列で指定してください"
    );
  });

  test("prints the success result from the CLI adapter", async () => {
    const channelDir = makeTempDir("cli-image-success-");
    const registryEntry = REGISTRY["image.generate"];
    const entry = {
      ...registryEntry,
      run: (() =>
        Promise.resolve(
          ok({
            savedPath: join(channelDir, "collections/planning/demo/main.png"),
          })
        )) as typeof registryEntry.run,
    };
    const stdoutSpy = spyOn(process.stdout, "write").mockImplementation(
      () => true
    );
    const command = createGenerateImageCommand({
      entry,
      resolveDeps: () =>
        Promise.resolve({
          channelDir,
          imageProvider: {
            generate: () => Promise.resolve(new Uint8Array([1])),
            name: "fake",
            supportedAspectRatios: [],
          },
        }),
    });

    try {
      await command.run?.({
        args: {
          "aspect-ratio": "16:9",
          "image-size": "2K",
          json: false,
          output: "collections/planning/demo/main.png",
          prompt: "a square cafe thumbnail",
          reference: undefined,
        },
      } as never);

      expect(stdoutSpy).toHaveBeenCalledWith(
        `saved: ${join(channelDir, "collections/planning/demo/main.png")}\n`
      );
    } finally {
      stdoutSpy.mockRestore();
    }
  });

  test("formats provider config errors through the command helper", () => {
    const channelDir = writeOpenAIChannel();

    const proc = runTayk(
      { env: { CHANNEL_DIR: channelDir, OPENAI_API_KEY: undefined } },
      "generate-image",
      "--prompt",
      "a square cafe thumbnail",
      "--output",
      "collections/planning/demo/out.png",
      "--aspect-ratio",
      "1:1",
      "--json"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toStartWith("[config] ");
    expect(proc.stderr.toString()).toContain("aspect_ratio");
    expect(proc.stderr.toString()).not.toContain("at ");
  });
});
