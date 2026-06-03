// サーバー URL の永続化（@wxt-dev/storage）。
//
// 実 read/write は chrome.storage が必要なため拡張ランタイム側でのみ動く。
// 既定値は yt-collection-serve の DEFAULT_PORT=7873 と一致させる（suno-helper と対称）。

import { storage } from "@wxt-dev/storage";

// popup のサーバー URL 入力の初期値。yt-collection-serve の既定ポートを指す。
export const DEFAULT_SERVER_URL = "http://localhost:7873";

// サーバー URL の永続化アイテム（local area）。
export const serverUrlItem = storage.defineItem<string>("local:serverUrl", {
  fallback: DEFAULT_SERVER_URL,
});
