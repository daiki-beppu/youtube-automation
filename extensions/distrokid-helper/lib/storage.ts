// サーバー URL の永続化（@wxt-dev/storage）。
//
// 実 read/write は chrome.storage が必要なため拡張ランタイム側でのみ動く。
// 既定値は shared/constants.ts の DEFAULT_URL を SSOT として参照する。

import { storage } from "@wxt-dev/storage";

import {
  DEFAULT_URL,
  SERVER_SOURCES_STORAGE_KEY,
} from "../../shared/constants";
import { migrateLegacyServerSources } from "../../shared/server-source-migration";

// サーバー URL の永続化アイテム（local area）。
export const serverUrlItem = storage.defineItem<string>("local:serverUrl", {
  fallback: DEFAULT_URL,
});

const legacyServerSourcesItem = storage.defineItem(
  `local:${SERVER_SOURCES_STORAGE_KEY}`
);

export async function migrateServerSourcesStorage(): Promise<void> {
  await migrateLegacyServerSources(legacyServerSourcesItem);
}
