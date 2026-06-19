// Mechanical guard for ADR-0003 §5 / Enforcement: a file under packages/mcp/**
// must NOT import the CLI-only interactive OAuth service. interactiveAuthService
// opens a browser and spins a local callback server, which would hang an MCP
// server process at boot. oxlint enforces this with a path-based
// no-restricted-imports rule (CLI is allowed, MCP is not).
//
// We verify the rule fires by linting a throwaway fixture inside a temp repo
// root. The real worktree must not grow or delete packages/mcp while the full
// test suite is running in parallel.

import { afterEach, expect, test } from "bun:test";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Repo root is three levels up from packages/core/test/.
const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const fixtureRel = "packages/mcp/__fixtures__/imports-interactive.ts";

const tmpRoots: string[] = [];
const makeTempRepo = (): string => {
  const root = mkdtempSync(join(tmpdir(), "oauth-interactive-lint-"));
  tmpRoots.push(root);
  copyFileSync(
    join(repoRoot, "oxlint.config.ts"),
    join(root, "oxlint.config.ts")
  );
  symlinkSync(
    join(repoRoot, "node_modules"),
    join(root, "node_modules"),
    "dir"
  );
  return root;
};

afterEach(() => {
  while (tmpRoots.length > 0) {
    const root = tmpRoots.pop();
    if (root !== undefined) {
      rmSync(root, { force: true, recursive: true });
    }
  }
});

test("oxlint errors when a packages/mcp file imports the interactive OAuth service", () => {
  // Given an mcp-tier file importing the CLI-only interactive service
  const tempRepo = makeTempRepo();
  const fixtureFile = join(tempRepo, fixtureRel);
  mkdirSync(join(tempRepo, "packages", "mcp", "__fixtures__"), {
    recursive: true,
  });
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

  // When linting just that file with the copied oxlint config
  const proc = Bun.spawnSync(["bun", "x", "oxlint", fixtureRel], {
    cwd: tempRepo,
  });

  // Then oxlint fails and reports a restricted-import violation naming interactive
  const output = `${proc.stdout.toString()}${proc.stderr.toString()}`;
  expect(proc.exitCode).not.toBe(0);
  expect(output).toContain("no-restricted-imports");
  expect(output).toContain("oauth/interactive");
});
