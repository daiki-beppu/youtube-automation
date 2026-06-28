// Manifest V3 service worker。
// 拡張ライフサイクルのログ、action クリック中継、および overlay ⇄ runner の content↔content 中継を担う。
// overlay (content script) は `browser.tabs.*` を呼べないため、overlay の no-tabId メッセージを受けて
// 送信元と同一タブの runner content へ tabs.sendMessage で転送する（#892, 詳細は lib/overlay-relay.ts）。
import { postDownloaded } from "../../shared/api";
import { describeRelayFailure } from "../components/runner-errors";
import { captureFromTab } from "../lib/auto-capture";
import { onMessage, sendMessage } from "../lib/messaging";
import { relayTabId, requireRelayTab } from "../lib/overlay-relay";

export default defineBackground(() => {
  const SUNO_ME_PLAYLISTS_URL = "https://suno.com/me/playlists";
  const PLAYLIST_URL_RESOLVE_TIMEOUT_MS = 15000;
  const PLAYLIST_URL_RESOLVE_POLL_MS = 500;
  const TRUSTED_DOWNLOAD_HOST_SUFFIXES = [".suno.com", ".suno.ai"];
  const DOWNLOAD_WATCHER_SESSION_KEY = "suno-helper:downloadWatcher";
  const DOWNLOAD_COMPLETE_POLL_MS = 3000;
  const DOWNLOAD_WATCH_TIMEOUT_MS = 600000;

  interface DownloadWatcherState {
    tabId: number;
    monitorStartedAt: number;
    targetDownloadId: number | null;
  }

  let activeDownloadWatcher: DownloadWatcherState | null = null;
  const watchTimeout: { id?: ReturnType<typeof setTimeout> } = {};
  const completedPoll: { id?: ReturnType<typeof setInterval> } = {};

  const isTrustedSunoDownloadUrl = (value: string | undefined): boolean => {
    if (!value) {
      return false;
    }
    try {
      const { hostname } = new URL(value);
      return hostname === "suno.com" || TRUSTED_DOWNLOAD_HOST_SUFFIXES.some((suffix) => hostname.endsWith(suffix));
    } catch {
      return false;
    }
  };

  const isTrustedSunoDownload = (item: chrome.downloads.DownloadItem): boolean =>
    isTrustedSunoDownloadUrl(item.url) ||
    isTrustedSunoDownloadUrl(item.finalUrl) ||
    isTrustedSunoDownloadUrl(item.referrer);

  const isZipStartedAfterMonitor = (item: chrome.downloads.DownloadItem, monitorStartedAt: number): boolean => {
    const filename = item.filename ?? "";
    if (!filename.toLowerCase().endsWith(".zip")) {
      return false;
    }
    if (!isTrustedSunoDownload(item)) {
      return false;
    }
    const downloadStartMs = new Date(item.startTime).getTime();
    return Number.isFinite(downloadStartMs) && downloadStartMs >= monitorStartedAt - 5000;
  };

  const normalizeWatcherState = (value: unknown): DownloadWatcherState | null => {
    if (typeof value !== "object" || value === null) {
      return null;
    }
    const record = value as Record<string, unknown>;
    if (typeof record.tabId !== "number" || typeof record.monitorStartedAt !== "number") {
      return null;
    }
    const targetDownloadId =
      typeof record.targetDownloadId === "number" || record.targetDownloadId === null ? record.targetDownloadId : null;
    return {
      tabId: record.tabId,
      monitorStartedAt: record.monitorStartedAt,
      targetDownloadId,
    };
  };

  const readStoredWatcherState = (): Promise<DownloadWatcherState | null> =>
    new Promise((resolve) => {
      if (!chrome.storage?.session) {
        resolve(null);
        return;
      }
      chrome.storage.session.get(DOWNLOAD_WATCHER_SESSION_KEY, (items) => {
        resolve(normalizeWatcherState(items[DOWNLOAD_WATCHER_SESSION_KEY]));
      });
    });

  const persistWatcherState = (watcher: DownloadWatcherState): void => {
    if (!chrome.storage?.session) {
      return;
    }
    chrome.storage.session.set({ [DOWNLOAD_WATCHER_SESSION_KEY]: watcher });
  };

  const clearStoredWatcherState = (): void => {
    if (!chrome.storage?.session) {
      return;
    }
    chrome.storage.session.remove(DOWNLOAD_WATCHER_SESSION_KEY);
  };

  const setActiveDownloadWatcher = (watcher: DownloadWatcherState): void => {
    activeDownloadWatcher = watcher;
    persistWatcherState(watcher);
    scheduleWatcherTimers(watcher);
  };

  const replaceActiveDownloadWatcher = (
    current: DownloadWatcherState,
    next: DownloadWatcherState,
  ): DownloadWatcherState => {
    if (activeDownloadWatcher !== current) {
      return current;
    }
    activeDownloadWatcher = next;
    persistWatcherState(next);
    scheduleWatcherTimers(next);
    return next;
  };

  const cleanupWatcher = (watcher: DownloadWatcherState): void => {
    if (activeDownloadWatcher !== watcher) {
      return;
    }
    activeDownloadWatcher = null;
    if (watchTimeout.id !== undefined) {
      clearTimeout(watchTimeout.id);
      watchTimeout.id = undefined;
    }
    if (completedPoll.id !== undefined) {
      clearInterval(completedPoll.id);
      completedPoll.id = undefined;
    }
    clearStoredWatcherState();
  };

  const notifyDownloadFailed = (watcher: DownloadWatcherState, message: string): void => {
    sendMessage("downloadFailed", { message }, watcher.tabId).catch((err: unknown) => {
      console.warn("[suno-helper] downloadFailed 中継失敗:", err);
    });
  };

  const notifyDownloadComplete = (watcher: DownloadWatcherState, filename: string, id?: number): void => {
    if (activeDownloadWatcher !== watcher) {
      return;
    }
    console.info(`[suno-helper] ZIP ダウンロード完了: ${filename}${id === undefined ? "" : ` (id=${id})`}`);
    cleanupWatcher(watcher);
    sendMessage("downloadComplete", { filename }, watcher.tabId).catch((err: unknown) => {
      console.warn("[suno-helper] downloadComplete 中継失敗:", err);
    });
  };

  const findTargetDownload = (
    watcher: DownloadWatcherState,
    callback: (item: chrome.downloads.DownloadItem | null) => void,
  ): void => {
    if (watcher.targetDownloadId === null) {
      chrome.downloads.search({ state: "complete", limit: 50, orderBy: ["-startTime"] }, (results) => {
        callback(results.find((item) => isZipStartedAfterMonitor(item, watcher.monitorStartedAt)) ?? null);
      });
      return;
    }
    chrome.downloads.search({ id: watcher.targetDownloadId }, (results) => {
      callback(results[0] ?? null);
    });
  };

  function scheduleWatcherTimers(watcher: DownloadWatcherState): void {
    if (watchTimeout.id !== undefined) {
      clearTimeout(watchTimeout.id);
    }
    if (completedPoll.id !== undefined) {
      clearInterval(completedPoll.id);
    }
    completedPoll.id = setInterval(() => {
      findTargetDownload(watcher, (item) => {
        if (item && item.state === "complete" && isZipStartedAfterMonitor(item, watcher.monitorStartedAt)) {
          const currentWatcher =
            watcher.targetDownloadId === null
              ? replaceActiveDownloadWatcher(watcher, { ...watcher, targetDownloadId: item.id })
              : watcher;
          notifyDownloadComplete(currentWatcher, item.filename ?? "", item.id);
        }
      });
    }, DOWNLOAD_COMPLETE_POLL_MS);

    const elapsedMs = Date.now() - watcher.monitorStartedAt;
    watchTimeout.id = setTimeout(
      () => {
        findTargetDownload(watcher, (item) => {
          if (item && item.state === "complete" && isZipStartedAfterMonitor(item, watcher.monitorStartedAt)) {
            const currentWatcher =
              watcher.targetDownloadId === null
                ? replaceActiveDownloadWatcher(watcher, { ...watcher, targetDownloadId: item.id })
                : watcher;
            notifyDownloadComplete(currentWatcher, item.filename ?? "", item.id);
            return;
          }
          const message = "Download all 監視タイムアウト（10 分）。listener を解除しました。";
          console.warn(`[suno-helper] ${message}`);
          cleanupWatcher(watcher);
          notifyDownloadFailed(watcher, message);
        });
      },
      Math.max(0, DOWNLOAD_WATCH_TIMEOUT_MS - elapsedMs),
    );
  }

  const withWatcherState = (fn: (watcher: DownloadWatcherState) => void): void => {
    if (activeDownloadWatcher !== null) {
      fn(activeDownloadWatcher);
      return;
    }
    void readStoredWatcherState().then((watcher) => {
      if (watcher === null) {
        return;
      }
      activeDownloadWatcher = watcher;
      scheduleWatcherTimers(watcher);
      fn(watcher);
    });
  };

  const createdListener = (item: chrome.downloads.DownloadItem): void => {
    withWatcherState((watcher) => {
      if (watcher.targetDownloadId !== null || !isZipStartedAfterMonitor(item, watcher.monitorStartedAt)) {
        return;
      }
      replaceActiveDownloadWatcher(watcher, { ...watcher, targetDownloadId: item.id });
    });
  };

  const handleDownloadState = (
    watcher: DownloadWatcherState,
    item: chrome.downloads.DownloadItem,
    state: "complete" | "interrupted",
  ): void => {
    const filename = item.filename ?? "";
    if (!isZipStartedAfterMonitor(item, watcher.monitorStartedAt)) {
      console.debug("[suno-helper] Download all 監視対象外の download event を無視:", {
        filename,
        url: item.url,
        startTime: item.startTime,
        state,
      });
      return;
    }
    const currentWatcher =
      watcher.targetDownloadId === null
        ? replaceActiveDownloadWatcher(watcher, { ...watcher, targetDownloadId: item.id })
        : watcher;
    if (state === "interrupted") {
      const message = `ZIP ダウンロードが中断されました: ${filename} (id=${item.id})`;
      console.warn(`[suno-helper] ${message}`);
      cleanupWatcher(currentWatcher);
      notifyDownloadFailed(currentWatcher, message);
      return;
    }
    notifyDownloadComplete(currentWatcher, filename, item.id);
  };

  const changedListener = (delta: chrome.downloads.DownloadDelta): void => {
    const state = delta.state?.current;
    if (state !== "complete" && state !== "interrupted") {
      return;
    }
    withWatcherState((watcher) => {
      if (watcher.targetDownloadId !== null && watcher.targetDownloadId !== delta.id) {
        return;
      }
      chrome.downloads.search({ id: delta.id }, (results) => {
        if (!results || results.length === 0) {
          return;
        }
        handleDownloadState(watcher, results[0], state);
      });
    });
  };

  chrome.downloads.onCreated.addListener(createdListener);
  chrome.downloads.onChanged.addListener(changedListener);
  void readStoredWatcherState().then((watcher) => {
    if (watcher !== null) {
      activeDownloadWatcher = watcher;
      scheduleWatcherTimers(watcher);
    }
  });

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
  onMessage("adoptSelectedClips", ({ data, sender }) =>
    sendMessage("adoptSelectedClips", data, requireRelayTab(sender, "adoptSelectedClips")),
  );
  onMessage("queryProgress", ({ sender }) =>
    sendMessage("queryProgress", undefined, requireRelayTab(sender, "queryProgress")),
  );
  // background → runner 中継。playlist URL 解決用に、指定タブの runner content が
  // 自身の document を scrape した結果を返す。
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
      return { ok: false, message: "startDownload: 送信元タブが特定できません" } as const;
    }
    const { format } = data;
    if (activeDownloadWatcher !== null) {
      return { ok: false, message: "別の Download all 監視が進行中です。完了後に再実行してください。" } as const;
    }
    console.info(`[suno-helper] Download all 監視を開始します (format=${format})`);

    // 監視開始時刻を記録し、これ以前に開始されたダウンロードを除外する (#1217)。
    const monitorStartedAt = Date.now();

    // Suno の ZIP ダウンロードは "Download all" click 直後に開始される。
    // chrome.downloads.onChanged で state=complete を待ち、ファイル名パターン (.zip) で照合する。
    setActiveDownloadWatcher({ tabId, monitorStartedAt, targetDownloadId: null });
    return { ok: true } as const;
  });

  onMessage("cancelDownload", ({ sender }) => {
    const tabId = relayTabId(sender);
    if (activeDownloadWatcher && (tabId === null || activeDownloadWatcher.tabId === tabId)) {
      cleanupWatcher(activeDownloadWatcher);
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

  onMessage("resolvePlaylistUrl", async ({ data }) => {
    const tab = await browser.tabs.create({ url: SUNO_ME_PLAYLISTS_URL, active: false });
    if (typeof tab.id !== "number") {
      throw new Error("playlist URL 解決用タブを作成できませんでした");
    }
    const tabId = tab.id;
    try {
      const items = await captureFromTab(tabId, {
        sendCapture: (targetTabId) => sendMessage("capturePlaylists", undefined, targetTabId),
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
        now: () => Date.now(),
        timeoutMs: PLAYLIST_URL_RESOLVE_TIMEOUT_MS,
        pollMs: PLAYLIST_URL_RESOLVE_POLL_MS,
      });
      const item = items.find((playlist) => playlist.title === data.playlistName);
      if (!item) {
        throw new Error(`playlist URL を解決できません: ${data.playlistName}`);
      }
      return { url: item.url };
    } finally {
      await browser.tabs.remove(tabId).catch((err: unknown) => {
        console.debug("[suno-helper] playlist URL 解決用タブの close に失敗:", err);
      });
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
