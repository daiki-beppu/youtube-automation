// Pack-time materialization of the CLI's bundled assets (#742).
//
// `_skills` and `_claude_md/CLAUDE.template.md` are committed as symlinks into
// the repo's single source of truth (`.claude/`), so the working tree never
// duplicates skill content and dev/tests resolve real files through the links.
// `npm`/`bun` `pack` strip symlinks from the tarball, so a package built
// straight from the links would ship neither asset (verified: pack emits 8
// files, both assets absent). `prepack` replaces each link with a dereferenced
// real copy; `postpack` restores the link, leaving the working tree unchanged.

import { cp, lstat, rm, symlink } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";

// packages/cli/scripts → packages/cli → packages → repo root.
const CLI_DIR = resolve(import.meta.dirname, "..");
const REPO_ROOT = resolve(CLI_DIR, "..", "..");

// Each bundled asset: the link path inside the CLI package and the canonical
// source under .claude/. The relative symlink target is derived from these two
// (see restore), so the link's shape is declared in exactly one place.
const ASSETS = [
  {
    link: resolve(CLI_DIR, "_skills"),
    source: resolve(REPO_ROOT, ".claude", "skills"),
  },
  {
    link: resolve(CLI_DIR, "_claude_md", "CLAUDE.template.md"),
    source: resolve(REPO_ROOT, ".claude", "CLAUDE.template.md"),
  },
] as const;

// lstat that returns null for a missing path and re-throws any other I/O error
// (Fail Fast — an unexpected error must not be mistaken for "absent").
const lstatOrNull = async (path: string) => {
  try {
    return await lstat(path);
  } catch (error) {
    if (
      typeof error === "object" &&
      error !== null &&
      (error as { code?: unknown }).code === "ENOENT"
    ) {
      return null;
    }
    throw error;
  }
};

// Replace each committed symlink with a dereferenced real copy of its source so
// the tarball ships real files. Idempotent: an already-materialized asset (real
// path, not a symlink) is left untouched.
const materialize = async (): Promise<void> => {
  for (const { link, source } of ASSETS) {
    const stat = await lstatOrNull(link);
    if (stat && !stat.isSymbolicLink()) {
      continue;
    }
    if (stat) {
      await rm(link, { force: true, recursive: true });
    }
    await cp(source, link, { dereference: true, recursive: true });
  }
};

// Restore each asset to its committed relative symlink regardless of the current
// on-disk shape (self-healing — works even if materialize ran only partially).
const restore = async (): Promise<void> => {
  for (const { link, source } of ASSETS) {
    await rm(link, { force: true, recursive: true });
    await symlink(relative(dirname(link), source), link);
  }
};

const [mode] = process.argv.slice(2);
if (mode === "materialize") {
  await materialize();
} else if (mode === "restore") {
  await restore();
} else {
  throw new Error(
    `usage: bundle-symlinks <materialize|restore> (got ${String(mode)})`
  );
}
