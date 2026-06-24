// chrome.storage.local 経由のサーバー URL 保存を @wxt-dev/storage の型付き wrapper で
// 書き換える (要件4)。key は shared/constants の STORAGE_KEY を SSOT とする。
import { storage } from "wxt/utils/storage";

import {
  DEFAULT_URL,
  DOWNLOAD_FORMAT_DEFAULT,
  DOWNLOAD_FORMAT_KEY,
  type DownloadFormat,
  STORAGE_KEY,
} from "../../shared/constants";

/** サーバー URL の型付き storage item。未設定時は DEFAULT_URL を返す。 */
export const serverUrlItem = storage.defineItem<string>(`local:${STORAGE_KEY}`, {
  fallback: DEFAULT_URL,
});

export const downloadFormatItem = storage.defineItem<DownloadFormat>(`local:${DOWNLOAD_FORMAT_KEY}`, {
  fallback: DOWNLOAD_FORMAT_DEFAULT,
});
