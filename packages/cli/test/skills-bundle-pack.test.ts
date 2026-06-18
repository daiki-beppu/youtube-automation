import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Guards the #742 distribution contract end-to-end: `_skills` / `_claude_md` are
// committed as symlinks into `.claude/`, and pack strips symlinks — so without
// the prepack materialization the published tarball ships neither asset (the
// original REJECT: pack emitted 8 files, both assets absent). This test packs
// the real package and asserts both assets land as real files.

// packages/cli/test → packages/cli, and two more up → repo root.
const cliDir = resolve(import.meta.dir, "..");
const repoRoot = resolve(cliDir, "..", "..");

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

const makePackWorkspace = (): string => {
  const workspace = makeTmp("cli-pack-workspace-");
  const packageDir = join(workspace, "packages", "cli");
  const coreDir = join(workspace, "packages", "core");
  mkdirSync(coreDir, { recursive: true });
  writeFileSync(
    join(workspace, "package.json"),
    JSON.stringify({ private: true, workspaces: ["packages/*"] }, null, 2)
  );
  cpSync(join(repoRoot, "bun.lock"), join(workspace, "bun.lock"));
  cpSync(
    join(repoRoot, "packages", "core", "package.json"),
    join(coreDir, "package.json")
  );
  cpSync(cliDir, packageDir, {
    dereference: false,
    filter: (source) => !source.includes(`${cliDir}/test`),
    recursive: true,
    verbatimSymlinks: true,
  });
  cpSync(join(repoRoot, ".claude"), join(workspace, ".claude"), {
    dereference: true,
    recursive: true,
  });
  return packageDir;
};

// Pack an isolated copy of the CLI package into `destination`. The package's
// real prepack/postpack scripts still run, but they materialize the copy's
// `_skills` / `_claude_md` links instead of replacing the shared worktree paths
// that other parallel tests read.
const packEntries = (destination: string): string[] => {
  const packageDir = makePackWorkspace();
  const pack = Bun.spawnSync(
    ["bun", "pm", "pack", "--destination", destination, "--quiet"],
    { cwd: packageDir }
  );
  if (pack.exitCode !== 0) {
    throw new Error(`bun pm pack failed: ${pack.stderr.toString()}`);
  }
  const tarball = readdirSync(destination).find((f) => f.endsWith(".tgz"));
  if (tarball === undefined) {
    throw new Error("bun pm pack produced no tarball");
  }
  const list = Bun.spawnSync(["tar", "-tzf", join(destination, tarball)]);
  if (list.exitCode !== 0) {
    throw new Error(`tar -tzf failed: ${list.stderr.toString()}`);
  }
  return list.stdout
    .toString()
    .split("\n")
    .filter((line) => line.length > 0);
};

afterAll(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

describe("cli package — published tarball bundles the sync assets (#742 AC#1/#2/#5)", () => {
  // One pack, shared across the assertions below.
  let entries: string[] = [];
  beforeAll(() => {
    entries = packEntries(makeTmp("cli-pack-"));
  });

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
});
