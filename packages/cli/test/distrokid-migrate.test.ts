import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const tmpDirs: string[] = [];

afterEach(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

const makeTarget = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "cli-distrokid-migrate-"));
  tmpDirs.push(dir);
  mkdirSync(join(dir, "config", "channel"), { recursive: true });
  return dir;
};

const distrokidPath = (target: string): string =>
  join(target, "config", "channel", "distrokid.json");

const writeOldDistrokid = (target: string): void => {
  writeFileSync(
    distrokidPath(target),
    `${JSON.stringify(
      {
        distrokid: {
          enabled: true,
          profile: {
            apple_music_credit: "Jane Doe",
            artist_name: "City Nights",
            language: "ja",
            main_genre: "Electronic",
            songwriter: "Jane Doe",
            track_type: "Instrumental",
          },
        },
      },
      null,
      2
    )}\n`
  );
};

describe("tayk distrokid-migrate", () => {
  test("runs as a dry-run subcommand and leaves distrokid.json unchanged", () => {
    const target = makeTarget();
    writeOldDistrokid(target);
    const before = readFileSync(distrokidPath(target), "utf-8");

    const proc = Bun.spawnSync(
      [
        "bun",
        "packages/cli/bin/tayk.ts",
        "distrokid-migrate",
        "--target",
        target,
      ],
      { cwd: repoRoot }
    );

    expect(proc.exitCode).toBe(0);
    expect(proc.stdout.toString()).toContain("[dry-run]");
    expect(proc.stderr.toString()).toBe("");
    expect(readFileSync(distrokidPath(target), "utf-8")).toBe(before);
  }, 30_000);

  test("applies migration without a backup when --no-backup is passed", () => {
    const target = makeTarget();
    writeOldDistrokid(target);

    const proc = Bun.spawnSync(
      [
        "bun",
        "packages/cli/bin/tayk.ts",
        "distrokid-migrate",
        "--apply",
        "--no-backup",
        "--target",
        target,
      ],
      { cwd: repoRoot }
    );

    const {
      distrokid: { profile },
    } = JSON.parse(readFileSync(distrokidPath(target), "utf-8")) as {
      distrokid: { profile: { songwriter?: unknown } };
    };
    expect(proc.exitCode).toBe(0);
    expect(proc.stdout.toString()).toContain("[apply]");
    expect(proc.stdout.toString()).not.toContain("backup:");
    expect(proc.stderr.toString()).toBe("");
    expect(profile.songwriter).toEqual({ first: "Jane", last: "Doe" });
    expect(existsSync(`${distrokidPath(target)}.bak`)).toBe(false);
  }, 30_000);
});
