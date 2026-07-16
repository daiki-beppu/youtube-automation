// service worker。注入フローの型付きチャンネルは popup ↔ content 間の直接通信で完結する。
// server state を更新する POST（配信済み記録）だけは、content/popup からの直接 fetch を避けて
// background の extension origin + serve token で実行する（#1360、suno-helper の postDownloaded と対称）。

import { recordDistrokidRelease } from "../../shared/api";
import { onMessage } from "../lib/messaging";
import { migrateServerSourcesStorage } from "../lib/storage";

export default defineBackground(() => {
  console.info("[distrokid-helper] background service worker started");

  browser.runtime.onInstalled.addListener(() => {
    void migrateServerSourcesStorage().catch((error: unknown) => {
      console.error("[distrokid-helper] legacy server source migration failed:", error);
    });
  });

  // popup → background: 配信済み記録。token 取得と 403 retry は shared/api に委譲する。
  // 失敗（reject）は popup 側が warning 表示に変換し、フィル成功は覆さない（#934 の契約を維持）。
  onMessage("recordRelease", async ({ data }) => {
    await recordDistrokidRelease(data.baseUrl, data.record);
  });
});
