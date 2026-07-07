import { describe, expect, test } from "bun:test";
import { join, resolve } from "node:path";

import { ok } from "@youtube-automation/core";
import type { Result, ServiceError } from "@youtube-automation/core";
import { REGISTRY } from "@youtube-automation/core/registry";
import type { DepsMap, RegistryEntry } from "@youtube-automation/core/registry";
import {
  SkillListInputSchema,
  SkillListOutputSchema,
  SkillSyncInputSchema,
  SkillSyncOutputSchema,
} from "@youtube-automation/core/skills-sync";
import type {
  SkillListInput,
  SkillListOutput,
  SkillSyncInput,
  SkillSyncOutput,
} from "@youtube-automation/core/skills-sync";
import { runCommand } from "citty";

import { createSkillsCommand } from "../src/commands/skills/cli.ts";

const CLI_SMOKE_TIMEOUT_MS = 15_000;
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

const runTayk = (...argv: string[]) =>
  Bun.spawnSync(["bun", join(repoRoot, "packages/cli/bin/tayk.ts"), ...argv], {
    cwd: repoRoot,
    timeout: CLI_SMOKE_TIMEOUT_MS,
  });

type EmptyDeps = Pick<DepsMap, never>;
type SkillListEntry = RegistryEntry<
  typeof SkillListInputSchema,
  typeof SkillListOutputSchema
>;
type SkillSyncEntry = RegistryEntry<
  typeof SkillSyncInputSchema,
  typeof SkillSyncOutputSchema
>;

const makeUnusedListEntry = () =>
  ({
    deps: [] as const,
    description: "List bundled skills",
    inputSchema: SkillListInputSchema,
    outputSchema: SkillListOutputSchema,
    run(
      _input: SkillListInput,
      _deps: EmptyDeps
    ): Promise<Result<SkillListOutput, ServiceError>> {
      return Promise.reject(
        new Error("list entry should not run in sync tests")
      );
    },
  }) satisfies SkillListEntry;

const makeSyncEntry = () => {
  const calls: {
    runDeps: EmptyDeps[];
    runInputs: SkillSyncInput[];
  } = { runDeps: [], runInputs: [] };

  const entry = {
    deps: [] as const,
    description: "Sync bundled assets",
    inputSchema: SkillSyncInputSchema,
    outputSchema: SkillSyncOutputSchema,
    run(input: SkillSyncInput, deps: EmptyDeps) {
      calls.runInputs.push(input);
      calls.runDeps.push(deps);
      const { asset } = input;
      return Promise.resolve(
        ok({
          agentsSkillsLink: asset === "skills" ? "linked" : null,
          asset,
          entries: [{ name: asset, result: "created" }],
          target: `/target/${asset}`,
        } satisfies SkillSyncOutput)
      );
    },
  } satisfies SkillSyncEntry;

  return { calls, entry };
};

const makeEmitResult = () => {
  const calls: {
    json: boolean;
    renderedText?: string;
    result: Result<unknown, ServiceError>;
  }[] = [];

  return {
    calls,
    emitResult<T>(
      result: Result<T, ServiceError>,
      options: { json: boolean; renderText: (value: T) => string }
    ) {
      calls.push({
        json: options.json,
        renderedText: result.ok ? options.renderText(result.value) : undefined,
        result,
      });
    },
  };
};

const makeCommand = () => {
  const { calls, entry: syncEntry } = makeSyncEntry();
  const emitted = makeEmitResult();
  const depsCalls: (readonly never[])[] = [];
  const stderr: string[] = [];
  const exitCodes: number[] = [];
  const command = createSkillsCommand({
    emitResult: emitted.emitResult,
    exit: (code: number) => {
      exitCodes.push(code);
      throw new Error(`exit ${code}`);
    },
    listEntry: makeUnusedListEntry(),
    resolveDeps: (deps: readonly never[]) => {
      depsCalls.push([...deps]);
      return Promise.resolve({});
    },
    syncEntry,
    writeStderr: (message: string) => {
      stderr.push(message);
    },
  });

  return { calls, command, depsCalls, emitted, exitCodes, stderr };
};

