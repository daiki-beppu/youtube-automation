// service worker。overlay command と runner progress は、送信元の同一タブへ型付き relay する。
// server state を更新する POST（配信済み記録）だけは、content/overlay からの直接 fetch を避けて
// background の extension origin + serve token で実行する（#1360、suno-helper の postDownloaded と対称）。

import { recordDistrokidRelease } from "../../shared/api";
import { requireSenderTabId } from "../../shared/tab-relay";
import { fetchLocalAsset, fetchLocalText } from "../lib/local-fetch";
import { onMessage, sendMessage } from "../lib/messaging";
import { migrateServerSourcesStorage } from "../lib/storage";

export default defineBackground(() => {
  console.info("[distrokid-helper] background service worker started");

  browser.runtime.onInstalled.addListener(() => {
    void migrateServerSourcesStorage().catch((error: unknown) => {
      console.error(
        "[distrokid-helper] legacy server source migration failed:",
        error
      );
    });
  });

  browser.action.onClicked.addListener((tab) => {
    if (typeof tab.id !== "number") {
      return;
    }
    void sendMessage("toggleOverlay", undefined, tab.id).catch(
      (error: unknown) => {
        console.warn("[distrokid-helper] overlay toggle relay failed:", error);
      }
    );
  });

  onMessage("fetchLocalText", ({ data }) => fetchLocalText(data));
  onMessage("fetchLocalAsset", ({ data }) => fetchLocalAsset(data));

  onMessage("injectStart", ({ data, sender }) =>
    sendMessage("injectStart", data, requireSenderTabId(sender, "injectStart"))
  );
  onMessage("injectTrack", ({ data, sender }) =>
    sendMessage("injectTrack", data, requireSenderTabId(sender, "injectTrack"))
  );
  onMessage("injectCover", ({ data, sender }) =>
    sendMessage("injectCover", data, requireSenderTabId(sender, "injectCover"))
  );
  onMessage("injectFinish", ({ sender }) =>
    sendMessage(
      "injectFinish",
      undefined,
      requireSenderTabId(sender, "injectFinish")
    )
  );
  onMessage("stop", ({ sender }) =>
    sendMessage("stop", undefined, requireSenderTabId(sender, "stop"))
  );
  onMessage("progress", ({ data, sender }) =>
    sendMessage("progress", data, requireSenderTabId(sender, "progress"))
  );

  // overlay → background: 配信済み記録。token 取得と 403 retry は shared/api に委譲する。
  // 失敗（reject）は overlay 側が warning 表示に変換し、フィル成功は覆さない（#934 の契約を維持）。
  onMessage("recordRelease", async ({ data }) => {
    await recordDistrokidRelease(data.baseUrl, data.record);
  });
});
