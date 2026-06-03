// chrome.storage.local 経由のサーバー URL 保存を @wxt-dev/storage の型付き wrapper で
// 書き換える (要件4)。key は shared/constants の STORAGE_KEY を SSOT とする。
import { storage } from "wxt/utils/storage";

import { DEFAULT_URL, STORAGE_KEY } from "../../shared/constants";

/** サーバー URL の型付き storage item。未設定時は DEFAULT_URL を返す。 */
export const serverUrlItem = storage.defineItem<string>(`local:${STORAGE_KEY}`, {
  fallback: DEFAULT_URL,
});
