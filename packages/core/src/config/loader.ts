// `config/channel/*.json` を glob ロード・バリデーションし `ChannelConfig` を組み立てる。
// singleton + reset + channelDir + localizations sidecar の pre-merge を担う。

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join } from "node:path";

import { z } from "zod";

import { ChannelConfigSchema } from "./config.ts";
import type { ChannelConfig } from "./config.ts";
import { isPlainObject } from "./internal.ts";

let instance: ChannelConfig | null = null;
let channelDirCache: string | null = null;

const LOCALIZATIONS_FILENAME = "localizations.json";
const LOCALIZATIONS_KEY = "localizations";

const isDir = (path: string): boolean =>
  existsSync(path) && statSync(path).isDirectory();

// zod の issue 列を `config:` prefix の 1 行メッセージへ整形する（path. + message）。
const formatIssuePath = (path: z.ZodIssue["path"]): string | null => {
  if (path.length === 0) {
    return null;
  }

  const [first, ...rest] = path;
  if (first === LOCALIZATIONS_KEY) {
    if (rest.length === 0) {
      return LOCALIZATIONS_FILENAME;
    }
    return `${LOCALIZATIONS_FILENAME}: ${rest.map(String).join(".")}`;
  }

  return path.map(String).join(".");
};

const formatZodError = (error: z.ZodError): string =>
  error.issues
    .map((issue) => {
      const path = formatIssuePath(issue.path);
      return path === null ? issue.message : `${path}: ${issue.message}`;
    })
    .join("; ");

// CHANNEL_DIR 環境変数を優先し、未設定なら CWD 祖先を辿って config/channel/ を探す。
const resolveChannelDir = (): string => {
  const env = process.env.CHANNEL_DIR;
  if (env) {
    return env;
  }
  let current = process.cwd();
  for (;;) {
    if (isDir(join(current, "config", "channel"))) {
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

/** チャンネルディレクトリを返す（シングルトン解決）。 */
export const channelDir = (): string => {
  if (channelDirCache === null) {
    channelDirCache = resolveChannelDir();
  }
  return channelDirCache;
};

/** シングルトン state をリセット（テスト用）。 */
export const reset = (): void => {
  instance = null;
  channelDirCache = null;
};

// 各ファイルを parse し、トップレベルキー重複を検出しつつ 1 つの object へマージ。
const loadAndMerge = (files: string[]): Record<string, unknown> => {
  const merged: Record<string, unknown> = {};
  const keyOrigin: Record<string, string> = {};
  for (const path of files) {
    let data: unknown;
    try {
      data = JSON.parse(readFileSync(path, "utf-8"));
    } catch (error) {
      throw new Error(`config: JSON パース失敗: ${path}: ${String(error)}`, {
        cause: error,
      });
    }
    if (!isPlainObject(data)) {
      throw new Error(
        `config: ${path} のトップレベルは object でなければなりません`
      );
    }
    for (const [key, value] of Object.entries(data)) {
      if (key in merged) {
        throw new Error(
          `config: トップレベルキー '${key}' が ${keyOrigin[key]} と ${basename(path)} の両方に存在します`
        );
      }
      merged[key] = value;
      keyOrigin[key] = basename(path);
    }
  }
  return merged;
};

// localizations.json（config/ 直下・config/channel/ の外）を raw のまま読み込む。
const loadLocalizationsRaw = (channelRoot: string): unknown | undefined => {
  const locPath = join(channelRoot, "config", LOCALIZATIONS_FILENAME);
  if (!existsSync(locPath)) {
    return undefined;
  }
  try {
    return JSON.parse(readFileSync(locPath, "utf-8"));
  } catch (error) {
    throw new Error(
      `config: ${LOCALIZATIONS_FILENAME} の JSON パース失敗: ${locPath}: ${String(error)}`,
      { cause: error }
    );
  }
};

const mergeLocalizations = (
  merged: Record<string, unknown>,
  localizationsRaw: unknown | undefined
): Record<string, unknown> => {
  if (LOCALIZATIONS_KEY in merged) {
    throw new Error(
      `config: '${LOCALIZATIONS_KEY}' キーは config/channel/*.json ではなく config/${LOCALIZATIONS_FILENAME} に配置してください`
    );
  }
  if (localizationsRaw === undefined) {
    return merged;
  }
  return { ...merged, [LOCALIZATIONS_KEY]: localizationsRaw };
};

const build = (channelRoot: string): ChannelConfig => {
  const channelSubdir = join(channelRoot, "config", "channel");
  const legacyPath = join(channelRoot, "config", "channel_config.json");

  if (existsSync(legacyPath)) {
    throw new Error(
      `config: 旧 channel_config.json が残っています: ${legacyPath}\nyt-config-migrate で新構造 (config/channel/*.json) へ変換してください`
    );
  }
  if (!isDir(channelSubdir)) {
    throw new Error(
      `config: config/channel/ ディレクトリが見つかりません: ${channelSubdir}`
    );
  }

  const files = readdirSync(channelSubdir)
    .filter((name) => name.endsWith(".json"))
    .toSorted()
    .map((name) => join(channelSubdir, name));
  if (files.length === 0) {
    throw new Error(
      `config: config/channel/ に JSON ファイルが 1 つもありません: ${channelSubdir}`
    );
  }

  const merged = mergeLocalizations(
    loadAndMerge(files),
    loadLocalizationsRaw(channelRoot)
  );
  try {
    return ChannelConfigSchema.parse(merged);
  } catch (error) {
    if (error instanceof z.ZodError) {
      throw new TypeError(`config: ${formatZodError(error)}`, { cause: error });
    }
    throw error;
  }
};

/** `config/channel/*.json` を glob ロードし `ChannelConfig` を返す（シングルトン）。 */
export const loadConfig = (): ChannelConfig => {
  if (instance !== null) {
    return instance;
  }
  channelDirCache = resolveChannelDir();
  instance = build(channelDirCache);
  return instance;
};
