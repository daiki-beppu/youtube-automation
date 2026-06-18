import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { Glob } from "bun";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const legacyScope = `@youtube${"-automation/"}`;

interface PackageJson {
  bin?: Record<string, string>;
  dependencies?: Record<string, string>;
  name: string;
  private?: boolean;
  version: string;
}

const readText = (relativePath: string): string =>
  readFileSync(join(repoRoot, relativePath), "utf-8");

const readPackageJson = (relativePath: string): PackageJson =>
  JSON.parse(readText(relativePath)) as PackageJson;

describe("rebrand contract - package manifests", () => {
  test("cli package is published as unscoped tayk with the tayk bin", () => {
    const manifest = readPackageJson("packages/cli/package.json");

    expect(manifest.name).toBe("tayk");
    expect(Object.hasOwn(manifest, "private")).toBe(false);
    expect(manifest.bin).toEqual({ tayk: "./bin/tayk.ts" });
  });

  test("cli depends on the renamed core workspace package", () => {
    const { dependencies } = readPackageJson("packages/cli/package.json");
    if (dependencies === undefined) {
      throw new Error("packages/cli/package.json must declare dependencies");
    }

    expect(dependencies["@tayk/core"]).toBe("workspace:*");
    expect(Object.hasOwn(dependencies, `${legacyScope}core`)).toBe(false);
  });

  test("core keeps private workspace status under the renamed internal scope", () => {
    const manifest = readPackageJson("packages/core/package.json");

    expect(manifest.name).toBe("@tayk/core");
    expect(manifest.private).toBe(true);
  });

  test("root package remains the private workspace root", () => {
    const manifest = readPackageJson("package.json");

    expect(manifest.name).toBe("youtube-channels-automation");
    expect(manifest.private).toBe(true);
  });
});

describe("rebrand contract - legacy scope removal", () => {
  test("packages and oxlint config contain no old internal scope references", () => {
    const glob = new Glob("packages/**/*.{json,ts}");
    const checkedFiles = [
      "oxlint.config.ts",
      ...glob.scanSync({ cwd: repoRoot }),
    ];

    const offenders = checkedFiles.filter((relativePath) =>
      readText(relativePath).includes(legacyScope)
    );

    expect(offenders.toSorted()).toEqual([]);
  });

  test("bun lock workspace metadata is synchronized with renamed packages", () => {
    const lockfile = readText("bun.lock");

    expect(lockfile.includes(legacyScope)).toBe(false);
    expect(lockfile.includes('"name": "tayk"')).toBe(true);
    expect(lockfile.includes('"name": "@tayk/core"')).toBe(true);
    expect(lockfile.includes('"@tayk/core": "workspace:*"')).toBe(true);
  });
});

describe("rebrand contract - oxlint package boundaries", () => {
  test("mcp is restricted from importing the published cli package name", () => {
    const config = readText("oxlint.config.ts");

    expect(config.includes('name: "tayk"')).toBe(true);
    expect(config.includes('"tayk/*"')).toBe(true);
    expect(config.includes("@tayk/cli")).toBe(false);
  });
});
