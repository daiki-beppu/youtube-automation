// Mechanical guard for ADR-0003 §5 / Enforcement: a file under packages/mcp/**
// must NOT import the CLI-only interactive OAuth service. interactiveAuthService
// opens a browser and spins a local callback server, which would hang an MCP
// server process at boot. oxlint enforces this with a path-based
// no-restricted-imports rule (CLI is allowed, MCP is not).
//
// We verify the rule fires by linting a throwaway fixture placed in a
// packages/mcp tier that is excluded from both the tsc include globs and the
// tsconfig-coverage test glob (`__fixtures__`, not src/lib/bin/test), then
// deleting the whole tree so a committed, intentionally-violating file never
// trips the repo-wide `bun run lint`. Spawning the linter mirrors the existing
// tsconfig-coverage.test.ts approach of shelling out to the toolchain.

import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

// Repo root is three levels up from packages/core/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const fixtureRel = "packages/mcp/__fixtures__/imports-interactive.ts";
const mcpDir = join(repoRoot, "packages", "mcp");
const fixtureDir = join(mcpDir, "__fixtures__");
const fixtureFile = join(repoRoot, fixtureRel);

// Snapshot whether a real packages/mcp already exists BEFORE the test runs. The
// cleanup must only remove what the test materialized: if the package is absent
// today we remove the whole tree we created, but once a real packages/mcp lands
// we delete just the throwaway __fixtures__ dir so we never blow away a real
// package (the rmSync footgun this test previously had).
const mcpPreexisted = existsSync(mcpDir);

afterEach(() => {
  rmSync(mcpPreexisted ? fixtureDir : mcpDir, {
    force: true,
    recursive: true,
  });
});

test("oxlint errors when a packages/mcp file imports the interactive OAuth service", () => {
  // Given an mcp-tier file importing the CLI-only interactive service
  mkdirSync(fixtureDir, { recursive: true });
  writeFileSync(
    fixtureFile,
    [
      'import { interactiveAuthService } from "@youtube-automation/core/oauth/interactive";',
      "",
      "export const handler = interactiveAuthService;",
      "",
    ].join("\n"),
    "utf-8"
  );

  // When linting just that file with the repo oxlint config (auto-discovered
  // from the repo root cwd)
  const proc = Bun.spawnSync(["bun", "run", "lint", "--", fixtureRel], {
    cwd: repoRoot,
  });

  // Then oxlint fails and reports a restricted-import violation naming interactive
  const output = `${proc.stdout.toString()}${proc.stderr.toString()}`;
  expect(proc.exitCode).not.toBe(0);
  expect(output).toContain("no-restricted-imports");
  expect(output).toContain("oauth/interactive");
});
