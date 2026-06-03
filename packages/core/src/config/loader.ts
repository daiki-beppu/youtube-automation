// `config/channel/*.json` を glob ロード・バリデーションし `ChannelConfig` を組み立てる。
// Python `utils/config/loader.py` の移植（singleton + reset + channelDir + cross-file 検証）。

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join } from "node:path";

import { ConfigError } from "../errors.ts";
import { parseAnalytics } from "./analytics.ts";
import { parseAudio } from "./audio.ts";
import { parseComments } from "./comments.ts";
import type { ChannelConfig } from "./config.ts";
import { parseContent } from "./content.ts";
import type { Content } from "./content.ts";
import { parseDistrokid } from "./distrokid.ts";
import { isRecord } from "./internal.ts";
import { localizationsAbsent, parseLocalizations } from "./localizations.ts";
import type { Localizations } from "./localizations.ts";
import { parseMeta } from "./meta.ts";
import { parsePinnedComment } from "./pinned-comment.ts";
import { parsePlaylists } from "./playlists.ts";
import { parseShorts } from "./shorts.ts";
import { parseWorkflow } from "./workflow.ts";
import { parseYoutube } from "./youtube.ts";
import type { YoutubeSection } from "./youtube.ts";

let instance: ChannelConfig | null = null;
let channelDirCache: string | null = null;

// 必須キー（ドット区切り）。分割前の `_REQUIRED_KEYS` を新構造へ分配。
const REQUIRED_KEYS_BY_SECTION: Record<string, string[]> = {
  "content.json": [
    "genre.primary",
    "genre.style",
    "genre.context",
    "tags.base",
    "tags.themes",
    "descriptions.opening",
    "descriptions.perfect_for",
    "descriptions.hashtags",
    "title.template",
  ],
  "meta.json": [
    "channel.name",
    "channel.short",
    "channel.youtube_handle",
    "channel.url",
  ],
  "youtube.json": [
    "youtube.category_id",
    "youtube.privacy_status",
    "youtube.language",
  ],
};

const isDir = (path: string): boolean =>
  existsSync(path) && statSync(path).isDirectory();

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
  throw new ConfigError(
    "CHANNEL_DIR 環境変数を設定するか、config/channel/ を持つディレクトリ配下で実行してください"
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
      throw new ConfigError(`JSON パース失敗: ${path}: ${String(error)}`);
    }
    if (!isRecord(data)) {
      throw new ConfigError(
        `${path} のトップレベルは object でなければなりません`
      );
    }
    for (const [key, value] of Object.entries(data)) {
      if (key in merged) {
        throw new ConfigError(
          `トップレベルキー '${key}' が ${keyOrigin[key]} と ${basename(path)} の両方に存在します`
        );
      }
      merged[key] = value;
      keyOrigin[key] = basename(path);
    }
  }
  return merged;
};

// 必須キーをドット区切りパスで検証し、欠落をまとめて報告。
const validateRequired = (merged: Record<string, unknown>): void => {
  const missing: string[] = [];
  for (const keys of Object.values(REQUIRED_KEYS_BY_SECTION)) {
    for (const keyPath of keys) {
      let current: unknown = merged;
      for (const part of keyPath.split(".")) {
        if (!isRecord(current) || !(part in current)) {
          missing.push(keyPath);
          break;
        }
        current = current[part];
      }
    }
  }
  if (missing.length > 0) {
    throw new ConfigError(
      `config/channel/ に必須キーがありません: ${missing.join(", ")}`
    );
  }
};

const loadLocalizations = (
  channelRoot: string,
  fallbackLanguage: string
): Localizations => {
  const locPath = join(channelRoot, "config", "localizations.json");
  if (!existsSync(locPath)) {
    return localizationsAbsent(fallbackLanguage);
  }
  let data: unknown;
  try {
    data = JSON.parse(readFileSync(locPath, "utf-8"));
  } catch (error) {
    throw new ConfigError(
      `localizations.json の JSON パース失敗: ${locPath}: ${String(error)}`
    );
  }
  return parseLocalizations(data);
};

// ファイル跨ぎ整合性チェック（違反はすべて ConfigError）。
const validateCrossFile = (
  youtube: YoutubeSection,
  content: Content,
  localizations: Localizations
): void => {
  // 1. content_model.languages ⊆ localizations.supported_languages（localizations 存在時）
  if (localizations.exists) {
    const unknownLangs = youtube.contentModel.languages.filter(
      (lang) => !localizations.supportedLanguages.includes(lang)
    );
    if (unknownLangs.length > 0) {
      throw new ConfigError(
        `content_model.languages に localizations.supported_languages へ未登録の言語があります: ${JSON.stringify(unknownLangs)}`
      );
    }
  }

  // 2. title.theme_scenes のキー ⊆ tags.themes のキー
  const themeKeys = new Set(Object.keys(content.tags.themes));
  const unknownScenes = Object.keys(content.title.themeScenes)
    .filter((key) => !themeKeys.has(key))
    .toSorted();
  if (unknownScenes.length > 0) {
    throw new ConfigError(
      `title.theme_scenes に tags.themes で定義されていないテーマキーがあります: ${JSON.stringify(unknownScenes)}`
    );
  }
};

const assemble = (
  merged: Record<string, unknown>,
  channelRoot: string
): ChannelConfig => {
  const meta = parseMeta(merged);
  const content = parseContent(merged, meta.channelName);
  const youtube = parseYoutube(merged);
  const localizations = loadLocalizations(channelRoot, youtube.api.language);

  validateCrossFile(youtube, content, localizations);

  return {
    analytics: parseAnalytics(merged),
    audio: parseAudio(merged),
    comments: parseComments(merged),
    content,
    distrokid: parseDistrokid(merged),
    localizations,
    meta,
    pinnedComment: parsePinnedComment(merged),
    playlists: parsePlaylists(merged),
    shorts: parseShorts(merged),
    workflow: parseWorkflow(merged),
    youtube,
  };
};

const build = (channelRoot: string): ChannelConfig => {
  const channelSubdir = join(channelRoot, "config", "channel");
  const legacyPath = join(channelRoot, "config", "channel_config.json");

  if (existsSync(legacyPath)) {
    throw new ConfigError(
      `旧 channel_config.json が残っています: ${legacyPath}\nyt-config-migrate で新構造 (config/channel/*.json) へ変換してください`
    );
  }
  if (!isDir(channelSubdir)) {
    throw new ConfigError(
      `config/channel/ ディレクトリが見つかりません: ${channelSubdir}`
    );
  }

  const files = readdirSync(channelSubdir)
    .filter((name) => name.endsWith(".json"))
    .toSorted()
    .map((name) => join(channelSubdir, name));
  if (files.length === 0) {
    throw new ConfigError(
      `config/channel/ に JSON ファイルが 1 つもありません: ${channelSubdir}`
    );
  }

  const merged = loadAndMerge(files);
  validateRequired(merged);
  return assemble(merged, channelRoot);
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
