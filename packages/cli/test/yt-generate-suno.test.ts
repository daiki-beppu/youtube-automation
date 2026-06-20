import { describe, expect, test } from "bun:test";
import { join, resolve } from "node:path";

import { ok } from "@youtube-automation/core";
import type { Result, ServiceError } from "@youtube-automation/core";
import { REGISTRY } from "@youtube-automation/core/registry";
import type { DepsMap, RegistryEntry } from "@youtube-automation/core/registry";
import {
  GenerateSunoInputSchema,
  GenerateSunoOutputSchema,
} from "@youtube-automation/core/suno-prompts";
import type {
  GenerateSunoInput,
  GenerateSunoOutput,
} from "@youtube-automation/core/suno-prompts";

import { createGenerateSunoCommand } from "../src/commands/generate-suno/cli.ts";

const CLI_SMOKE_TIMEOUT_MS = 15_000;
const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const taykBin = join(repoRoot, "packages", "cli", "bin", "tayk.ts");

const runTayk = (...argv: string[]) =>
  Bun.spawnSync(["bun", taykBin, ...argv], {
    cwd: repoRoot,
    timeout: CLI_SMOKE_TIMEOUT_MS,
  });

const generatedOutput: GenerateSunoOutput = {
  entryCount: 1,
  jsonPath: "/collection/20-documentation/suno-prompts.json",
  markdownPath: "/collection/20-documentation/suno-prompts.md",
  warnings: ["Style text exceeds 40 char limit"],
};

type GenerateSunoEntry = RegistryEntry<
  typeof GenerateSunoInputSchema,
  typeof GenerateSunoOutputSchema,
  "channelDir"
>;
type GenerateSunoDeps = Pick<DepsMap, "channelDir">;

const makeGenerateEntry = () => {
  const calls: {
    runDeps: GenerateSunoDeps[];
    runInputs: GenerateSunoInput[];
  } = { runDeps: [], runInputs: [] };

  const entry = {
    deps: ["channelDir"] as const,
    description: "Generate Suno prompts",
    inputSchema: GenerateSunoInputSchema,
    outputSchema: GenerateSunoOutputSchema,
    run(input: GenerateSunoInput, deps: GenerateSunoDeps) {
      calls.runInputs.push(input);
      calls.runDeps.push(deps);
      return Promise.resolve(ok(generatedOutput));
    },
  } satisfies GenerateSunoEntry;

  return { calls, entry };
};

const makeEmitResult = () => {
  const calls: {
    json: boolean;
    renderedText?: string;
    result: Result<GenerateSunoOutput, ServiceError>;
  }[] = [];

  return {
    calls,
    emitResult(
      result: Result<GenerateSunoOutput, ServiceError>,
      options: {
        json: boolean;
        renderText: (value: GenerateSunoOutput) => string;
      }
    ) {
      const renderedText = result.ok
        ? options.renderText(result.value)
        : undefined;
      calls.push({ json: options.json, renderedText, result });
    },
  };
};

describe("core registry — suno.generate entry visible from cli package", () => {
  test("should expose the registry entry consumed by the CLI adapter", () => {
    const entry = REGISTRY["suno.generate"];

    expect(entry.deps).toEqual(["channelDir"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk generate-suno — dispatcher smoke", () => {
  test(
    "should list generate-suno in dispatcher help",
    () => {
      const proc = runTayk("--help");

      expect(proc.exitCode).toBe(0);
      expect(proc.stdout.toString()).toContain("generate-suno");
    },
    CLI_SMOKE_TIMEOUT_MS
  );
});

describe("createGenerateSunoCommand — in-process adapter contract", () => {
  test("forwards the positional path, deps, and json flag to the registry entry", async () => {
    const { calls, entry } = makeGenerateEntry();
    const emitted = makeEmitResult();
    const depsValue = { channelDir: "/channel" };
    const depsCalls: (readonly "channelDir"[])[] = [];
    const command = createGenerateSunoCommand({
      emitResult: emitted.emitResult,
      entry,
      getCwd: () => "/unused-cwd",
      resolveDeps: (deps: readonly "channelDir"[]) => {
        depsCalls.push([...deps]);
        return Promise.resolve(depsValue);
      },
    });

    await command.run({
      args: { json: true, path: "/channel/collections/planning/test" },
    } as never);

    expect(depsCalls).toEqual([["channelDir"]]);
    expect(calls.runInputs).toEqual([
      { path: "/channel/collections/planning/test" },
    ]);
    expect(calls.runDeps).toEqual([depsValue]);
    expect(emitted.calls).toHaveLength(1);
    expect(emitted.calls[0]?.json).toBe(true);
  });

  test("reads cwd at command run time when the collection path is omitted", async () => {
    const { calls, entry } = makeGenerateEntry();
    const emitted = makeEmitResult();
    let currentCwd = "/channel/collections/planning/before-run";
    const command = createGenerateSunoCommand({
      emitResult: emitted.emitResult,
      entry,
      getCwd: () => currentCwd,
      resolveDeps: () => Promise.resolve({ channelDir: "/channel" }),
    });

    currentCwd = "/channel/collections/planning/from-runtime-cwd";
    await command.run({ args: { json: false } } as never);

    expect(calls.runInputs).toEqual([
      { path: "/channel/collections/planning/from-runtime-cwd" },
    ]);
    expect(emitted.calls[0]?.json).toBe(false);
  });

  test("treats a positional --json token as json output with cwd as the path", async () => {
    const { calls, entry } = makeGenerateEntry();
    const emitted = makeEmitResult();
    const command = createGenerateSunoCommand({
      emitResult: emitted.emitResult,
      entry,
      getCwd: () => "/channel/collections/planning/json-token",
      resolveDeps: () => Promise.resolve({ channelDir: "/channel" }),
    });

    await command.run({ args: { path: "--json" } } as never);

    expect(calls.runInputs).toEqual([
      { path: "/channel/collections/planning/json-token" },
    ]);
    expect(emitted.calls[0]?.json).toBe(true);
  });

  test("formats dependency resolution failures through emitResult", async () => {
    const { entry } = makeGenerateEntry();
    const emitted = makeEmitResult();
    const command = createGenerateSunoCommand({
      emitResult: emitted.emitResult,
      entry,
      getCwd: () => "/channel/collections/planning/failing",
      resolveDeps: () =>
        Promise.reject(new Error("config: CHANNEL_DIR is required")),
    });

    await command.run({ args: { json: true } } as never);

    expect(emitted.calls).toHaveLength(1);
    expect(emitted.calls[0]?.result).toEqual({
      error: {
        domain: "config",
        message: "config: CHANNEL_DIR is required",
      } satisfies ServiceError,
      ok: false,
    });
  });

  test("keeps normal text rendering in the CLI adapter", async () => {
    const { entry } = makeGenerateEntry();
    const emitted = makeEmitResult();
    const command = createGenerateSunoCommand({
      emitResult: emitted.emitResult,
      entry,
      getCwd: () => "/collection",
      resolveDeps: () => Promise.resolve({ channelDir: "/channel" }),
    });

    await command.run({ args: { json: false, path: "/collection" } } as never);

    expect(emitted.calls[0]?.renderedText).toContain("generated: 1");
    expect(emitted.calls[0]?.renderedText).toContain(
      "markdown: /collection/20-documentation/suno-prompts.md"
    );
    expect(emitted.calls[0]?.renderedText).toContain(
      "[WARN] Style text exceeds 40 char limit"
    );
  });
});
