import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  lstatSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Imported by the published package name + ADR-0002 subpath so the test
// exercises the core `exports` map ("./skills-sync") rather than a relative
// path — a missing/broken subpath export fails resolution here, not in tsc.
// syncAssetService / the Sync schemas land in skills-sync as part of #742.
import {
  SkillSyncInputSchema,
  SkillSyncOutputSchema,
  syncAssetService,
} from "@youtube-automation/core/skills-sync";
import type { SkillSyncInput } from "@youtube-automation/core/skills-sync";

// Repo root is three levels up from packages/core/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

// The canonical skill source (.claude/skills, reached via the packages/cli/_skills
// symlink). Read dynamically so the assertions stay correct as skills are added
// or removed — mirrors the listSkillsService default-resolution test.
const expectedSkills = readdirSync(join(repoRoot, ".claude", "skills"), {
  withFileTypes: true,
})
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .toSorted();

// The source of truth for the claude-md asset; the synced file must be a
// byte-for-byte copy of it.
const claudeTemplate = join(repoRoot, ".claude", "CLAUDE.template.md");

// ADR-0003: the service returns Result, never throws. Unwrap the ok arm here so
// happy-path assertions stay focused on the payload; a failed Result is itself a
// test failure (the service was expected to succeed).
const syncOk = async (input: SkillSyncInput) => {
  const r = await syncAssetService(input);
  if (!r.ok) {
    throw new Error(
      `expected an ok Result, got error: ${JSON.stringify(r.error)}`
    );
  }
  return r.value;
};

// Per-test temp dirs, torn down after each case.
const tmpDirs: string[] = [];
const makeTmp = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
};

