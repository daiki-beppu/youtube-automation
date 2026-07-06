import type { Stats } from "node:fs";
import { lstat, readFile } from "node:fs/promises";
import { join } from "node:path";

import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";
import {
  AUDIO_SECTION_KEY,
  MASTERUP_CONFIG_DIR,
  MASTERUP_JSON_FILENAME,
  MASTERUP_YAML_FILENAME,
} from "./constants.ts";

export type MasterupAudioConfig = Partial<{
  bitrate: string;
  crossfadeDuration: number;
  pinFirstCount: number;
  shuffle: boolean;
  shuffleSeed: number;
  targetDurationMin: number;
}>;

export interface MasterupConfigFs {
  readonly lstat: (path: string) => Promise<Stats>;
  readonly readFile: (path: string, encoding: "utf-8") => Promise<string>;
}

const defaultFs: MasterupConfigFs = { lstat, readFile };

const MasterupAudioConfigSchema = z
  .object({
    bitrate: z.string().trim().min(1).optional(),
    crossfadeDuration: z.number().positive().optional(),
    pinFirstCount: z.number().int().nonnegative().optional(),
    shuffle: z.boolean().optional(),
    shuffleSeed: z.number().int().optional(),
    targetDurationMin: z.number().int().positive().optional(),
  })
  .passthrough();

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isNodeErrorCode = (error: unknown, code: string): boolean =>
  isRecord(error) && error.code === code;

const configFileExists = async (
  path: string,
  fs: MasterupConfigFs
): Promise<boolean> => {
  try {
    const stats = await fs.lstat(path);
    if (!stats.isFile() || stats.isSymbolicLink()) {
      throw new Error(`config: ${path} must be a regular file`);
    }
    return true;
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) {
      return false;
    }
    if (error instanceof Error && error.message.startsWith("config:")) {
      throw error;
    }
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`config: failed to inspect ${path}: ${message}`, {
      cause: error,
    });
  }
};

const configPath = (channelDir: string, filename: string): string =>
  join(channelDir, MASTERUP_CONFIG_DIR, filename);

const existingConfigPath = async (
  channelDir: string,
  fs: MasterupConfigFs
): Promise<string | null> => {
  const json = configPath(channelDir, MASTERUP_JSON_FILENAME);
  if (await configFileExists(json, fs)) {
    return json;
  }
  const yaml = configPath(channelDir, MASTERUP_YAML_FILENAME);
  return (await configFileExists(yaml, fs)) ? yaml : null;
};

const readConfigText = async (
  path: string,
  fs: MasterupConfigFs
): Promise<string> => {
  try {
    return await fs.readFile(path, "utf-8");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`config: failed to read ${path}: ${message}`, {
      cause: error,
    });
  }
};

const parseConfigJson = (path: string, text: string): unknown => {
  try {
    return JSON.parse(text);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`config: failed to parse ${path}: ${message}`, {
      cause: error,
    });
  }
};

const stripInlineComment = (value: string): string => {
  let singleQuoted = false;
  let doubleQuoted = false;
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    const previous = index === 0 ? "" : value[index - 1];
    if (char === "'" && !doubleQuoted) {
      singleQuoted = !singleQuoted;
      continue;
    }
    if (char === '"' && !singleQuoted && previous !== "\\") {
      doubleQuoted = !doubleQuoted;
      continue;
    }
    if (
      char === "#" &&
      !singleQuoted &&
      !doubleQuoted &&
      (index === 0 || (previous !== undefined && /\s/u.test(previous)))
    ) {
      return value.slice(0, index).trimEnd();
    }
  }
  return value.trimEnd();
};

const parseQuotedScalar = (value: string): string | undefined => {
  if (value.startsWith('"') && value.endsWith('"')) {
    return JSON.parse(value) as string;
  }
  if (value.startsWith("'") && value.endsWith("'")) {
    return value.slice(1, -1).replaceAll("''", "'");
  }
  return undefined;
};

const parseScalar = (value: string): string | number | boolean => {
  const normalized = stripInlineComment(value).trim();
  if (normalized.length === 0) {
    throw new Error("config: empty masterup audio YAML scalar");
  }
  const quoted = parseQuotedScalar(normalized);
  if (quoted !== undefined) {
    return quoted;
  }
  if (normalized === "true") {
    return true;
  }
  if (normalized === "false") {
    return false;
  }
  const numberValue = Number(normalized);
  return Number.isNaN(numberValue) ? normalized : numberValue;
};

const parseMasterupYaml = (text: string): unknown => {
  const audio: Record<string, string | number | boolean> = {};
  let inAudio = false;
  let inFinalize = false;
  for (const line of text.split(/\r?\n/u)) {
    if (line.trim().length === 0 || line.trimStart().startsWith("#")) {
      continue;
    }
    if (!line.startsWith(" ")) {
      const topLevelAudio = new RegExp(
        `^${AUDIO_SECTION_KEY}:\\s*(.*)$`,
        "u"
      ).exec(line.trim());
      if (topLevelAudio !== null) {
        const [, value] = topLevelAudio;
        if (value !== undefined && value.length > 0) {
          throw new Error("config: masterup audio YAML must be a mapping");
        }
        inAudio = true;
        inFinalize = false;
        continue;
      }
      inAudio = false;
      inFinalize = false;
    }
    if (inAudio) {
      const match = /^ {2}([a-zA-Z0-9_]+):\s*(.+)$/u.exec(line);
      if (match !== null) {
        const [, key, value] = match;
        if (key !== undefined && value !== undefined) {
          if (key === "finalize") {
            inFinalize = false;
            continue;
          }
          inFinalize = false;
          audio[key] = parseScalar(value.trim());
          continue;
        }
      }
      if (/^ {2}finalize:\s*$/u.test(line)) {
        inFinalize = true;
        continue;
      }
      if (inFinalize && /^ {4,}/u.test(line)) {
        continue;
      }
      throw new Error(`config: unsupported masterup audio YAML line: ${line}`);
    }
  }
  return { [AUDIO_SECTION_KEY]: audio };
};

const parseMasterupConfig = (path: string, text: string): unknown => {
  try {
    return path.endsWith(".json")
      ? parseConfigJson(path, text)
      : parseMasterupYaml(text);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.startsWith("config:")) {
      throw error;
    }
    throw new Error(`config: failed to parse ${path}: ${message}`, {
      cause: error,
    });
  }
};

export const readMasterupAudioConfig = async (
  channelDir: string | undefined,
  fs: MasterupConfigFs = defaultFs
): Promise<MasterupAudioConfig> => {
  if (channelDir === undefined) {
    return {};
  }
  const path = await existingConfigPath(channelDir, fs);
  if (path === null) {
    return {};
  }
  const parsed = parseMasterupConfig(path, await readConfigText(path, fs));
  if (!isRecord(parsed)) {
    throw new Error(`config: ${path} must contain an object`);
  }
  const audioSection = Object.hasOwn(parsed, AUDIO_SECTION_KEY)
    ? parsed[AUDIO_SECTION_KEY]
    : {};
  if (!isRecord(audioSection)) {
    throw new Error(`config: ${path} audio must be an object`);
  }
  const result = MasterupAudioConfigSchema.safeParse(
    snakeToCamel(audioSection)
  );
  if (!result.success) {
    throw new Error(`config: invalid masterup audio config at ${path}`);
  }
  return result.data;
};
