import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export type JsonRecord = Record<string, unknown>;

const tmpDirs: string[] = [];

export const cleanupDistrokidTargets = (): void => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
};

export const makeDistrokidTarget = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "distrokid-migrate-"));
  tmpDirs.push(dir);
  mkdirSync(join(dir, "config", "channel"), { recursive: true });
  return dir;
};

export const distrokidPath = (target: string): string =>
  join(target, "config", "channel", "distrokid.json");

export const backupPath = (target: string): string =>
  join(target, "config", "channel", "distrokid.json.bak");

export const oldDistrokid = (
  overrides: JsonRecord = {},
  profileOverrides: JsonRecord = {}
): JsonRecord => ({
  distrokid: {
    enabled: true,
    profile: {
      apple_music_credit: "Jane Doe",
      artist_name: "City Nights",
      language: "ja",
      main_genre: "Electronic",
      songwriter: "Jane Doe",
      track_type: "Instrumental",
      ...profileOverrides,
    },
    ...overrides,
  },
});

export const writeDistrokid = (target: string, data: unknown): void => {
  writeFileSync(distrokidPath(target), `${JSON.stringify(data, null, 2)}\n`);
};

export const readDistrokidText = (target: string): string =>
  readFileSync(distrokidPath(target), "utf-8");

export const readDistrokid = (target: string): JsonRecord =>
  JSON.parse(readDistrokidText(target)) as JsonRecord;

export const readProfile = (target: string): JsonRecord =>
  (readDistrokid(target).distrokid as JsonRecord).profile as JsonRecord;
