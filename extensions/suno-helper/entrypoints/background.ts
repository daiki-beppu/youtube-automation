// Manifest V3 service worker。
// 拡張ライフサイクルのログ、action クリック中継、および overlay ⇄ runner の content↔content 中継を担う。
// overlay (content script) は `browser.tabs.*` を呼べないため、overlay の no-tabId メッセージを受けて
// 送信元と同一タブの runner content へ tabs.sendMessage で転送する（#892, 詳細は lib/overlay-relay.ts）。
import { postCapturedPlaylists } from "../../shared/api";
import { describeRelayFailure } from "../components/runner-errors";
import { autoCapturePlaylists, captureFromTab } from "../lib/auto-capture";
import { onMessage, sendMessage } from "../lib/messaging";
import { relayTabId, requireRelayTab } from "../lib/overlay-relay";
import { serverUrlItem } from "../lib/storage";

// 自動 capture で開く Suno `/me` の URL（追加要件 A）。
const SUNO_ME_URL = "https://suno.com/me";
// bg `/me` tab の content script が capturePlaylists に応答するまでの poll 上限と間隔。
// tab 生成直後は content script 未注入で sendMessage が reject されるためリトライする。
const CAPTURE_TAB_TIMEOUT_MS = 15000;
const CAPTURE_TAB_POLL_MS = 300;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** lib/auto-capture の orchestration に実 collaborator（browser tab / messaging / storage / api）を配線する。 */
function runAutoCapture(): Promise<void> {
  return autoCapturePlaylists({
    getServerUrl: () => serverUrlItem.getValue(),
    createMeTab: () => browser.tabs.create({ url: SUNO_ME_URL, active: false }),
    removeTab: (tabId) => browser.tabs.remove(tabId),
    capture: (tabId) =>
      captureFromTab(tabId, {
        sendCapture: (id) => sendMessage("capturePlaylists", undefined, id),
        sleep,
        now: Date.now,
        timeoutMs: CAPTURE_TAB_TIMEOUT_MS,
        pollMs: CAPTURE_TAB_POLL_MS,
      }),
    post: (baseUrl, items) => postCapturedPlaylists(baseUrl, items),
  });
}

export default defineBackground(() => {
  browser.runtime.onInstalled.addListener((details) => {
    console.info(`[suno-helper] installed/updated: ${details.reason}`);
  });

  // popup 廃止 (#892): default_popup を持たないため action クリックで onClicked が発火する。
  // クリックされたタブの overlay content script へ表示 toggle を中継する。
  browser.action.onClicked.addListener((tab) => {
    if (typeof tab.id !== "number") {
      // タブ id が取れないケース（特殊ページ等）は overlay も注入されていないため中継しない。
      return;
    }
    // overlay 未注入のタブ（suno.com 以外 / 拡張リロード後の stale タブ）では必ず reject するため
    // catch して消費する。放置すると未処理 rejection としてエラーバッジに記録される（#937）。
    sendMessage("toggleOverlay", undefined, tab.id).catch((err: unknown) => {
      const { level, text } = describeRelayFailure("toggleOverlay", err instanceof Error ? err.message : String(err));
      console[level](text);
    });
  });

  // overlay → runner 中継 (#892)。overlay が送る run / stop / queryProgress を送信元と同一タブの
  // runner content へ転送し、runner の応答をそのまま overlay へ返す。tab を持たない送信元は中継不能
  // のため requireRelayTab が fail-loud で throw する（握りつぶさない）。
  onMessage("run", ({ data, sender }) => sendMessage("run", data, requireRelayTab(sender, "run")));
  onMessage("stop", ({ sender }) => sendMessage("stop", undefined, requireRelayTab(sender, "stop")));
  onMessage("queryProgress", ({ sender }) =>
    sendMessage("queryProgress", undefined, requireRelayTab(sender, "queryProgress")),
  );
  // overlay → runner 中継 (#893)。overlay の手動 Capture を送信元と同一タブの runner content へ転送し、
  // runner が自身の document を scrape した結果をそのまま overlay へ返す。
  onMessage("capturePlaylists", ({ sender }) =>
    sendMessage("capturePlaylists", undefined, requireRelayTab(sender, "capturePlaylists")),
  );

  // runner → background: 連続実行完了時の自動 capture trigger (#893 追加要件 A)。
  // bg `/me` tab を開いて scrape→POST→close する。fail soft（失敗は warning のみ、runner の FINISHED は妨げない）。
  onMessage("requestPlaylistCapture", () => {
    void runAutoCapture().catch((err) => {
      console.warn("[suno-helper] auto playlist capture failed:", err);
    });
  });

  // runner → overlay 中継 (#892)。runner content が emit する progress 通知を送信元と同一タブへ転送する
  // （content↔content 直送不可のため）。tab を持たない送信元は転送先が無いため no-op。
  onMessage("progress", ({ data, sender }) => {
    const tabId = relayTabId(sender);
    if (tabId === null) {
      return;
    }
    // ページ遷移・タブ閉鎖のレースで overlay 側リスナーが消えていると reject する。progress は
    // 高頻度かつ取りこぼしても次の通知で追いつくため、debug ログのみ残して握りつぶす（#937）。
    sendMessage("progress", data, tabId).catch((err: unknown) => {
      console.debug("[suno-helper] progress 中継先なし（overlay 消滅レース）:", err);
    });
  });
});
