import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import {
  cpSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, relative, resolve } from "node:path";

// Guards the #742 distribution contract end-to-end: `_skills` / `_claude_md` are
// committed as symlinks into `.claude/`, and pack strips symlinks — so without
// the prepack materialization the published tarball ships neither asset (the
// original REJECT: pack emitted 8 files, both assets absent). This test packs
// the real package and asserts both assets land as real files.

// packages/cli/test → packages/cli, and two more up → repo root.
const sourceCliDir = resolve(import.meta.dir, "..");
const repoRoot = resolve(sourceCliDir, "..", "..");
const CLI_SMOKE_TIMEOUT_MS = 15_000;
// beforeAll runs multiple subprocesses (restore + pack + tar) whose individual
// timeouts sum to > CLI_SMOKE_TIMEOUT_MS. Give the outer harness enough room
// so a slow CI machine doesn't hit the beforeAll deadline first (AI-ANTI-002).
const BEFORE_ALL_TIMEOUT_MS = 30_000;

// The canonical skill source. Every entry must reach the tarball as a real
// directory — read dynamically so the assertion tracks skills being added or
// removed (mirrors the listSkillsService default-resolution test).
const expectedSkills = readdirSync(join(repoRoot, ".claude", "skills"), {
  withFileTypes: true,
})
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .toSorted();

// npm/bun roots every tarball entry under `package/`.
const PKG_PREFIX = "package/";

const tmpDirs: string[] = [];
const makeTmp = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
};

interface IsolatedPackage {
  cliDir: string;
  repoRoot: string;
}

const createIsolatedPackage = (): IsolatedPackage => {
  const isolatedRepoRoot = makeTmp("cli-pack-repo-");
  const isolatedCliDir = join(isolatedRepoRoot, "packages", "cli");

  cpSync(
    join(repoRoot, "package.json"),
    join(isolatedRepoRoot, "package.json")
  );
  cpSync(join(repoRoot, "bun.lock"), join(isolatedRepoRoot, "bun.lock"));
  cpSync(join(repoRoot, ".claude"), join(isolatedRepoRoot, ".claude"), {
    dereference: true,
    recursive: true,
  });
  mkdirSync(join(isolatedRepoRoot, "packages"), { recursive: true });
  mkdirSync(join(isolatedRepoRoot, "packages", "core"), { recursive: true });
  cpSync(
    join(repoRoot, "packages", "core", "package.json"),
    join(isolatedRepoRoot, "packages", "core", "package.json")
  );
  cpSync(sourceCliDir, isolatedCliDir, {
    dereference: false,
    filter: (source) => {
      const path = relative(sourceCliDir, source);
      return path !== "node_modules" && !path.startsWith("node_modules/");
    },
    recursive: true,
  });

  return { cliDir: isolatedCliDir, repoRoot: isolatedRepoRoot };
};

// Pack the CLI package into `destination` (runs prepack/postpack, which
// materialize the bundled symlinks into real files and restore the links
// afterward) and return the tarball's entry paths.
const packEntries = (cliDir: string, destination: string): string[] => {
  const pack = Bun.spawnSync(
    ["bun", "pm", "pack", "--destination", destination, "--quiet"],
    { cwd: cliDir, timeout: CLI_SMOKE_TIMEOUT_MS }
  );
  if (pack.exitCode !== 0) {
    throw new Error(`bun pm pack failed: ${pack.stderr.toString()}`);
  }
  const tarball = readdirSync(destination).find((f) => f.endsWith(".tgz"));
  if (tarball === undefined) {
    throw new Error("bun pm pack produced no tarball");
  }
  const list = Bun.spawnSync(["tar", "-tzf", join(destination, tarball)], {
    timeout: CLI_SMOKE_TIMEOUT_MS,
  });
  if (list.exitCode !== 0) {
    throw new Error(`tar -tzf failed: ${list.stderr.toString()}`);
  }
  return list.stdout
    .toString()
    .split("\n")
    .filter((line) => line.length > 0);
};

