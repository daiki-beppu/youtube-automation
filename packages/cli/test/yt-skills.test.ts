import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { REGISTRY } from "@tayk/core/registry";

import { expectExitCode, expectNonZeroExit, runTayk } from "./run-tayk.ts";

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
    const entry = REGISTRY["skills.list"];

    expect(entry.deps).toEqual([]);
    expect(entry.description.length).toBeGreaterThan(0);
  });

  test("inputSchema accepts {} and run returns an ok Result", async () => {
    const input = REGISTRY["skills.list"].inputSchema.parse({});

    const output = await listOk(input);

    expect(Array.isArray(output.skills)).toBe(true);
    expect(typeof output.source).toBe("string");
  });
});

describe("tayk skills list — text output (default)", () => {
  test("exits 0 and prints the count header matching the skills list format", () => {
    const proc = runTayk({}, "skills", "list");

    expectExitCode(proc, 0);
    expect(proc.stdout.toString()).toMatch(
      /^同梱スキル \d+ 件 \(source: .+\)$/mu
    );
  });

  test("prints each skill as an indented bullet line", async () => {
    const proc = runTayk({}, "skills", "list");
    const output = proc.stdout.toString();

    const expected = await listOk({});
    expect(output).toMatch(/^ {2}- .+$/mu);
    for (const skill of expected.skills) {
      expect(output).toContain(`  - ${skill}`);
    }
  });
});

describe("tayk skills list --json", () => {
  test("prints valid JSON carrying source and skills, with no cli reshaping", async () => {
    const proc = runTayk({}, "skills", "list", "--json");

    expectExitCode(proc, 0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      skills: string[];
      source: string;
    };
    const expected = await listOk({});
    expect(parsed.skills).toEqual(expected.skills);
    expect(typeof parsed.source).toBe("string");
  });
});

describe("tayk skills list --skills-dir — option propagates to the service", () => {
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

  test("--json lists the directories under the supplied --skills-dir", () => {
    const proc = runTayk(
      {},
      "skills",
      "list",
      "--skills-dir",
      fixtureDir,
      "--json"
    );

    expectExitCode(proc, 0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      skills: string[];
      source: string;
    };
    expect(parsed.skills).toEqual(["bravo", "charlie", "delta"]);
    expect(parsed.source).toBe(fixtureDir);
  });

  test("text output header reports the supplied --skills-dir as source", () => {
    const proc = runTayk({}, "skills", "list", "--skills-dir", fixtureDir);

    expectExitCode(proc, 0);
    expect(proc.stdout.toString()).toContain(`(source: ${fixtureDir})`);
  });
});

describe("tayk skills list — error path (run-command helper)", () => {
  test("missing --skills-dir exits 1 with an io-domain stderr prefix and empty stdout", () => {
    const missingDir = join(tmpdir(), "skills-bin-missing-xyz-842");
    const proc = runTayk({}, "skills", "list", "--skills-dir", missingDir);

    expectExitCode(proc, 1);
    expect(proc.stderr.toString()).toContain("[io]");
    expect(proc.stdout.toString()).toBe("");
  });
});

describe("tayk dispatcher — citty usage surface", () => {
  test("`tayk --help` exits 0 and lists the skills subcommand", () => {
    const proc = runTayk({}, "--help");

    expectExitCode(proc, 0);
    expect(proc.stdout.toString()).toContain("skills");
  });

  test("`tayk skills <unknown>` exits non-zero", () => {
    const proc = runTayk({}, "skills", "bogus");

    expectNonZeroExit(proc);
  });
});
