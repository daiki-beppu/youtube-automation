// chrome.storage.local 経由のサーバー URL 保存を @wxt-dev/storage の型付き wrapper で
// 書き換える (要件4)。key は shared/constants の STORAGE_KEY を SSOT とする。
import { storage } from "wxt/utils/storage";

import {
  COMPLETION_SOUND_SETTINGS_KEY,
  DEFAULT_URL,
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

export const downloadEnabledItem = storage.defineItem<boolean>(
  "local:sunoDownloadEnabled",
  { fallback: true }
);

const legacyServerSourcesItem = storage.defineItem(
  `local:${SERVER_SOURCES_STORAGE_KEY}`
);

/** 通知設定。旧 preset は enabled を維持したまま read 時に削除する。 */
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
    Object.keys(value).some((key) => key !== "enabled")
  ) {
    await completionSoundSettingsItem.setValue(normalized);
  }
  return normalized;
}

export async function migrateServerSourcesStorage(): Promise<void> {
  await migrateLegacyServerSources(legacyServerSourcesItem);
}
