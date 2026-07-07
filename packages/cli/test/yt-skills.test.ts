import { describe, expect, test } from "bun:test";
import { join, resolve } from "node:path";

import { err, ok } from "@youtube-automation/core";
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

const listOutput: SkillListOutput = {
  skills: ["bravo", "charlie", "delta"],
  source: "/fixtures/skills",
};

type EmptyDeps = Pick<DepsMap, never>;
type SkillListEntry = RegistryEntry<
  typeof SkillListInputSchema,
  typeof SkillListOutputSchema
>;
type SkillSyncEntry = RegistryEntry<
  typeof SkillSyncInputSchema,
  typeof SkillSyncOutputSchema
>;

const makeListEntry = () => {
  const calls: {
    runDeps: EmptyDeps[];
    runInputs: SkillListInput[];
  } = { runDeps: [], runInputs: [] };

  const entry = {
    deps: [] as const,
    description: "List bundled skills",
    inputSchema: SkillListInputSchema,
    outputSchema: SkillListOutputSchema,
    run(input: SkillListInput, deps: EmptyDeps) {
      calls.runInputs.push(input);
      calls.runDeps.push(deps);
      return Promise.resolve(ok(listOutput));
    },
  } satisfies SkillListEntry;

  return { calls, entry };
};

const makeFailingListEntry = () => {
  const calls: {
    runDeps: EmptyDeps[];
    runInputs: SkillListInput[];
  } = { runDeps: [], runInputs: [] };

  const entry = {
    deps: [] as const,
    description: "List bundled skills",
    inputSchema: SkillListInputSchema,
    outputSchema: SkillListOutputSchema,
    run(input: SkillListInput, deps: EmptyDeps) {
      calls.runInputs.push(input);
      calls.runDeps.push(deps);
      return Promise.resolve(
        err({ domain: "io", message: "missing skills directory" })
      );
    },
  } satisfies SkillListEntry;

  return { calls, entry };
};

const makeUnusedSyncEntry = () =>
  ({
    deps: [] as const,
    description: "Sync bundled assets",
    inputSchema: SkillSyncInputSchema,
    outputSchema: SkillSyncOutputSchema,
    run(
      _input: SkillSyncInput,
      _deps: EmptyDeps
    ): Promise<Result<SkillSyncOutput, ServiceError>> {
      return Promise.reject(
        new Error("sync entry should not run in list tests")
      );
    },
  }) satisfies SkillSyncEntry;

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

describe("core registry — skills.list entry (ADR-0004 contract)", () => {
  test("declares no deps and a human-readable description", () => {
    const entry = REGISTRY["skills.list"];

    expect(entry.deps).toEqual([]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk skills — dispatcher smoke", () => {
  test(
    "`tayk --help` exits 0 and lists the skills subcommand",
    () => {
      const proc = runTayk("--help");

      expect(proc.exitCode).toBe(0);
      expect(proc.stdout.toString()).toContain("skills");
    },
    CLI_SMOKE_TIMEOUT_MS
  );

  test(
    "`tayk skills --help` exits 0 and lists child commands",
    () => {
      const proc = runTayk("skills", "--help");

      expect(proc.exitCode).toBe(0);
      expect(proc.stdout.toString()).toContain("list");
      expect(proc.stdout.toString()).toContain("sync");
    },
    CLI_SMOKE_TIMEOUT_MS
  );
});

describe("createSkillsCommand list — in-process adapter contract", () => {
  test("forwards --skills-dir, deps, and json flag to the list entry", async () => {
    const { calls, entry: listEntry } = makeListEntry();
    const emitted = makeEmitResult();
    const depsCalls: (readonly never[])[] = [];
    const command = createSkillsCommand({
      emitResult: emitted.emitResult,
      exit: (code: number) => {
        throw new Error(`unexpected exit ${code}`);
      },
      listEntry,
      resolveDeps: (deps: readonly never[]) => {
        depsCalls.push([...deps]);
        return Promise.resolve({});
      },
      syncEntry: makeUnusedSyncEntry(),
      writeStderr: (message: string) => {
        throw new Error(`unexpected stderr: ${message}`);
      },
    });

    await command.subCommands.list.run({
      args: { json: true, "skills-dir": "/fixtures/skills" },
    });

    expect(depsCalls).toEqual([[]]);
    expect(calls.runInputs).toEqual([{ skillsDir: "/fixtures/skills" }]);
    expect(calls.runDeps).toEqual([{}]);
    expect(emitted.calls).toHaveLength(1);
    expect(emitted.calls[0]?.json).toBe(true);
  });

  test("keeps text output rendering in the CLI adapter", async () => {
    const { entry: listEntry } = makeListEntry();
    const emitted = makeEmitResult();
    const command = createSkillsCommand({
      emitResult: emitted.emitResult,
      exit: (code: number) => {
        throw new Error(`unexpected exit ${code}`);
      },
      listEntry,
      resolveDeps: () => Promise.resolve({}),
      syncEntry: makeUnusedSyncEntry(),
      writeStderr: (message: string) => {
        throw new Error(`unexpected stderr: ${message}`);
      },
    });

    await command.subCommands.list.run({
      args: { json: false },
    });

    expect(emitted.calls[0]?.renderedText).toContain(
      "同梱スキル 3 件 (source: /fixtures/skills)"
    );
    expect(emitted.calls[0]?.renderedText).toContain("  - bravo");
    expect(emitted.calls[0]?.renderedText).toContain("  - delta");
  });

  test("forwards list entry error Results to emitResult", async () => {
    const { calls, entry: listEntry } = makeFailingListEntry();
    const emitted = makeEmitResult();
    const depsCalls: (readonly never[])[] = [];
    const command = createSkillsCommand({
      emitResult: emitted.emitResult,
      exit: (code: number) => {
        throw new Error(`unexpected exit ${code}`);
      },
      listEntry,
      resolveDeps: (deps: readonly never[]) => {
        depsCalls.push([...deps]);
        return Promise.resolve({});
      },
      syncEntry: makeUnusedSyncEntry(),
      writeStderr: (message: string) => {
        throw new Error(`unexpected stderr: ${message}`);
      },
    });

    await command.subCommands.list.run({
      args: { json: true, "skills-dir": "/missing/skills" },
    });

    expect(depsCalls).toEqual([[]]);
    expect(calls.runInputs).toEqual([{ skillsDir: "/missing/skills" }]);
    expect(calls.runDeps).toEqual([{}]);
    expect(emitted.calls).toEqual([
      {
        json: true,
        renderedText: undefined,
        result: {
          error: { domain: "io", message: "missing skills directory" },
          ok: false,
        },
      },
    ]);
  });

  test("--json flag is parsed by citty parser via runCommand for list subcommand", async () => {
    const { entry } = makeListEntry();
    const emitted = makeEmitResult();
    const command = createSkillsCommand({
      emitResult: emitted.emitResult,
      exit: () => {
        throw new Error("exit");
      },
      listEntry: entry,
      resolveDeps: () => Promise.resolve({}),
      syncEntry: makeUnusedSyncEntry(),
      writeStderr: () => {},
    });

    await runCommand(command.subCommands.list, { rawArgs: ["--json"] });

    expect(emitted.calls).toHaveLength(1);
    expect(emitted.calls[0]?.json).toBe(true);
  });
});
