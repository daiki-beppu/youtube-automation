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

// 自動 capture で開く Suno playlists ページの URL（追加要件 A）。
// Suno の URL 構造変更（/me → /me/playlists）に追従。
const SUNO_ME_URL = "https://suno.com/me/playlists";
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

  // runner → background: 連続実行完了時の自動 capture trigger (#893 追加要件 A)。
  // bg `/me` tab を開いて scrape→POST→close する。fail soft（失敗は warning のみ、runner の FINISHED は妨げない）。
  onMessage("requestPlaylistCapture", () => {
    void runAutoCapture().catch((err) => {
      console.warn("[suno-helper] auto playlist capture failed:", err);
    });
  });

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
    console.info(`[suno-helper] Download all 監視を開始します (format=${format})`);

    // 監視開始時刻を記録し、これ以前に開始されたダウンロードを除外する (#1217)。
    const monitorStartedAt = Date.now();

    // Suno の ZIP ダウンロードは "Download all" click 直後に開始される。
    // chrome.downloads.onChanged で state=complete を待ち、ファイル名パターン (.zip) で照合する。
    // 安全弁 timeout の ID を保持し、成功時に clearTimeout する (#1217)。
    const listener = (delta: chrome.downloads.DownloadDelta): void => {
      if (!delta.state || delta.state.current !== "complete") {
        return;
      }
      // 完了したダウンロードの詳細を取得してファイル名を確認する
      chrome.downloads.search({ id: delta.id }, (results) => {
        if (!results || results.length === 0) {
          return;
        }
        const item = results[0];
        const filename = item.filename ?? "";
        // Suno CDN domain check: reject downloads not originating from Suno (#1217 SEC-002).
        const downloadUrl = item.url ?? "";
        if (!downloadUrl.includes("suno.com") && !downloadUrl.includes("sunocdn.")) {
          return;
        }
        // Suno の ZIP ダウンロードは .zip 拡張子を持つ（playlist 名がファイル名に含まれる）
        if (!filename.toLowerCase().endsWith(".zip")) {
          return;
        }
        // 監視開始前に開始されたダウンロードは無関係なので無視する (#1217)。
        // item.startTime は ISO 8601 文字列。5 秒のマージンを設ける（ブラウザ内部時刻の微小ズレ対策）。
        const downloadStartMs = new Date(item.startTime).getTime();
        if (downloadStartMs < monitorStartedAt - 5000) {
          return;
        }
        console.info(`[suno-helper] ZIP ダウンロード完了: ${filename} (id=${delta.id})`);
        // listener を解除して以降のダウンロードイベントを無視する
        chrome.downloads.onChanged.removeListener(listener);
        // 安全弁タイムアウトをキャンセルして spurious warning を防ぐ (#1217)。
        clearTimeout(watchTimeoutId);
        // content script へダウンロード完了を中継する
        sendMessage("downloadComplete", { downloadId: delta.id, filename }, tabId).catch((err: unknown) => {
          console.warn("[suno-helper] downloadComplete 中継失敗:", err);
        });
      });
    };
    chrome.downloads.onChanged.addListener(listener);

    // 安全弁: 10 分以内にダウンロードが完了しなければ listener を解除する（メモリリーク防止）
    const DOWNLOAD_WATCH_TIMEOUT_MS = 600000;
    // listener closure が watchTimeoutId を非同期参照するため、宣言順を addListener の後に置く。
    // listener が発火するのはダウンロードイベント（非同期）なので初期化前アクセスは起きない。
    const watchTimeoutId = setTimeout(() => {
      chrome.downloads.onChanged.removeListener(listener);
      console.warn("[suno-helper] Download all 監視タイムアウト（10 分）。listener を解除しました。");
    }, DOWNLOAD_WATCH_TIMEOUT_MS);
  });

  // content → background: chrome.debugger で trusted Cmd+P を dispatch する (#1251)。
  // content script は chrome.debugger API にアクセスできないため background に委譲する。
  // attach → rawKeyDown + keyUp → detach を一瞬で行い、デバッグバーの表示時間を最小化する。
  onMessage("sendTrustedCmdP", async ({ data, sender }) => {
    const tabId = relayTabId(sender);
    if (tabId === null) {
      console.warn("[suno-helper] sendTrustedCmdP: 送信元タブが特定できません");
      return;
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
    }
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
