import { afterAll, beforeAll, describe, expect, spyOn, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import process from "node:process";

// Importing core by its package name + ADR 0002 subpath from the *cli* package
// is the real cli→core `workspace:*` resolution under test. Broken workspace or
// subpath wiring fails here instead of silently degrading.
import { listSkillsService } from "@youtube-automation/core/skills-sync";

import { runSkillsCli } from "../skills-sync/cli.ts";

// Repo root is three levels up from packages/cli/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

// ADR-0003: listSkillsService returns Result. Unwrap the ok arm so e2e
// assertions can compare the cli rendering against the service's payload.
const listOk = async (input: { skillsDir?: string }) => {
  const r = await listSkillsService(input);
  if (!r.ok) {
    throw new Error(
      `expected an ok Result, got error: ${JSON.stringify(r.error)}`
    );
  }
  return r.value;
};

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
    const expected = await listOk({});
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
    const expected = await listOk({});

    // Then the cli does no reshaping of the service contract.
    expect(parsed.skills).toEqual(expected.skills);
  });
});

describe("runSkillsCli — --skills-dir option propagates to the service", () => {
  // The new --skills-dir flag must travel cli arg → service input → readdir.
  // A fixture dir with out-of-order subdirectories proves the cli is reading
  // *this* dir (not the bundled default) end to end.
  let fixtureDir: string;

  beforeAll(() => {
    fixtureDir = mkdtempSync(join(tmpdir(), "cli-skills-fixture-"));
    for (const name of ["delta", "bravo", "charlie"]) {
      mkdirSync(join(fixtureDir, name));
    }
  });

  afterAll(() => {
    rmSync(fixtureDir, { force: true, recursive: true });
  });

  test("--json lists the directories under the supplied --skills-dir", async () => {
    // Given `list --skills-dir <fixture> --json`
    // When the cli wrapper runs
    const output = await captureStdout(() =>
      runSkillsCli(["list", "--skills-dir", fixtureDir, "--json"])
    );

    // Then stdout reports the fixture's subdirectories (sorted) and echoes the
    // fixture as the source — the option reached the service unchanged.
    const parsed = JSON.parse(output) as { source: string; skills: string[] };
    expect(parsed.skills).toEqual(["bravo", "charlie", "delta"]);
    expect(parsed.source).toBe(fixtureDir);
  });

  test("text output header reports the supplied --skills-dir as source", async () => {
    // Given `list --skills-dir <fixture>` without --json
    // When the cli wrapper runs
    const output = await captureStdout(() =>
      runSkillsCli(["list", "--skills-dir", fixtureDir])
    );

    // Then the header source is the fixture dir, not the bundled default.
    expect(output).toContain(`(source: ${fixtureDir})`);
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

  test("rejects an unknown option", async () => {
    // Given `list` with an unsupported flag
    // When/Then the wrapper surfaces a usage error rather than ignoring it.
    await expect(runSkillsCli(["list", "--bogus"])).rejects.toThrow();
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

  test("`yt-skills list --skills-dir <missing>` exits 1 with an io-domain stderr prefix", () => {
    // Given a `list` against a path that does not exist
    const missingDir = join(tmpdir(), "skills-bin-missing-xyz-824");
    const proc = Bun.spawnSync(
      [
        "bun",
        "packages/cli/bin/yt-skills.ts",
        "list",
        "--skills-dir",
        missingDir,
      ],
      { cwd: repoRoot }
    );

    // Then the service error surfaces as exit 1 (non-quota) with a domain-
    // prefixed stderr line, and nothing is written to stdout.
    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toContain("[io]");
    expect(proc.stdout.toString()).toBe("");
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
