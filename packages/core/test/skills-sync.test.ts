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
  SkillListOutputSchema,
} from "@youtube-automation/core/skills-sync";
import type { SkillListInput } from "@youtube-automation/core/skills-sync";

// Repo root is three levels up from packages/core/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

// ADR-0003: the service returns Result, never throws. Unwrap the ok arm here so
// happy-path assertions stay focused on the payload; a failed Result is itself a
// test failure (the service was expected to succeed).
const listOk = async (input: SkillListInput) => {
  const r = await listSkillsService(input);
  if (!r.ok) {
    throw new Error(
      `expected an ok Result, got error: ${JSON.stringify(r.error)}`
    );
  }
  return r.value;
};

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

  test("returns ok Result with skill names in code-point ascending order", async () => {
    // Given a fixture dir whose subdirectories were created out of order
    // When listSkillsService is called with that dir
    const value = await listOk({ skillsDir: fixtureDir });

    // Then names come back sorted with the default (code-point) comparator,
    // matching the Python `sorted(...)` contract.
    expect(value.skills).toEqual(["alpha", "mango", "zebra"]);
  });

  test("excludes non-directory entries (a skill is a directory)", async () => {
    // Given a fixture dir containing a stray README.md file
    // When listSkillsService is called
    const value = await listOk({ skillsDir: fixtureDir });

    // Then the file is omitted; only directories are reported.
    expect(value.skills).not.toContain("README.md");
    expect(value.skills).toEqual(["alpha", "mango", "zebra"]);
  });

  test("echoes the resolved source directory in the output", async () => {
    // Given an explicit skillsDir
    // When listSkillsService is called
    const value = await listOk({ skillsDir: fixtureDir });

    // Then `source` reports the directory that was read.
    expect(value.source).toBe(fixtureDir);
  });

  test("returns an empty skills array for an empty directory", async () => {
    // Given a freshly created empty directory
    const emptyDir = mkdtempSync(join(tmpdir(), "skills-empty-"));
    try {
      // When listSkillsService is called
      const value = await listOk({ skillsDir: emptyDir });

      // Then skills is an empty array (boundary value), not an error.
      expect(value.skills).toEqual([]);
    } finally {
      rmSync(emptyDir, { force: true, recursive: true });
    }
  });
});

describe("listSkillsService — default resolution (import.meta.url)", () => {
  test("default source resolves to the cli _skills resource", async () => {
    // Given no skillsDir input (default resolution path)
    // When listSkillsService is called
    const value = await listOk({});

    // Then the resolved source points at the packages/cli/_skills resource.
    expect(value.source).toContain("_skills");
  });

  test("an explicit undefined skillsDir resolves the same as an absent one", async () => {
    // The cli always forwards `{ skillsDir }` (no defensive ternary), so the
    // service must treat `{ skillsDir: undefined }` exactly like `{}` and fall
    // back to the bundled default — guarding the cli input simplification.
    const fromUndefined = await listOk({ skillsDir: undefined });
    const fromAbsent = await listOk({});

    expect(fromUndefined.source).toBe(fromAbsent.source);
    expect(fromUndefined.skills).toEqual(fromAbsent.skills);
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
    const value = await listOk({});

    // Then the listing semantically matches the Python `yt-skills list`.
    expect(value.skills).toEqual(expected);
    expect(value.skills.length).toBeGreaterThan(0);
  });
});

describe("listSkillsService — error contract (Result, never throws)", () => {
  test("resolves (does not reject) even on a failing read", async () => {
    // Given a path that does not exist
    const missingDir = join(tmpdir(), "skills-does-not-exist-xyz-824");

    // When/Then the call settles with a value instead of rejecting — the
    // service surfaces failure through Result, not by throwing (ADR-0003 §1).
    await expect(
      listSkillsService({ skillsDir: missingDir })
    ).resolves.toBeDefined();
  });

  test("returns an io-domain error when the target directory is missing", async () => {
    // Given a path that does not exist
    const missingDir = join(tmpdir(), "skills-does-not-exist-xyz-824");

    // When listSkillsService is called
    const r = await listSkillsService({ skillsDir: missingDir });

    // Then the Result is the error arm in the io domain (readdir ENOENT is an
    // unprefixed Error, which toServiceError routes to `io`).
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.domain).toBe("io");
      expect(r.error.message.length).toBeGreaterThan(0);
    }
  });

  test("returns a validation-domain error when skillsDir is not a string", async () => {
    // Given an input whose skillsDir violates the schema
    const badInput = { skillsDir: 123 } as unknown as SkillListInput;

    // When listSkillsService is called
    const r = await listSkillsService(badInput);

    // Then the boundary parse() fails into a validation-domain error rather
    // than coercing or throwing (ZodError → domain "validation").
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.domain).toBe("validation");
    }
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

  test("rejects unknown keys (.strict())", () => {
    // Given an input carrying a key outside the schema
    // When/Then the strict object rejects it rather than silently dropping it
    // (ADR-0003 §8: `.strict()` makes unknown keys an error).
    expect(() =>
      SkillListInputSchema.parse({ extra: true, skillsDir: "/tmp/skills" })
    ).toThrow();
  });
});

describe("SkillListOutputSchema — contract", () => {
  test("accepts a well-formed output payload", () => {
    // Given an output object matching the schema shape
    // When parsed
    const parsed = SkillListOutputSchema.parse({
      skills: ["alpha", "beta"],
      source: "/tmp/skills",
    });

    // Then it round-trips unchanged.
    expect(parsed.skills).toEqual(["alpha", "beta"]);
    expect(parsed.source).toBe("/tmp/skills");
  });

  test("rejects unknown keys (.strict())", () => {
    // Given an output carrying a key outside the schema
    // When/Then the strict object rejects it rather than silently dropping it.
    // Both Input and Output must be strict per ADR-0003 §8 / canonical template;
    // this guards against the Output schema regressing to a non-strict object.
    expect(() =>
      SkillListOutputSchema.parse({
        extra: true,
        skills: ["alpha"],
        source: "/tmp/skills",
      })
    ).toThrow();
  });
});