const restoreBundledSymlinks = (cliDir: string): void => {
  const restore = Bun.spawnSync(
    ["bun", "run", "scripts/bundle-symlinks.ts", "restore"],
    {
      cwd: cliDir,
      timeout: CLI_SMOKE_TIMEOUT_MS,
    }
  );
  if (restore.exitCode !== 0) {
    throw new Error(`bundle symlink restore failed: ${restore.stderr}`);
  }
};

afterAll(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
}, CLI_SMOKE_TIMEOUT_MS);

describe("cli package — published tarball bundles the sync assets (#742 AC#1/#2/#5)", () => {
  // One pack, shared across the assertions below.
  let isolatedPackage: IsolatedPackage;
  let entries: string[] = [];
  beforeAll(() => {
    isolatedPackage = createIsolatedPackage();
    restoreBundledSymlinks(isolatedPackage.cliDir);
    entries = packEntries(isolatedPackage.cliDir, makeTmp("cli-pack-"));
  }, BEFORE_ALL_TIMEOUT_MS);

  test("ships the CLAUDE.template.md asset as a real file (AC#5)", () => {
    // The claude-md source resolves through the _claude_md symlink; its presence
    // here proves the symlink was dereferenced into the tarball.
    expect(entries).toContain(`${PKG_PREFIX}_claude_md/CLAUDE.template.md`);
  });

  test("ships every bundled skill directory as real, dereferenced content (AC#1/#2)", () => {
    // Each .claude/skills/<name> must appear under package/_skills/<name>/.
    // A stripped symlink would contribute nothing, so a populated subtree per
    // skill is the materialization proof.
    for (const skill of expectedSkills) {
      const prefix = `${PKG_PREFIX}_skills/${skill}/`;
      expect(entries.some((entry) => entry.startsWith(prefix))).toBe(true);
    }
  });

  test("contains real files under both bundled-asset prefixes (regression guard)", () => {
    // The original defect packed `_skills` / `_claude_md` as bare symlinks that
    // vanished from the tarball. Real entries under both prefixes prove the
    // regression cannot recur silently.
    expect(
      entries.some((entry) => entry.startsWith(`${PKG_PREFIX}_skills/`))
    ).toBe(true);
    expect(
      entries.some((entry) => entry.startsWith(`${PKG_PREFIX}_claude_md/`))
    ).toBe(true);
  });

  test("postpack restores the source asset and package asset link shape", () => {
    // Assert BEFORE manually calling restoreBundledSymlinks so that a postpack
    // failure is not silently masked by the explicit restore (AI-ANTI-001).
    expect(
      lstatSync(
        join(isolatedPackage.repoRoot, ".claude", "CLAUDE.template.md")
      ).isFile()
    ).toBe(true);
    expect(
      lstatSync(join(isolatedPackage.cliDir, "_claude_md")).isDirectory()
    ).toBe(true);
    expect(
      lstatSync(
        join(isolatedPackage.cliDir, "_claude_md", "CLAUDE.template.md")
      ).isSymbolicLink()
    ).toBe(true);

    // Explicit restore for subsequent tests that depend on the symlink state.
    restoreBundledSymlinks(isolatedPackage.cliDir);
  }, CLI_SMOKE_TIMEOUT_MS);

  test("restores idempotently when bundled asset symlinks already exist", () => {
    restoreBundledSymlinks(isolatedPackage.cliDir);
    restoreBundledSymlinks(isolatedPackage.cliDir);

    expect(
      lstatSync(join(isolatedPackage.cliDir, "_skills")).isSymbolicLink()
    ).toBe(true);
    expect(
      lstatSync(
        join(isolatedPackage.cliDir, "_claude_md", "CLAUDE.template.md")
      ).isSymbolicLink()
    ).toBe(true);
  }, CLI_SMOKE_TIMEOUT_MS);

  test("does not mutate the source worktree bundled asset links", () => {
    expect(lstatSync(join(sourceCliDir, "_skills")).isSymbolicLink()).toBe(
      true
    );
    expect(lstatSync(join(sourceCliDir, "_claude_md")).isDirectory()).toBe(
      true
    );
    expect(
      lstatSync(
        join(sourceCliDir, "_claude_md", "CLAUDE.template.md")
      ).isSymbolicLink()
    ).toBe(true);
  });
});
