import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Importing core by its package name + ADR-0004 registry subpath from the *cli*
// package is the real cli→core `workspace:*` resolution under test. Broken
// workspace or subpath wiring fails here instead of silently degrading.
import { REGISTRY } from "@youtube-automation/core/registry";

// Repo root is three levels up from packages/cli/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

// `bunx yt ...` 相当の e2e。citty dispatcher (bin/yt.ts) を実プロセスで起動する。
const runYt = (...argv: string[]) =>
  Bun.spawnSync(["bun", "packages/cli/bin/yt.ts", ...argv], { cwd: repoRoot });
const CLI_E2E_TIMEOUT_MS = 10_000;

// ADR-0003: registry entry の run は Result を返す。ok arm を unwrap して e2e の
// 期待値 (service が見るのと同じ payload) を得る。
const listOk = async (input: { skillsDir?: string }) => {
  const r = await REGISTRY["skills.list"].run(input, {});
  if (!r.ok) {
    throw new Error(
      `expected an ok Result, got error: ${JSON.stringify(r.error)}`
    );
  }
  return r.value;
};

describe("core registry — skills.list entry (ADR-0004 contract)", () => {
  test("declares no deps and a human-readable description", () => {
    // Given the registry entry
    const entry = REGISTRY["skills.list"];

    // Then deps is the empty declaration (typed Pick<DepsMap, never>) and the
    // description lives in core next to the schema (locality).
    expect(entry.deps).toEqual([]);
    expect(entry.description.length).toBeGreaterThan(0);
  });

  test("inputSchema accepts {} and run returns an ok Result", async () => {
    // Given an empty input parsed through the entry's own schema
    const input = REGISTRY["skills.list"].inputSchema.parse({});

    // When the entry runs
    const output = await listOk(input);

    // Then the output matches the outputSchema contract.
    expect(Array.isArray(output.skills)).toBe(true);
    expect(typeof output.source).toBe("string");
  });
});

describe("yt skills list — text output (default)", () => {
  test(
    "exits 0 and prints the count header matching the Python `yt-skills list` format",
    () => {
      // Given `yt skills list` with no format flag
      const proc = runYt("skills", "list");

      // Then it exits cleanly and the header matches `同梱スキル <N> 件 (source: <path>)`.
      expect(proc.exitCode).toBe(0);
      expect(proc.stdout.toString()).toMatch(
        /^同梱スキル \d+ 件 \(source: .+\)$/mu
      );
    },
    CLI_E2E_TIMEOUT_MS
  );

  test(
    "prints each skill as an indented bullet line",
    async () => {
      // Given `yt skills list`
      const proc = runYt("skills", "list");
      const output = proc.stdout.toString();

      // Then every skill from the registry entry appears as a `  - <name>` line.
      const expected = await listOk({});
      expect(output).toMatch(/^ {2}- .+$/mu);
      for (const skill of expected.skills) {
        expect(output).toContain(`  - ${skill}`);
      }
    },
    CLI_E2E_TIMEOUT_MS
  );
});

describe("yt skills list --json", () => {
  test(
    "prints valid JSON carrying source and skills, with no cli reshaping",
    async () => {
      // Given `yt skills list --json`
      const proc = runYt("skills", "list", "--json");

      // Then stdout is parseable JSON matching the registry entry's output.
      expect(proc.exitCode).toBe(0);
      const parsed = JSON.parse(proc.stdout.toString()) as {
        skills: string[];
        source: string;
      };
      const expected = await listOk({});
      expect(parsed.skills).toEqual(expected.skills);
      expect(typeof parsed.source).toBe("string");
    },
    CLI_E2E_TIMEOUT_MS
  );
});

describe("yt skills list --skills-dir — option propagates to the service", () => {
  // The --skills-dir flag must travel citty arg → registry entry → readdir.
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

  test(
    "--json lists the directories under the supplied --skills-dir",
    () => {
      // Given `yt skills list --skills-dir <fixture> --json`
      const proc = runYt(
        "skills",
        "list",
        "--skills-dir",
        fixtureDir,
        "--json"
      );

      // Then stdout reports the fixture's subdirectories (sorted) and echoes the
      // fixture as the source — the option reached the service unchanged.
      expect(proc.exitCode).toBe(0);
      const parsed = JSON.parse(proc.stdout.toString()) as {
        skills: string[];
        source: string;
      };
      expect(parsed.skills).toEqual(["bravo", "charlie", "delta"]);
      expect(parsed.source).toBe(fixtureDir);
    },
    CLI_E2E_TIMEOUT_MS
  );

  test(
    "text output header reports the supplied --skills-dir as source",
    () => {
      // Given `yt skills list --skills-dir <fixture>` without --json
      const proc = runYt("skills", "list", "--skills-dir", fixtureDir);

      // Then the header source is the fixture dir, not the bundled default.
      expect(proc.exitCode).toBe(0);
      expect(proc.stdout.toString()).toContain(`(source: ${fixtureDir})`);
    },
    CLI_E2E_TIMEOUT_MS
  );
});

describe("yt skills list — error path (run-command helper)", () => {
  test(
    "missing --skills-dir exits 1 with an io-domain stderr prefix and empty stdout",
    () => {
      // Given a `list` against a path that does not exist
      const missingDir = join(tmpdir(), "skills-bin-missing-xyz-842");
      const proc = runYt("skills", "list", "--skills-dir", missingDir);

      // Then the ServiceError surfaces via lib/run-command.ts as exit 1
      // (non-quota) with the `[domain] message` stderr line (ADR-0004 §4).
      expect(proc.exitCode).toBe(1);
      expect(proc.stderr.toString()).toContain("[io]");
      expect(proc.stdout.toString()).toBe("");
    },
    CLI_E2E_TIMEOUT_MS
  );
});

describe("yt dispatcher — citty usage surface", () => {
  test(
    "`yt --help` exits 0 and lists the skills subcommand",
    () => {
      // Given the dispatcher invoked with --help
      const proc = runYt("--help");

      // Then the sub-command tree is shown (AC: `bunx yt --help`).
      expect(proc.exitCode).toBe(0);
      expect(proc.stdout.toString()).toContain("skills");
    },
    CLI_E2E_TIMEOUT_MS
  );

  test(
    "`yt skills <unknown>` exits non-zero",
    () => {
      // Given an unsupported subcommand under skills
      const proc = runYt("skills", "bogus");

      // Then the process fails (usage error propagates to a non-zero exit).
      expect(proc.exitCode).not.toBe(0);
    },
    CLI_E2E_TIMEOUT_MS
  );
});