afterEach(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

describe("syncAssetService — skills asset (standard .claude/skills layout)", () => {
  test("copies every bundled skill directory into the target and reports them created", async () => {
    // Given a fresh standard-layout target (<tmp>/.claude/skills)
    const tmp = makeTmp("skills-sync-");
    const target = join(tmp, ".claude", "skills");

    // When the skills asset is synced there
    const value = await syncOk({ asset: "skills", force: false, target });

    // Then the output echoes the asset + resolved target, and every bundled
    // skill directory is reported as a created entry.
    expect(value.asset).toBe("skills");
    expect(value.target).toBe(resolve(target));
    expect(value.entries.map((e) => e.name).toSorted()).toEqual(expectedSkills);
    expect(value.entries.every((e) => e.result === "created")).toBe(true);
  });

  test("materializes each entry as a real directory (deep copy, not a symlink)", async () => {
    // Given a standard-layout target
    const tmp = makeTmp("skills-sync-");
    const target = join(tmp, ".claude", "skills");

    // When the skills asset is synced
    await syncOk({ asset: "skills", force: false, target });

    // Then a sample skill exists on disk as a real directory — the bundled
    // _skills symlink was dereferenced, matching Python copytree(symlinks=False).
    const [sample] = expectedSkills;
    const copied = join(target, sample as string);
    expect(existsSync(copied)).toBe(true);
    expect(lstatSync(copied).isDirectory()).toBe(true);
    expect(lstatSync(copied).isSymbolicLink()).toBe(false);
  });

  test("creates the .agents/skills mirror as a symlink to ../.claude/skills", async () => {
    // Given a standard-layout target
    const tmp = makeTmp("skills-sync-");
    const target = join(tmp, ".claude", "skills");

    // When the skills asset is synced
    const value = await syncOk({ asset: "skills", force: false, target });

    // Then the Codex discovery path <repo>/.agents/skills is a relative symlink
    // pointing at ../.claude/skills (matches Python _AGENTS_SKILLS_LINK_TARGET).
    const link = join(tmp, ".agents", "skills");
    expect(value.agentsSkillsLink).toBe("linked");
    expect(lstatSync(link).isSymbolicLink()).toBe(true);
    expect(readlinkSync(link)).toBe("../.claude/skills");
  });
});

describe("syncAssetService — skills idempotency and --force", () => {
  test("a second sync without force skips existing entries and the mirror", async () => {
    // Given a target already populated by a first sync
    const tmp = makeTmp("skills-sync-");
    const target = join(tmp, ".claude", "skills");
    await syncOk({ asset: "skills", force: false, target });

    // When syncing again without force
    const second = await syncOk({ asset: "skills", force: false, target });

    // Then nothing is rewritten: every entry and the mirror report skipped.
    expect(second.entries.every((e) => e.result === "skipped")).toBe(true);
    expect(second.agentsSkillsLink).toBe("skipped");
  });

  test("force re-copies entries and re-links the mirror", async () => {
    // Given a target already populated by a first sync
    const tmp = makeTmp("skills-sync-");
    const target = join(tmp, ".claude", "skills");
    await syncOk({ asset: "skills", force: false, target });

    // When syncing again with force: true
    const second = await syncOk({ asset: "skills", force: true, target });

    // Then entries are re-created and the mirror is re-linked, still pointing at
    // ../.claude/skills.
    expect(second.entries.every((e) => e.result === "created")).toBe(true);
    expect(second.agentsSkillsLink).toBe("linked");
    expect(readlinkSync(join(tmp, ".agents", "skills"))).toBe(
      "../.claude/skills"
    );
  });
});

describe("syncAssetService — skills mirror only on the standard layout", () => {
  test("skips the .agents/skills mirror for a non-standard target", async () => {
    // Given a target that is NOT <repo>/.claude/skills (repo root unknowable)
    const tmp = makeTmp("skills-sync-");
    const target = join(tmp, "custom-skills");

    // When the skills asset is synced
    const value = await syncOk({ asset: "skills", force: false, target });

    // Then skills are still copied, but no .agents mirror is attempted (null),
    // and no .agents directory is created as a side effect.
    expect(value.entries.length).toBeGreaterThan(0);
    expect(value.agentsSkillsLink).toBeNull();
    expect(existsSync(join(tmp, ".agents"))).toBe(false);
  });
});

describe("syncAssetService — symlink failure is non-fatal (AC#4)", () => {
  test("returns 'unsupported' and keeps Result ok when the mirror cannot be created", async () => {
    // Given a standard-layout target whose <repo>/.agents path is already a
    // regular file — symlink creation under it fails (ENOTDIR), standing in for
    // a symlink-incapable environment without mocking or chmod/root concerns.
    const tmp = makeTmp("skills-sync-");
    const target = join(tmp, ".claude", "skills");
    writeFileSync(join(tmp, ".agents"), "blocks the mirror");

    // When the skills asset is synced
    const value = await syncOk({ asset: "skills", force: false, target });

    // Then the skills copy still succeeds and the failed mirror degrades to
    // 'unsupported' (warning-only) rather than failing the whole sync.
    expect(value.entries.length).toBeGreaterThan(0);
    expect(value.entries.every((e) => e.result === "created")).toBe(true);
    expect(value.agentsSkillsLink).toBe("unsupported");
  });
});

describe("syncAssetService — claude-md asset (single file, AC#5)", () => {
  test("copies CLAUDE.template.md to the target file path and reports it created", async () => {
    // Given a target file path (<tmp>/.claude/CLAUDE.md)
    const tmp = makeTmp("claude-md-sync-");
    const target = join(tmp, ".claude", "CLAUDE.md");

    // When the claude-md asset is synced
    const value = await syncOk({ asset: "claude-md", force: false, target });

    // Then the output echoes the asset + resolved target, the file is a
    // byte-for-byte copy of the bundled template, and no skills mirror applies.
    expect(value.asset).toBe("claude-md");
    expect(value.target).toBe(resolve(target));
    expect(existsSync(target)).toBe(true);
    expect(readFileSync(target, "utf-8")).toBe(
      readFileSync(claudeTemplate, "utf-8")
    );
    expect(value.entries).toEqual([{ name: "CLAUDE.md", result: "created" }]);
    expect(value.agentsSkillsLink).toBeNull();
  });

  test("a second claude-md sync without force skips the file", async () => {
    // Given a target already written by a first sync
    const tmp = makeTmp("claude-md-sync-");
    const target = join(tmp, ".claude", "CLAUDE.md");
    await syncOk({ asset: "claude-md", force: false, target });

    // When syncing again without force
    const second = await syncOk({ asset: "claude-md", force: false, target });

    // Then the single entry is skipped (idempotent).
    expect(second.entries).toEqual([{ name: "CLAUDE.md", result: "skipped" }]);
  });
});

describe("syncAssetService — error contract (Result, never throws)", () => {
  test("resolves (does not reject) even on invalid input", async () => {
    // Given an asset outside the schema enum
    // When/Then the call settles with a value instead of rejecting — failure is
    // surfaced through Result, not by throwing (ADR-0003 §1).
    await expect(
      syncAssetService({ asset: "bogus" } as unknown as SkillSyncInput)
    ).resolves.toBeDefined();
  });

  test("returns a validation-domain error for an unknown asset", async () => {
    // Given an asset value the schema does not allow
    const r = await syncAssetService({
      asset: "workflow-cheatsheet",
    } as unknown as SkillSyncInput);

    // Then the boundary parse() fails into a validation-domain error.
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.domain).toBe("validation");
    }
  });

  test("rejects asset 'all' at the service boundary (expansion is a CLI concern)", async () => {
    // Given asset 'all' — the CLI expands it; the service contract never sees it
    const r = await syncAssetService({
      asset: "all",
    } as unknown as SkillSyncInput);

    // Then it is a validation-domain error, not a silent no-op.
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.domain).toBe("validation");
    }
  });

  test("returns a validation-domain error when target is not a string", async () => {
    // Given a non-string target
    const r = await syncAssetService({
      asset: "skills",
      target: 123,
    } as unknown as SkillSyncInput);

    // Then the boundary parse() rejects it (ZodError → domain "validation").
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.domain).toBe("validation");
    }
  });
});