describe("core registry — skills.sync entry (ADR-0004 contract)", () => {
  test("declares no deps and a human-readable description", () => {
    const entry = REGISTRY["skills.sync"];

    expect(entry.deps).toEqual([]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk skills sync — dispatcher smoke", () => {
  test(
    "`tayk skills sync --help` exits 0 and prints usage",
    () => {
      const proc = runTayk("skills", "sync", "--help");

      expect(proc.exitCode).toBe(0);
      expect(proc.stdout.toString()).toContain("--asset");
      expect(proc.stdout.toString()).toContain("--target");
    },
    CLI_SMOKE_TIMEOUT_MS
  );
});

describe("tayk skills sync — citty parser defaults", () => {
  test("omitting --asset causes citty to inject default 'all' and sync all assets", async () => {
    const { calls, command } = makeCommand();

    await runCommand(command.subCommands.sync, { rawArgs: [] });

    expect(calls.runInputs).toEqual([
      { asset: "skills", force: false },
      { asset: "claude-md", force: false },
    ]);
  });

  test("--asset skills --json --force are parsed by citty and forwarded to the sync entry", async () => {
    const { calls, command, emitted } = makeCommand();

    await runCommand(command.subCommands.sync, {
      rawArgs: ["--asset", "skills", "--json", "--force"],
    });

    expect(calls.runInputs).toEqual([
      { asset: "skills", force: true, target: undefined },
    ]);
    expect(emitted.calls).toHaveLength(1);
    expect(emitted.calls[0]?.json).toBe(true);
  });
});

describe("createSkillsCommand sync — in-process adapter contract", () => {
  test("forwards an explicit asset, target, force, deps, and json flag", async () => {
    const { calls, command, depsCalls, emitted } = makeCommand();

    await command.subCommands.sync.run({
      args: {
        asset: "skills",
        force: true,
        json: true,
        target: "/repo/.claude/skills",
      },
    });

    expect(depsCalls).toEqual([[]]);
    expect(calls.runInputs).toEqual([
      { asset: "skills", force: true, target: "/repo/.claude/skills" },
    ]);
    expect(calls.runDeps).toEqual([{}]);
    expect(emitted.calls).toHaveLength(1);
    expect(emitted.calls[0]?.json).toBe(true);
  });

  test("expands --asset all into each supported asset with default targets", async () => {
    const { calls, command, emitted } = makeCommand();

    await command.subCommands.sync.run({
      args: { asset: "all", force: false, json: false },
    });

    expect(calls.runInputs).toEqual([
      { asset: "skills", force: false },
      { asset: "claude-md", force: false },
    ]);
    expect(emitted.calls).toHaveLength(2);
    expect(emitted.calls.map((call) => call.renderedText)).toEqual([
      "[skills] → /target/skills\n  created: skills\n  .agents/skills: linked",
      "[claude-md] → /target/claude-md\n  created: claude-md",
    ]);
  });

  test("rejects --asset all with --target before running the sync entry", async () => {
    const { calls, command, emitted, exitCodes, stderr } = makeCommand();

    await expect(
      command.subCommands.sync.run({
        args: {
          asset: "all",
          force: false,
          json: false,
          target: "/repo/custom-target",
        },
      })
    ).rejects.toThrow("exit 2");

    expect(exitCodes).toEqual([2]);
    expect(stderr.join("")).toContain("--asset all");
    expect(calls.runInputs).toEqual([]);
    expect(emitted.calls).toEqual([]);
  });

  test("rejects unknown assets as usage errors before running the sync entry", async () => {
    const { calls, command, emitted, exitCodes, stderr } = makeCommand();

    await expect(
      command.subCommands.sync.run({
        args: {
          asset: "bogus",
          force: false,
          json: false,
          target: "/repo/custom-target",
        },
      })
    ).rejects.toThrow("exit 2");

    expect(exitCodes).toEqual([2]);
    expect(stderr.join("")).toContain("bogus");
    expect(calls.runInputs).toEqual([]);
    expect(emitted.calls).toEqual([]);
  });
});
