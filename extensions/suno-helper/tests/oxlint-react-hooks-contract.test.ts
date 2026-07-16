import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, test } from "vitest";

const oxlint = fileURLToPath(new URL("../node_modules/.bin/oxlint", import.meta.url));
const config = fileURLToPath(new URL("../../.oxlintrc.json", import.meta.url));
const temporaryDirectories: string[] = [];

function lintFixture(name: string) {
  const directory = mkdtempSync(join(tmpdir(), "oxlint-react-hooks-"));
  temporaryDirectories.push(directory);
  const source = readFileSync(new URL(`./fixtures/${name}.fixture`, import.meta.url), "utf8");
  const sourcePath = join(directory, `${name}.tsx`);
  writeFileSync(sourcePath, source);

  const result = spawnSync(oxlint, ["-c", config, sourcePath], {
    encoding: "utf8",
  });

  return {
    status: result.status,
    output: `${result.stdout}${result.stderr}`,
  };
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("React Hooks lint contract", () => {
  test("conditional Hook calls fail with rules-of-hooks", () => {
    const result = lintFixture("conditional-hook");

    expect(result.status).not.toBe(0);
    expect(result.output).toContain("react-hooks(rules-of-hooks)");
    expect(result.output).toMatch(/\berror\b/);
  });

  test("missing effect dependencies remain warnings", () => {
    const result = lintFixture("missing-effect-dependency");

    expect(result.status).toBe(0);
    expect(result.output).toContain("react-hooks(exhaustive-deps)");
    expect(result.output).toMatch(/\bwarning\b/);
  });

  test("React Compiler diagnostics remain disabled without strengthening old warnings", () => {
    const result = lintFixture("ref-read-during-render");

    expect(result.status).toBe(0);
    expect(result.output).not.toContain("react(react-compiler)");
  });
});
