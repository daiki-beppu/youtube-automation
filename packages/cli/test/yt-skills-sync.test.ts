import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  lstatSync,
  mkdtempSync,
  readlinkSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { REGISTRY } from "@tayk/core/registry";

import { expectExitCode, expectNonZeroExit, runTayk } from "./run-tayk.ts";

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

describe("core registry — skills.sync entry (ADR-0004 contract)", () => {
  test("declares no deps and a human-readable description", () => {
    const entry = REGISTRY["skills.sync"];

    expect(entry.deps).toEqual([]);
    expect(entry.description.length).toBeGreaterThan(0);
  });

  test("inputSchema parses an asset + target and run returns an ok Result", async () => {
    const tmp = makeTmp("cli-skills-sync-");
    const target = join(tmp, ".claude", "skills");
    const input = REGISTRY["skills.sync"].inputSchema.parse({
      asset: "skills",
      target,
    });

    const result = await REGISTRY["skills.sync"].run(input, {});

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.asset).toBe("skills");
      expect(Array.isArray(result.value.entries)).toBe(true);
      expect(result.value.agentsSkillsLink).toBe("linked");
    }
  });
});

describe("tayk skills sync --asset skills --target <dir>", () => {
  test("exits 0, copies skills, and creates the .agents/skills symlink", () => {
    const tmp = makeTmp("tayk-skills-sync-");
    const target = join(tmp, ".claude", "skills");

    const proc = runTayk(
      {},
      "skills",
      "sync",
      "--asset",
      "skills",
      "--target",
      target
    );

    expectExitCode(proc, 0);
    expect(existsSync(target)).toBe(true);
    const link = join(tmp, ".agents", "skills");
    expect(lstatSync(link).isSymbolicLink()).toBe(true);
    expect(readlinkSync(link)).toBe("../.claude/skills");
  });

  test("--json prints a parseable SkillSyncOutput payload", () => {
    const tmp = makeTmp("tayk-skills-sync-");
    const target = join(tmp, ".claude", "skills");

    const proc = runTayk(
      {},
      "skills",
      "sync",
      "--asset",
      "skills",
      "--target",
      target,
      "--json"
    );

    expectExitCode(proc, 0);
    const parsed = JSON.parse(proc.stdout.toString()) as {
      agentsSkillsLink: string | null;
      asset: string;
      entries: { name: string; result: string }[];
      target: string;
    };
    expect(parsed.asset).toBe("skills");
    expect(Array.isArray(parsed.entries)).toBe(true);
    expect(parsed.agentsSkillsLink).toBe("linked");
  });
});

describe("tayk skills sync --asset claude-md --target <file>", () => {
  test("exits 0 and writes the CLAUDE.md file (AC#5)", () => {
    const tmp = makeTmp("tayk-claude-md-sync-");
    const target = join(tmp, ".claude", "CLAUDE.md");

    const proc = runTayk(
      {},
      "skills",
      "sync",
      "--asset",
      "claude-md",
      "--target",
      target
    );

    expectExitCode(proc, 0);
    expect(existsSync(target)).toBe(true);
  });
});

describe("tayk skills sync --asset all — guard against --target", () => {
  test("exits 2 with a stderr message and writes nothing", () => {
    const tmp = makeTmp("tayk-skills-sync-");
    const target = join(tmp, "x");

    const proc = runTayk(
      {},
      "skills",
      "sync",
      "--asset",
      "all",
      "--target",
      target
    );

    expectExitCode(proc, 2);
    expect(proc.stderr.toString().length).toBeGreaterThan(0);
    expect(existsSync(target)).toBe(false);
  });
});

describe("tayk skills sync — default asset 'all' resolves per-asset default targets", () => {
  test("bare `skills sync` syncs both skills and claude-md under the working dir", () => {
    const cwd = makeTmp("tayk-skills-sync-all-");

    const proc = runTayk({ cwd }, "skills", "sync");

    expectExitCode(proc, 0);
    expect(existsSync(join(cwd, ".claude", "skills"))).toBe(true);
    expect(existsSync(join(cwd, ".claude", "CLAUDE.md"))).toBe(true);
    expect(lstatSync(join(cwd, ".agents", "skills")).isSymbolicLink()).toBe(
      true
    );
  });
});

describe("tayk skills sync — usage errors", () => {
  test("an unknown --asset exits non-zero", () => {
    const tmp = makeTmp("tayk-skills-sync-");
    const proc = runTayk(
      {},
      "skills",
      "sync",
      "--asset",
      "bogus",
      "--target",
      join(tmp, "x")
    );

    expectNonZeroExit(proc);
  });
});
