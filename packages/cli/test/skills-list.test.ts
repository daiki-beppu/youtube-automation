import { describe, expect, spyOn, test } from "bun:test";
import { resolve } from "node:path";
import process from "node:process";

// Importing core by its package name + ADR 0002 subpath from the *cli* package
// is the real cli→core `workspace:*` resolution under test. Broken workspace or
// subpath wiring fails here instead of silently degrading.
import { listSkillsService } from "@youtube-automation/core/skills-sync";

import { runSkillsCli } from "../skills-sync/cli.ts";

// Repo root is three levels up from packages/cli/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

// Captures everything written to stdout (console.log routes through here too)
// for the duration of `fn`, then restores the original writer.
const captureStdout = async (fn: () => Promise<void>): Promise<string> => {
  const writes: string[] = [];
  const spy = spyOn(process.stdout, "write").mockImplementation((chunk) => {
    writes.push(
      typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk)
    );
    return true;
  });

  try {
    await fn();
  } finally {
    spy.mockRestore();
  }

  return writes.join("");
};

describe("runSkillsCli — text output (default)", () => {
  test("prints the count header matching the Python `yt-skills list` format", async () => {
    // Given the `list` subcommand with no format flag
    // When the cli wrapper runs
    const output = await captureStdout(() => runSkillsCli(["list"]));

    // Then the header line matches `同梱スキル <N> 件 (source: <path>)`.
    expect(output).toMatch(/^同梱スキル \d+ 件 \(source: .+\)$/mu);
  });

  test("prints each skill as an indented bullet line", async () => {
    // Given the `list` subcommand
    // When the cli wrapper runs
    const output = await captureStdout(() => runSkillsCli(["list"]));

    // Then at least one skill appears as a `  - <name>` line, and every listed
    // skill from the service is present in the rendered text.
    const expected = await listSkillsService({});
    expect(output).toMatch(/^ {2}- .+$/mu);
    for (const skill of expected.skills) {
      expect(output).toContain(`  - ${skill}`);
    }
  });
});

describe("runSkillsCli — json output (--json)", () => {
  test("prints valid JSON carrying source and skills", async () => {
    // Given the `list` subcommand with --json
    // When the cli wrapper runs
    const output = await captureStdout(() => runSkillsCli(["list", "--json"]));

    // Then stdout is parseable JSON with the service's output shape.
    const parsed = JSON.parse(output) as { source: string; skills: string[] };
    expect(typeof parsed.source).toBe("string");
    expect(Array.isArray(parsed.skills)).toBe(true);
  });

  test("json skills match the service output exactly", async () => {
    // Given --json output
    const output = await captureStdout(() => runSkillsCli(["list", "--json"]));
    const parsed = JSON.parse(output) as { source: string; skills: string[] };

    // When compared with the service result
    const expected = await listSkillsService({});

    // Then the cli does no reshaping of the service contract.
    expect(parsed.skills).toEqual(expected.skills);
  });
});

describe("runSkillsCli — usage errors (fail fast)", () => {
  test("rejects an unknown subcommand", async () => {
    // Given an unsupported subcommand
    // When/Then the wrapper surfaces a usage error instead of guessing.
    await expect(runSkillsCli(["sync"])).rejects.toThrow();
  });

  test("rejects when no subcommand is provided", async () => {
    // Given empty argv
    // When/Then the wrapper surfaces a usage error.
    await expect(runSkillsCli([])).rejects.toThrow();
  });
});

describe("yt-skills bin — end-to-end (bunx entry)", () => {
  test("`yt-skills list` exits 0 and prints the header", () => {
    // Given the bin invoked exactly as `bunx yt-skills list` would
    const proc = Bun.spawnSync(
      ["bun", "packages/cli/bin/yt-skills.ts", "list"],
      { cwd: repoRoot }
    );

    // Then it exits cleanly and prints the count header.
    expect(proc.exitCode).toBe(0);
    expect(proc.stdout.toString()).toContain("同梱スキル");
  });

  test("`yt-skills list --json` exits 0 and prints a skills array", () => {
    // Given the bin invoked with --json
    const proc = Bun.spawnSync(
      ["bun", "packages/cli/bin/yt-skills.ts", "list", "--json"],
      { cwd: repoRoot }
    );

    // Then it exits cleanly and stdout is JSON with a skills array.
    expect(proc.exitCode).toBe(0);
    const parsed = JSON.parse(proc.stdout.toString()) as { skills: string[] };
    expect(Array.isArray(parsed.skills)).toBe(true);
  });

  test("`yt-skills <unknown>` exits non-zero", () => {
    // Given an unsupported subcommand at the bin layer
    const proc = Bun.spawnSync(
      ["bun", "packages/cli/bin/yt-skills.ts", "bogus"],
      { cwd: repoRoot }
    );

    // Then the process fails (usage error propagates to a non-zero exit).
    expect(proc.exitCode).not.toBe(0);
  });
});
