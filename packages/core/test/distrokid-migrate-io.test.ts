import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { migrateDistrokidService } from "@youtube-automation/core/distrokid-migrate";
import { REGISTRY } from "@youtube-automation/core/registry";

import {
  backupPath,
  cleanupDistrokidTargets,
  distrokidPath,
  makeDistrokidTarget,
  oldDistrokid,
  readDistrokidText,
  readProfile,
  writeDistrokid,
} from "./distrokid-migrate-fixtures.ts";

let savedChannelDir: string | undefined;
let savedCwd: string;

beforeEach(() => {
  savedChannelDir = process.env.CHANNEL_DIR;
  savedCwd = process.cwd();
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
});

afterEach(() => {
  process.chdir(savedCwd);
  if (savedChannelDir === undefined) {
    Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  } else {
    process.env.CHANNEL_DIR = savedChannelDir;
  }
  cleanupDistrokidTargets();
});

const expectOk = async (
  input: Parameters<typeof migrateDistrokidService>[0]
): Promise<void> => {
  const result = await migrateDistrokidService(input);
  expect(result.ok).toBe(true);
};

describe("distrokid migrate service — filesystem behavior", () => {
  test("dry-run keeps the source file unchanged and does not create a backup", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid());
    const before = readDistrokidText(target);

    await expectOk({ apply: false, backup: true, target });

    expect(readDistrokidText(target)).toBe(before);
    expect(existsSync(backupPath(target))).toBe(false);
  });

  test("creates distrokid.json.bak when apply uses backup", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid());
    const before = readDistrokidText(target);

    await expectOk({ apply: true, backup: true, target });

    expect(readFileSync(backupPath(target), "utf-8")).toBe(before);
  });

  test("resolves target from CHANNEL_DIR when target is omitted", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid());
    process.env.CHANNEL_DIR = target;

    await expectOk({ apply: true, backup: false });

    expect(readProfile(target).songwriter).toEqual({
      first: "Jane",
      last: "Doe",
    });
  });

  test("explicit target takes precedence over CHANNEL_DIR", async () => {
    const envTarget = makeDistrokidTarget();
    const explicitTarget = makeDistrokidTarget();
    writeDistrokid(envTarget, oldDistrokid({}, { songwriter: "Env Writer" }));
    writeDistrokid(
      explicitTarget,
      oldDistrokid({}, { songwriter: "Explicit Writer" })
    );
    process.env.CHANNEL_DIR = envTarget;

    await expectOk({ apply: true, backup: false, target: explicitTarget });

    expect(readProfile(explicitTarget).songwriter).toEqual({
      first: "Explicit",
      last: "Writer",
    });
    expect(readProfile(envTarget).songwriter).toBe("Env Writer");
  });

  test("resolves target from a current working directory ancestor", async () => {
    const target = makeDistrokidTarget();
    const nested = join(target, "work", "nested");
    mkdirSync(nested, { recursive: true });
    writeDistrokid(target, oldDistrokid({}, { songwriter: "Ancestor Writer" }));
    process.chdir(nested);

    await expectOk({ apply: true, backup: false });

    expect(readProfile(target).songwriter).toEqual({
      first: "Ancestor",
      last: "Writer",
    });
  });

  test("returns a config error for missing distrokid.json", async () => {
    const target = makeDistrokidTarget();

    const result = await migrateDistrokidService({
      apply: false,
      backup: true,
      target,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("distrokid.json");
    }
  });

  test("returns a config error for invalid JSON", async () => {
    const target = makeDistrokidTarget();
    writeFileSync(distrokidPath(target), "{broken");

    const result = await migrateDistrokidService({
      apply: false,
      backup: true,
      target,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("JSON");
    }
  });

  test("returns a config error for a non-object top-level JSON value", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, ["not", "an", "object"]);

    const result = await migrateDistrokidService({
      apply: false,
      backup: true,
      target,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("object");
    }
  });

  test("returns a config error for a non-object distrokid.profile", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, { distrokid: { enabled: true, profile: [] } });

    const result = await migrateDistrokidService({
      apply: false,
      backup: true,
      target,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("profile");
    }
  });
});

describe("distrokid migrate registry", () => {
  test("declares no injected deps so config loading is not required", () => {
    const entry = REGISTRY["distrokid.migrate"];

    expect(entry.deps).toEqual([]);
  });
});
