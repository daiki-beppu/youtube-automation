import { existsSync } from "node:fs";
import { copyFile, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import {
  CHANNEL_DIRNAME,
  CONFIG_DIRNAME,
  DISTROKID_BACKUP_FILENAME,
  DISTROKID_FILENAME,
  DistrokidMigrateInputSchema,
  DistrokidMigrateOutputSchema,
} from "./schema.ts";
import type {
  DistrokidMigrateInput,
  DistrokidMigrateOutput,
} from "./schema.ts";

type JsonRecord = Record<string, unknown>;

const PROFILE_KEYS = ["language", "main_genre", "sub_genre"] as const;

const SONGWRITER_KEYS = ["first", "last", "middle"] as const;

const AI_DISCLOSURE_KEYS = [
  "apply_to_all",
  "artist_persona",
  "enabled",
  "lyrics",
  "music",
  "partial_audio_type",
  "recording_scope",
] as const;

const CREDIT_KEYS = ["performer_role", "producer_role"] as const;

const DEFAULT_AI_DISCLOSURE: JsonRecord = {
  apply_to_all: true,
  artist_persona: true,
  enabled: true,
  lyrics: true,
  music: true,
  partial_audio_type: null,
  recording_scope: "full",
};

const isPlainObject = (value: unknown): value is JsonRecord =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const distrokidPath = (target: string): string =>
  join(target, CONFIG_DIRNAME, CHANNEL_DIRNAME, DISTROKID_FILENAME);

const backupPath = (target: string): string =>
  join(target, CONFIG_DIRNAME, CHANNEL_DIRNAME, DISTROKID_BACKUP_FILENAME);

const hasChannelConfigDir = (path: string): boolean =>
  existsSync(join(path, CONFIG_DIRNAME, CHANNEL_DIRNAME));

const resolveAncestorTarget = (start: string): string => {
  let current = resolve(start);
  for (;;) {
    if (hasChannelConfigDir(current)) {
      return current;
    }
    const parent = dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }
  throw new Error(
    "config: CHANNEL_DIR 環境変数を設定するか、config/channel/ を持つディレクトリ配下で実行してください"
  );
};

const resolveTarget = (target: string | undefined): string => {
  if (target !== undefined) {
    return resolve(target);
  }
  if (process.env.CHANNEL_DIR) {
    return resolve(process.env.CHANNEL_DIR);
  }
  return resolveAncestorTarget(process.cwd());
};

const readJsonObject = async (path: string): Promise<JsonRecord> => {
  if (!existsSync(path)) {
    throw new Error(`config: ${DISTROKID_FILENAME} が見つかりません: ${path}`);
  }
  let data: unknown;
  try {
    data = JSON.parse(await readFile(path, "utf-8"));
  } catch (error) {
    throw new Error(`config: ${DISTROKID_FILENAME} の JSON パース失敗`, {
      cause: error,
    });
  }
  if (!isPlainObject(data)) {
    throw new Error(
      `config: ${DISTROKID_FILENAME} は object でなければなりません`
    );
  }
  return data;
};

const profileFrom = (data: JsonRecord): JsonRecord => {
  if (!isPlainObject(data.distrokid)) {
    throw new Error("config: distrokid は object でなければなりません");
  }
  if (data.distrokid.profile === undefined) {
    return {};
  }
  if (!isPlainObject(data.distrokid.profile)) {
    throw new Error("config: distrokid.profile は object でなければなりません");
  }
  return data.distrokid.profile;
};

const pickKnownKeys = (
  source: JsonRecord,
  keys: readonly string[]
): JsonRecord => {
  const next: JsonRecord = {};
  for (const key of keys) {
    if (key in source) {
      next[key] = source[key];
    }
  }
  return next;
};

const normalizeSongwriter = (value: unknown): unknown => {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (isPlainObject(value)) {
    return pickKnownKeys(value, SONGWRITER_KEYS);
  }
  if (typeof value !== "string") {
    throw new TypeError(
      "validation: distrokid.profile.songwriter must be string or object"
    );
  }
  const parts = value
    .trim()
    .split(/\s+/u)
    .filter((part) => part.length > 0);
  if (parts.length === 0) {
    return undefined;
  }
  if (parts.length === 1) {
    return { first: parts[0], last: "" };
  }
  const [first, ...rest] = parts;
  const last = rest.at(-1);
  if (last === undefined) {
    throw new Error(
      "validation: distrokid.profile.songwriter last name is required"
    );
  }
  const middle = rest.slice(0, -1).join(" ");
  return middle.length > 0 ? { first, last, middle } : { first, last };
};

const normalizeAiDisclosure = (value: unknown): JsonRecord => {
  if (value === undefined || !isPlainObject(value)) {
    return DEFAULT_AI_DISCLOSURE;
  }
  const { composition, ...withoutComposition } = value;
  const music =
    withoutComposition.music === undefined
      ? composition
      : withoutComposition.music;
  const withMusic =
    music === undefined ? withoutComposition : { ...withoutComposition, music };
  const recordingScope =
    withMusic.recording_scope === undefined &&
    withMusic.partial_audio_type !== undefined &&
    withMusic.partial_audio_type !== null
      ? "partial"
      : withMusic.recording_scope;
  const normalized =
    recordingScope === undefined
      ? withMusic
      : { ...withMusic, recording_scope: recordingScope };

  return {
    ...DEFAULT_AI_DISCLOSURE,
    ...pickKnownKeys(normalized, AI_DISCLOSURE_KEYS),
  };
};

const migrateProfile = (profile: JsonRecord): JsonRecord => {
  const next = pickKnownKeys(profile, PROFILE_KEYS);
  if (isPlainObject(profile.credits)) {
    next.credits = pickKnownKeys(profile.credits, CREDIT_KEYS);
  }

  const songwriter = normalizeSongwriter(profile.songwriter);
  if (songwriter === undefined) {
    Reflect.deleteProperty(next, "songwriter");
  } else {
    next.songwriter = songwriter;
  }
  next.ai_disclosure = normalizeAiDisclosure(profile.ai_disclosure);
  return next;
};

const migrateDocument = (data: JsonRecord): JsonRecord => {
  const distrokid = data.distrokid as JsonRecord;
  const profile = profileFrom(data);
  return {
    ...data,
    distrokid: {
      ...distrokid,
      profile: migrateProfile(profile),
    },
  };
};

export const migrateDistrokidService = async (
  input: DistrokidMigrateInput
): Promise<Result<DistrokidMigrateOutput, ServiceError>> => {
  try {
    const request = DistrokidMigrateInputSchema.parse(input);
    const target = resolveTarget(request.target);
    const path = distrokidPath(target);
    const backup = backupPath(target);
    const source = await readJsonObject(path);
    const migrated = migrateDocument(source);

    if (request.apply) {
      if (request.backup) {
        await copyFile(path, backup);
      }
      await writeFile(path, `${JSON.stringify(migrated, null, 2)}\n`);
    }

    return ok(
      DistrokidMigrateOutputSchema.parse({
        applied: request.apply,
        backupPath: request.apply && request.backup ? backup : null,
        path,
        target,
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
