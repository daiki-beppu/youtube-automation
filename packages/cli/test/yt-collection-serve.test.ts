import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { REGISTRY } from "@youtube-automation/core/registry";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const taykBin = join(repoRoot, "packages", "cli", "bin", "tayk.ts");

const runTayk = (...argv: string[]) =>
  Bun.spawnSync(["bun", taykBin, ...argv], {
    cwd: repoRoot,
    env: process.env,
  });

describe("core registry — collection.serve entry visible from cli package", () => {
  test("should expose the registry entry consumed by the CLI adapter", () => {
    const entry = REGISTRY["collection.serve"];

    expect(entry.deps).toEqual(["config"]);
    expect(entry.description.length).toBeGreaterThan(0);
  });
});

describe("tayk collection-serve — smoke", () => {
  test("should expose help through the single tayk dispatcher", () => {
    const proc = runTayk("collection-serve", "--help");

    expect(proc.exitCode).toBe(0);
    const stdout = proc.stdout.toString();
    expect(stdout).toContain("collection-serve");
    expect(stdout).toContain("--port");
    expect(stdout).toContain("--allow-origin");
    expect(stdout).toContain("--distrokid-source");
    expect(stdout).toContain("--distrokid-state-root");
    expect(stdout).toContain("--playlist-capture-root");
    expect(stdout).toContain("--playlist-capture-prefix");
  });

  test("should not add a per-CLI yt-collection-serve bin", () => {
    expect(
      existsSync(
        join(repoRoot, "packages", "cli", "bin", "yt-collection-serve.ts")
      )
    ).toBe(false);
  });

  test("should not expose the legacy Python yt-collection-serve entry point", () => {
    const pyproject = readFileSync(join(repoRoot, "pyproject.toml"), "utf-8");

    expect(pyproject).not.toContain("yt-collection-serve");
    expect(pyproject).not.toContain(
      "youtube_automation.scripts.collection_serve:main"
    );
  });

  test("should point helper-facing guidance at tayk collection-serve", () => {
    const distrokidPopup = readFileSync(
      join(
        repoRoot,
        "extensions",
        "distrokid-helper",
        "entrypoints",
        "popup",
        "App.tsx"
      ),
      "utf-8"
    );
    const sunoRunner = readFileSync(
      join(
        repoRoot,
        "extensions",
        "suno-helper",
        "components",
        "useSunoRunner.ts"
      ),
      "utf-8"
    );
    const distrokidReadme = readFileSync(
      join(repoRoot, "extensions", "distrokid-helper", "README.md"),
      "utf-8"
    );
    const distrokidSkill = readFileSync(
      join(repoRoot, ".claude", "skills", "distrokid-prep", "SKILL.md"),
      "utf-8"
    );
    const wfNewSkill = readFileSync(
      join(repoRoot, ".claude", "skills", "wf-new", "SKILL.md"),
      "utf-8"
    );

    expect(distrokidPopup).toContain("tayk collection-serve");
    expect(sunoRunner).toContain("tayk collection-serve");
    expect(distrokidReadme).toContain("--distrokid-state-root");
    expect(distrokidSkill).toContain("collection-serve service");
    expect(wfNewSkill).toContain("tayk collection-serve");
    expect(distrokidPopup).not.toContain("yt-collection-serve を再起動");
    expect(sunoRunner).not.toContain("yt-collection-serve が起動");
    expect(distrokidReadme).not.toContain("yt-collection-serve");
    expect(distrokidSkill).not.toContain("yt-collection-serve");
    expect(wfNewSkill).not.toContain("yt-collection-serve");
    expect(distrokidReadme).not.toContain(
      "--playlist-capture-root <channel_root>"
    );
  });
});