describe("SkillSyncInputSchema — contract", () => {
  test("defaults force to false and leaves target undefined when omitted", () => {
    // Given only an asset
    // When parsed
    const parsed = SkillSyncInputSchema.parse({ asset: "skills" });

    // Then force defaults to false and target stays absent (CLI forwards both;
    // the service fills the per-asset default target).
    expect(parsed.force).toBe(false);
    expect(parsed.target).toBeUndefined();
  });

  test("accepts the claude-md asset (AC#5: claude-md is a supported asset)", () => {
    // Given the claude-md asset
    // When parsed
    const parsed = SkillSyncInputSchema.parse({ asset: "claude-md" });

    // Then it is valid.
    expect(parsed.asset).toBe("claude-md");
  });

  test("preserves an explicit target and force", () => {
    // Given an explicit target + force
    // When parsed
    const parsed = SkillSyncInputSchema.parse({
      asset: "skills",
      force: true,
      target: "/tmp/skills",
    });

    // Then the values are preserved.
    expect(parsed.force).toBe(true);
    expect(parsed.target).toBe("/tmp/skills");
  });

  test("rejects asset 'all' (the service enum is skills | claude-md)", () => {
    // Given asset 'all' (a CLI-only sugar, not a service asset)
    // When/Then parse throws.
    expect(() => SkillSyncInputSchema.parse({ asset: "all" })).toThrow();
  });

  test("rejects an unknown asset value", () => {
    // Given an asset outside the enum
    // When/Then parse throws.
    expect(() =>
      SkillSyncInputSchema.parse({ asset: "workflow-cheatsheet" })
    ).toThrow();
  });

  test("rejects a non-boolean force", () => {
    // Given a non-boolean force
    // When/Then parse throws (no coercion).
    expect(() =>
      SkillSyncInputSchema.parse({ asset: "skills", force: "yes" })
    ).toThrow();
  });

  test("rejects unknown keys (.strict())", () => {
    // Given an input carrying a key outside the schema
    // When/Then the strict object rejects it (ADR-0003 §8).
    expect(() =>
      SkillSyncInputSchema.parse({ asset: "skills", extra: true })
    ).toThrow();
  });
});

describe("SkillSyncOutputSchema — contract", () => {
  // A well-formed baseline payload reused across the rejection cases.
  const validOutput = {
    agentsSkillsLink: "linked",
    asset: "skills",
    entries: [{ name: "alpha", result: "created" }],
    target: "/tmp/.claude/skills",
  };

  test("accepts a well-formed payload with a linked mirror", () => {
    // Given an output matching the schema shape
    // When parsed
    const parsed = SkillSyncOutputSchema.parse(validOutput);

    // Then it round-trips unchanged.
    expect(parsed.agentsSkillsLink).toBe("linked");
    expect(parsed.entries).toEqual([{ name: "alpha", result: "created" }]);
  });

  test("accepts a null agentsSkillsLink (file asset / non-standard layout)", () => {
    // Given an output whose mirror is not applicable
    // When parsed
    const parsed = SkillSyncOutputSchema.parse({
      ...validOutput,
      agentsSkillsLink: null,
    });

    // Then null is a valid mirror state.
    expect(parsed.agentsSkillsLink).toBeNull();
  });

  test("rejects an invalid agentsSkillsLink value", () => {
    // Given an out-of-domain mirror state
    // When/Then parse throws.
    expect(() =>
      SkillSyncOutputSchema.parse({ ...validOutput, agentsSkillsLink: "bogus" })
    ).toThrow();
  });

  test("rejects an invalid entry result value", () => {
    // Given an entry with a result outside created | skipped
    // When/Then parse throws.
    expect(() =>
      SkillSyncOutputSchema.parse({
        ...validOutput,
        entries: [{ name: "alpha", result: "bogus" }],
      })
    ).toThrow();
  });

  test("rejects unknown keys (.strict())", () => {
    // Given an output carrying a key outside the schema
    // When/Then the strict object rejects it (both Input and Output are strict).
    expect(() =>
      SkillSyncOutputSchema.parse({ ...validOutput, extra: true })
    ).toThrow();
  });
});
