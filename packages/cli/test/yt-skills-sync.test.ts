import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  lstatSync,
  mkdtempSync,
  readlinkSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Importing core by its package name + ADR-0004 registry subpath from the *cli*
// package is the real cli→core `workspace:*` resolution under test. The
// skills.sync entry lands in the registry as part of #742.
import { REGISTRY } from "@youtube-automation/core/registry";

// Repo root is three levels up from packages/cli/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

// `bunx yt ...` 相当の e2e。citty dispatcher (bin/yt.ts) を実プロセスで起動する。
// runYt は repoRoot を cwd にする (既存 yt-skills.test.ts と同じ)。runYtIn は
// --asset all のデフォルト target (cwd 相対) を temp ディレクトリで検証するため、
// 任意の cwd で起動する変種。
const runYt = (...argv: string[]) =>
  Bun.spawnSync(["bun", "packages/cli/bin/yt.ts", ...argv], { cwd: repoRoot });

const runYtIn = (cwd: string, ...argv: string[]) =>
  Bun.spawnSync(["bun", join(repoRoot, "packages/cli/bin/yt.ts"), ...argv], {
    cwd,
  });

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

describe("core registry — skills.sync entry (ADR-0004 contract)", () => {
  test("declares no deps and a human-readable description", () => {
    // Given the registry entry
    const entry = REGISTRY["skills.sync"];

    // Then deps is the empty declaration and the description lives in core next
    // to the schema (locality).
    expect(entry.deps).toEqual([]);
    expect(entry.description.length).toBeGreaterThan(0);
  });

  test("inputSchema parses an asset + target and run returns an ok Result", async () => {
    // Given an input parsed through the entry's own schema (target → a temp dir)
    const tmp = makeTmp("cli-skills-sync-");
    const target = join(tmp, ".claude", "skills");
    const input = REGISTRY["skills.sync"].inputSchema.parse({
      asset: "skills",
      target,
    });

    // When the entry runs (deps-free, so {} is the full slice)
    const result = await REGISTRY["skills.sync"].run(input, {});

    // Then it succeeds and the payload matches the outputSchema contract.
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.asset).toBe("skills");
      expect(Array.isArray(result.value.entries)).toBe(true);
      expect(result.value.agentsSkillsLink).toBe("linked");
    }
  });
});

describe("yt skills sync --asset skills --target <dir>", () => {
  test("exits 0, copies skills, and creates the .agents/skills symlink", () => {
    // Given a standard-layout target under a temp dir
    const tmp = makeTmp("yt-skills-sync-");
    const target = join(tmp, ".claude", "skills");

    // When `yt skills sync --asset skills --target <dir>` runs
    const proc = runYt(
      "skills",
      "sync",
      "--asset",
      "skills",
      "--target",
      target
    );

    // Then it exits cleanly, the skills land in the target, and the Codex
    // discovery mirror is a relative symlink to ../.claude/skills.
    expect(proc.exitCode).toBe(0);
    expect(existsSync(target)).toBe(true);
    const link = join(tmp, ".agents", "skills");
    expect(lstatSync(link).isSymbolicLink()).toBe(true);
    expect(readlinkSync(link)).toBe("../.claude/skills");
  });

  test("--json prints a parseable SkillSyncOutput payload", () => {
    // Given the same sync with --json
    const tmp = makeTmp("yt-skills-sync-");
    const target = join(tmp, ".claude", "skills");

    // When run with --json
    const proc = runYt(
      "skills",
      "sync",
      "--asset",
      "skills",
      "--target",
      target,
      "--json"
    );

    // Then stdout is the service output as JSON, with no cli reshaping.
    expect(proc.exitCode).toBe(0);
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

describe("yt skills sync --asset claude-md --target <file>", () => {
  test("exits 0 and writes the CLAUDE.md file (AC#5)", () => {
    // Given a target file path under a temp dir
    const tmp = makeTmp("yt-claude-md-sync-");
    const target = join(tmp, ".claude", "CLAUDE.md");

    // When `yt skills sync --asset claude-md --target <file>` runs
    const proc = runYt(
      "skills",
      "sync",
      "--asset",
      "claude-md",
      "--target",
      target
    );

    // Then it exits cleanly and the template is written to the target path.
    expect(proc.exitCode).toBe(0);
    expect(existsSync(target)).toBe(true);
  });
});

describe("yt skills sync --asset all — guard against --target", () => {
  test("exits 2 with a stderr message and writes nothing", () => {
    // Given `--asset all` combined with `--target` (ambiguous: per-asset default
    // targets differ, so a single target would silently misplace an asset).
    const tmp = makeTmp("yt-skills-sync-");
    const target = join(tmp, "x");

    // When run
    const proc = runYt("skills", "sync", "--asset", "all", "--target", target);

    // Then it is a usage error (exit 2) with a non-empty stderr, and the target
    // is never created (the guard fires before any write).
    expect(proc.exitCode).toBe(2);
    expect(proc.stderr.toString().length).toBeGreaterThan(0);
    expect(existsSync(target)).toBe(false);
  });
});

describe("yt skills sync — default asset 'all' resolves per-asset default targets", () => {
  test("bare `skills sync` syncs both skills and claude-md under the working dir", () => {
    // Given a temp working dir (so the cwd-relative default targets are safe to
    // write). `yt skills sync` with no flags defaults asset to 'all'.
    const cwd = makeTmp("yt-skills-sync-all-");

    // When run from that working dir
    const proc = runYtIn(cwd, "skills", "sync");

    // Then both assets reach their per-asset defaults: skills → .claude/skills
    // (+ the .agents/skills mirror) and claude-md → .claude/CLAUDE.md.
    expect(proc.exitCode).toBe(0);
    expect(existsSync(join(cwd, ".claude", "skills"))).toBe(true);
    expect(existsSync(join(cwd, ".claude", "CLAUDE.md"))).toBe(true);
    expect(lstatSync(join(cwd, ".agents", "skills")).isSymbolicLink()).toBe(
      true
    );
  });
});

describe("yt skills sync — usage errors", () => {
  test("an unknown --asset exits non-zero", () => {
    // Given an asset value outside { all, skills, claude-md }
    const tmp = makeTmp("yt-skills-sync-");
    const proc = runYt(
      "skills",
      "sync",
      "--asset",
      "bogus",
      "--target",
      join(tmp, "x")
    );

    // Then the process fails (usage / validation error → non-zero exit).
    expect(proc.exitCode).not.toBe(0);
  });
});
