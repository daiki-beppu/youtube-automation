// Manifest V3 service worker。
// 拡張ライフサイクルのログ、action クリック中継、および overlay ⇄ runner の content↔content 中継を担う。
// overlay (content script) は `browser.tabs.*` を呼べないため、overlay の no-tabId メッセージを受けて
// 送信元と同一タブの runner content へ tabs.sendMessage で転送する（#892, 詳細は lib/overlay-relay.ts）。
import { postDownloaded } from "../../shared/api";
import { describeRelayFailure } from "../components/runner-errors";
import { onMessage, sendMessage } from "../lib/messaging";
import { relayTabId, requireRelayTab } from "../lib/overlay-relay";

export default defineBackground(() => {
  let activeDownloadWatcher: { tabId: number; cleanup: () => void } | null = null;

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
  onMessage("retryPlaylist", ({ data, sender }) =>
    sendMessage("retryPlaylist", data, requireRelayTab(sender, "retryPlaylist")),
  );
  onMessage("retryDownload", ({ data, sender }) =>
    sendMessage("retryDownload", data, requireRelayTab(sender, "retryDownload")),
  );
  onMessage("queryProgress", ({ sender }) =>
    sendMessage("queryProgress", undefined, requireRelayTab(sender, "queryProgress")),
  );
  // overlay → runner 中継 (#893)。overlay の手動 Capture を送信元と同一タブの runner content へ転送し、
  // runner が自身の document を scrape した結果をそのまま overlay へ返す。
  onMessage("capturePlaylists", ({ sender }) =>
    sendMessage("capturePlaylists", undefined, requireRelayTab(sender, "capturePlaylists")),
  );

  // runner → background: Download all 開始通知 (#1146)。content script は chrome.downloads API に
  // アクセスできないため、background が chrome.downloads.onChanged を監視して完了を中継する。
  // ダウンロード監視は startDownload 受信時に listener を登録し、完了時に自動解除する。
  onMessage("startDownload", ({ data, sender }) => {
    const tabId = relayTabId(sender);
    if (tabId === null) {
      console.warn("[suno-helper] startDownload: 送信元タブが特定できません");
      return;
    }
    const { format } = data;
    if (activeDownloadWatcher !== null) {
      sendMessage(
        "downloadFailed",
        { message: "別の Download all 監視が進行中です。完了後に再実行してください。" },
        tabId,
      ).catch((err: unknown) => {
        console.warn("[suno-helper] downloadFailed 中継失敗:", err);
      });
      return;
    }
    console.info(`[suno-helper] Download all 監視を開始します (format=${format})`);

    // 監視開始時刻を記録し、これ以前に開始されたダウンロードを除外する (#1217)。
    const monitorStartedAt = Date.now();

    // Suno の ZIP ダウンロードは "Download all" click 直後に開始される。
    // chrome.downloads.onChanged で state=complete を待ち、ファイル名パターン (.zip) で照合する。
    // 安全弁 timeout の ID を保持し、成功時に clearTimeout する (#1217)。
    const notifyDownloadFailed = (message: string): void => {
      sendMessage("downloadFailed", { message }, tabId).catch((err: unknown) => {
        console.warn("[suno-helper] downloadFailed 中継失敗:", err);
      });
    };

    const isSunoZipStartedAfterMonitor = (item: chrome.downloads.DownloadItem): boolean => {
      const filename = item.filename ?? "";
      if (!filename.toLowerCase().endsWith(".zip")) {
        return false;
      }
      const downloadUrl = item.url ?? "";
      let isSunoUrl = false;
      try {
        const hostname = new URL(downloadUrl).hostname;
        isSunoUrl =
          hostname === "suno.com" ||
          hostname.endsWith(".suno.com") ||
          hostname === "sunocdn.com" ||
          hostname.endsWith(".sunocdn.com");
      } catch {
        return false;
      }
      if (!isSunoUrl) {
        return false;
      }
      const downloadStartMs = new Date(item.startTime).getTime();
      return Number.isFinite(downloadStartMs) && downloadStartMs >= monitorStartedAt - 5000;
    };

    const watchTimeout: { id?: ReturnType<typeof setTimeout> } = {};
    const cleanupWatcher = (): void => {
      chrome.downloads.onChanged.removeListener(listener);
      if (watchTimeout.id !== undefined) {
        clearTimeout(watchTimeout.id);
      }
      if (activeDownloadWatcher?.cleanup === cleanupWatcher) {
        activeDownloadWatcher = null;
      }
    };

    const listener = (delta: chrome.downloads.DownloadDelta): void => {
      const state = delta.state?.current;
      if (state !== "complete" && state !== "interrupted") {
        return;
      }
      // 完了したダウンロードの詳細を取得してファイル名を確認する
      chrome.downloads.search({ id: delta.id }, (results) => {
        if (!results || results.length === 0) {
          return;
        }
        const item = results[0];
        const filename = item.filename ?? "";
        if (!isSunoZipStartedAfterMonitor(item)) {
          return;
        }
        if (state === "interrupted") {
          const message = `ZIP ダウンロードが中断されました: ${filename} (id=${delta.id})`;
          console.warn(`[suno-helper] ${message}`);
          cleanupWatcher();
          notifyDownloadFailed(message);
          return;
        }
        console.info(`[suno-helper] ZIP ダウンロード完了: ${filename} (id=${delta.id})`);
        // listener を解除して以降のダウンロードイベントを無視する
        cleanupWatcher();
        // content script へダウンロード完了を中継する
        sendMessage("downloadComplete", { filename }, tabId).catch((err: unknown) => {
          console.warn("[suno-helper] downloadComplete 中継失敗:", err);
        });
      });
    };
    chrome.downloads.onChanged.addListener(listener);
    activeDownloadWatcher = { tabId, cleanup: cleanupWatcher };

    // 安全弁: 10 分以内にダウンロードが完了しなければ listener を解除する（メモリリーク防止）
    const DOWNLOAD_WATCH_TIMEOUT_MS = 600000;
    watchTimeout.id = setTimeout(() => {
      const message = "Download all 監視タイムアウト（10 分）。listener を解除しました。";
      console.warn(`[suno-helper] ${message}`);
      cleanupWatcher();
      notifyDownloadFailed(message);
    }, DOWNLOAD_WATCH_TIMEOUT_MS);
  });

  onMessage("cancelDownload", ({ sender }) => {
    const tabId = relayTabId(sender);
    if (activeDownloadWatcher && (tabId === null || activeDownloadWatcher.tabId === tabId)) {
      activeDownloadWatcher.cleanup();
    }
  });

  // content → background: chrome.debugger で trusted Cmd+P を dispatch する (#1251)。
  // content script は chrome.debugger API にアクセスできないため background に委譲する。
  // attach → rawKeyDown + keyUp → detach を一瞬で行い、デバッグバーの表示時間を最小化する。
  onMessage("sendTrustedCmdP", async ({ data, sender }) => {
    const tabId = relayTabId(sender);
    if (tabId === null) {
      throw new Error("sendTrustedCmdP: 送信元タブが特定できません");
    }
    const { isMac } = data;
    const modifiers = isMac ? 4 : 2; // 4=Meta, 2=Ctrl
    const target: chrome.debugger.Debuggee = { tabId };
    try {
      await chrome.debugger.attach(target, "1.3");
      try {
        await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
          type: "rawKeyDown",
          modifiers,
          key: "p",
          windowsVirtualKeyCode: 80,
          nativeVirtualKeyCode: 80,
        });
        await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
          type: "keyUp",
          modifiers,
          key: "p",
          windowsVirtualKeyCode: 80,
          nativeVirtualKeyCode: 80,
        });
      } finally {
        await chrome.debugger.detach(target);
      }
    } catch (err) {
      console.warn("[suno-helper] sendTrustedCmdP failed:", err);
      throw err;
    }
  });

  // runner → background: content script から localhost server へ直接 token 取得しないよう、
  // token fetch と POST /downloaded は background の extension origin から実行する。
  onMessage("postDownloaded", ({ data }) => postDownloaded(data.baseUrl, data.collectionId, data.body));

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
