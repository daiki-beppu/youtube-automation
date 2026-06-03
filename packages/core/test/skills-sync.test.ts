import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Imported by the published package name + ADR 0002 subpath, so the test
// exercises the core `exports` map ("./skills-sync") rather than a relative
// path. A missing/broken subpath export fails resolution here, not in tsc.
import {
  listSkillsService,
  SkillListInputSchema,
} from "@youtube-automation/core/skills-sync";
import type { SkillListInput } from "@youtube-automation/core/skills-sync";

// Repo root is three levels up from packages/core/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

describe("listSkillsService — explicit skillsDir (golden / fixture)", () => {
  // A throwaway fixture with directories created out of order plus a stray
  // file, so one fixture can assert sorting AND directory-only filtering.
  let fixtureDir: string;

  beforeAll(() => {
    fixtureDir = mkdtempSync(join(tmpdir(), "skills-fixture-"));
    for (const name of ["zebra", "alpha", "mango"]) {
      mkdirSync(join(fixtureDir, name));
    }
    writeFileSync(join(fixtureDir, "README.md"), "not a skill directory");
  });

  afterAll(() => {
    rmSync(fixtureDir, { force: true, recursive: true });
  });

  test("returns skill directory names in code-point ascending order", async () => {
    // Given a fixture dir whose subdirectories were created out of order
    // When listSkillsService is called with that dir
    const output = await listSkillsService({ skillsDir: fixtureDir });

    // Then names come back sorted with the default (code-point) comparator,
    // matching the Python `sorted(...)` contract.
    expect(output.skills).toEqual(["alpha", "mango", "zebra"]);
  });

  test("excludes non-directory entries (a skill is a directory)", async () => {
    // Given a fixture dir containing a stray README.md file
    // When listSkillsService is called
    const output = await listSkillsService({ skillsDir: fixtureDir });

    // Then the file is omitted; only directories are reported.
    expect(output.skills).not.toContain("README.md");
    expect(output.skills).toEqual(["alpha", "mango", "zebra"]);
  });

  test("echoes the resolved source directory in the output", async () => {
    // Given an explicit skillsDir
    // When listSkillsService is called
    const output = await listSkillsService({ skillsDir: fixtureDir });

    // Then `source` reports the directory that was read.
    expect(output.source).toBe(fixtureDir);
  });

  test("returns an empty skills array for an empty directory", async () => {
    // Given a freshly created empty directory
    const emptyDir = mkdtempSync(join(tmpdir(), "skills-empty-"));
    try {
      // When listSkillsService is called
      const output = await listSkillsService({ skillsDir: emptyDir });

      // Then skills is an empty array (boundary value), not an error.
      expect(output.skills).toEqual([]);
    } finally {
      rmSync(emptyDir, { force: true, recursive: true });
    }
  });
});

describe("listSkillsService — default resolution (import.meta.url)", () => {
  test("default source resolves to the cli _skills resource", async () => {
    // Given no skillsDir input (default resolution path)
    // When listSkillsService is called
    const output = await listSkillsService({});

    // Then the resolved source points at the packages/cli/_skills resource.
    expect(output.source).toContain("_skills");
  });

  test("default skills match the real .claude/skills directories", async () => {
    // Given the repo's canonical skill source (.claude/skills, reached via the
    // packages/cli/_skills symlink) — read dynamically so the assertion stays
    // correct as skills are added or removed.
    const realSkillsDir = join(repoRoot, ".claude", "skills");
    const expected = readdirSync(realSkillsDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .toSorted();

    // When listSkillsService is called with default resolution
    const output = await listSkillsService({});

    // Then the listing semantically matches the Python `yt-skills list`.
    expect(output.skills).toEqual(expected);
    expect(output.skills.length).toBeGreaterThan(0);
  });
});

describe("listSkillsService — boundary validation", () => {
  test("rejects when skillsDir is not a string (boundary parse())", async () => {
    // Given an input whose skillsDir violates the schema
    const badInput = { skillsDir: 123 } as unknown as SkillListInput;

    // When/Then the service must reject at the schema boundary, not coerce.
    await expect(listSkillsService(badInput)).rejects.toThrow();
  });

  test("rejects when the target directory does not exist (fail fast)", async () => {
    // Given a path that does not exist
    const missingDir = join(tmpdir(), "skills-does-not-exist-xyz-732");

    // When/Then the service surfaces the error rather than returning empty.
    await expect(
      listSkillsService({ skillsDir: missingDir })
    ).rejects.toThrow();
  });
});

describe("SkillListInputSchema — contract", () => {
  test("accepts an empty object (skillsDir is optional)", () => {
    // Given an empty input object
    // When parsed
    const parsed = SkillListInputSchema.parse({});

    // Then it is valid and skillsDir is absent.
    expect(parsed.skillsDir).toBeUndefined();
  });

  test("accepts an explicit string skillsDir", () => {
    // Given an input with a string skillsDir
    // When parsed
    const parsed = SkillListInputSchema.parse({ skillsDir: "/tmp/skills" });

    // Then the value is preserved.
    expect(parsed.skillsDir).toBe("/tmp/skills");
  });

  test("rejects a non-string skillsDir", () => {
    // Given an input with a numeric skillsDir
    // When/Then parse throws.
    expect(() => SkillListInputSchema.parse({ skillsDir: 123 })).toThrow();
  });
});
