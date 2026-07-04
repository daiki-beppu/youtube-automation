import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, relative, resolve } from "node:path";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const lefthookConfig = join(repoRoot, "lefthook.yml");
const fixtureDirPrefix = join(
  repoRoot,
  "packages",
  "cli",
  "__lefthook_contract__-"
);
const fixtureDirs: string[] = [];

const runTool = (args: string[]) =>
  Bun.spawnSync(["bun", "x", ...args], { cwd: repoRoot });

const combinedOutput = (proc: Bun.SyncSubprocess<"pipe", "pipe">): string =>
  `${proc.stdout.toString()}${proc.stderr.toString()}`;

const createFixtureDir = (): string => {
  const fixtureDir = mkdtempSync(fixtureDirPrefix);
  fixtureDirs.push(fixtureDir);
  return fixtureDir;
};

afterEach(() => {
  for (const fixtureDir of fixtureDirs.splice(0)) {
    rmSync(fixtureDir, { force: true, recursive: true });
  }
});

describe("lefthook pre-commit oxlint / oxfmt contract", () => {
  test("commands keep --no-error-on-unmatched-pattern on staged file inputs", () => {
    const config = readFileSync(lefthookConfig, "utf-8");

    expect(config).toContain(
      "run: bunx oxlint --no-error-on-unmatched-pattern {staged_files}"
    );
    expect(config).toContain(
      "run: bunx oxfmt --check --no-error-on-unmatched-pattern {staged_files}"
    );
    expect(config).toContain('- "extensions/**"');
  });

  test("ignored-only files are successful no-ops for both tools", () => {
    const ignoredTs = "poc/ts-rewrite/src/types.ts";
    const ignoredJson = "examples/channel_config.example/workflow.json";
    expect(existsSync(join(repoRoot, ignoredTs))).toBe(true);
    expect(existsSync(join(repoRoot, ignoredJson))).toBe(true);

    expect(runTool(["oxlint", ignoredTs]).exitCode).not.toBe(0);
    const oxlint = runTool([
      "oxlint",
      "--no-error-on-unmatched-pattern",
      ignoredTs,
    ]);
    expect(oxlint.exitCode).toBe(0);

    expect(runTool(["oxfmt", "--check", ignoredJson]).exitCode).not.toBe(0);
    const oxfmt = runTool([
      "oxfmt",
      "--check",
      "--no-error-on-unmatched-pattern",
      ignoredJson,
    ]);
    expect(oxfmt.exitCode).toBe(0);
  });

  test("real oxlint violations still fail with the unmatched-pattern flag", () => {
    const fixtureDir = createFixtureDir();
    const fixtureFile = join(fixtureDir, "banned-mcp-import.ts");
    const fixtureRel = relative(repoRoot, fixtureFile);
    writeFileSync(
      fixtureFile,
      [
        'import { something } from "@youtube-automation/mcp";',
        "",
        "export const value = something;",
        "",
      ].join("\n"),
      "utf-8"
    );

    const proc = runTool([
      "oxlint",
      "--no-error-on-unmatched-pattern",
      fixtureRel,
    ]);
    const output = combinedOutput(proc);
    expect(proc.exitCode).not.toBe(0);
    expect(output).toContain("no-restricted-imports");
    expect(output).toContain("@youtube-automation/mcp");
  });

  test("real oxfmt violations still fail with the unmatched-pattern flag", () => {
    const fixtureDir = createFixtureDir();
    const fixtureFile = join(fixtureDir, "bad-format.json");
    const fixtureRel = relative(repoRoot, fixtureFile);
    writeFileSync(fixtureFile, '{"alpha":1}\n', "utf-8");

    const proc = runTool([
      "oxfmt",
      "--check",
      "--no-error-on-unmatched-pattern",
      fixtureRel,
    ]);
    expect(proc.exitCode).not.toBe(0);
  });
});
