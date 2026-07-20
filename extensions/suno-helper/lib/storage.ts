// chrome.storage.local 経由のサーバー URL 保存を @wxt-dev/storage の型付き wrapper で
// 書き換える (要件4)。key は shared/constants の STORAGE_KEY を SSOT とする。
import { storage } from "wxt/utils/storage";

import {
  COMPLETION_SOUND_SETTINGS_KEY,
  DEFAULT_URL,
  DOWNLOAD_FORMAT_DEFAULT,
  DOWNLOAD_FORMAT_KEY,
  SERVER_SOURCES_STORAGE_KEY,
  STORAGE_KEY,
} from "../../shared/constants";
import { migrateLegacyServerSources } from "../../shared/server-source-migration";
import {
  DEFAULT_COMPLETION_SOUND_SETTINGS,
  normalizeCompletionSoundSettings,
  type CompletionSoundSettings,
} from "./completion-sound";

/** サーバー URL の型付き storage item。未設定時は DEFAULT_URL を返す。 */
export const serverUrlItem = storage.defineItem<string>(
  `local:${STORAGE_KEY}`,
  { fallback: DEFAULT_URL }
);

const legacyServerSourcesItem = storage.defineItem(
  `local:${SERVER_SOURCES_STORAGE_KEY}`
);

/** Suno ダウンロード形式の union 型 (#1215)。postDownloaded の payload と一致させる。 */
export type DownloadFormat = "mp3" | "m4a" | "wav";

/** Suno ダウンロード形式の型付き storage item (#1215)。未設定時は "mp3" を返す。 */
export const downloadFormatItem = storage.defineItem<DownloadFormat>(
  `local:${DOWNLOAD_FORMAT_KEY}`,
  {
    fallback: DOWNLOAD_FORMAT_DEFAULT,
  }
);

const DOWNLOAD_FORMAT_VALUES = ["mp3", "m4a", "wav"] as const;

export function normalizeDownloadFormat(value: unknown): DownloadFormat {
  return DOWNLOAD_FORMAT_VALUES.includes(value as DownloadFormat)
    ? (value as DownloadFormat)
    : DOWNLOAD_FORMAT_DEFAULT;
}

export async function readDownloadFormat(): Promise<DownloadFormat> {
  const value: unknown = await downloadFormatItem.getValue();
  const normalized = normalizeDownloadFormat(value);
  if (normalized !== value) {
    await downloadFormatItem.setValue(normalized);
  }
  return normalized;
}

/** 完了音設定。初回は ON + chime、旧/不正値は read 時に正規化して自己修復する。 */
export const completionSoundSettingsItem =
  storage.defineItem<CompletionSoundSettings>(
    `local:${COMPLETION_SOUND_SETTINGS_KEY}`,
    { fallback: DEFAULT_COMPLETION_SOUND_SETTINGS }
  );

export async function readCompletionSoundSettings(): Promise<CompletionSoundSettings> {
  const value: unknown = await completionSoundSettingsItem.getValue();
  const normalized = normalizeCompletionSoundSettings(value);
  if (
    !value ||
    typeof value !== "object" ||
    (value as Partial<CompletionSoundSettings>).enabled !==
      normalized.enabled ||
    (value as Partial<CompletionSoundSettings>).preset !== normalized.preset
  ) {
    await completionSoundSettingsItem.setValue(normalized);
  }
  return normalized;
}

export async function migrateServerSourcesStorage(): Promise<void> {
  await migrateLegacyServerSources(legacyServerSourcesItem);
}
