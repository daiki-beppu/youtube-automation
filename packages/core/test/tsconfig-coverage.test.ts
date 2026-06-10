import { expect, test } from "bun:test";
import { resolve } from "node:path";

import { Glob } from "bun";

// Repo root is three levels up from packages/core/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");

// Guards the wiring-gap: a new package path tier (e.g. bin/) must not slip past
// `tsc -b --noEmit`. We assert tsc's resolved file set covers every package
// source file, so adding a tier without registering its include glob fails here.
test("tsconfig contract: every package source tier is type-checked", async () => {
  const proc = Bun.spawnSync(
    ["bun", "x", "tsc", "-p", "tsconfig.json", "--showConfig"],
    { cwd: repoRoot }
  );
  expect(proc.exitCode).toBe(0);

  const config = JSON.parse(proc.stdout.toString()) as { files: string[] };
  const checked = new Set(config.files.map((file) => resolve(repoRoot, file)));

  const glob = new Glob("packages/*/{src,lib,bin,test}/**/*.ts");
  const uncovered: string[] = [];
  for await (const rel of glob.scan({ cwd: repoRoot })) {
    if (!checked.has(resolve(repoRoot, rel))) {
      uncovered.push(rel);
    }
  }

  expect(uncovered).toEqual([]);
});
