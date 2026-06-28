const TRUSTED_DOWNLOAD_HOST_SUFFIXES = [".suno.com", ".suno.ai"];
const DOWNLOAD_WATCHER_SESSION_KEY = "suno-helper:downloadWatcher";
const DOWNLOAD_COMPLETE_POLL_MS = 3000;
const DOWNLOAD_WATCH_TIMEOUT_MS = 600000;

type DownloadMessageSender = (
  type: "downloadComplete" | "downloadFailed",
  data: { filename: string } | { message: string },
  tabId: number,
) => Promise<unknown>;

interface DownloadWatcherState {
  tabId: number;
  monitorStartedAt: number;
  targetDownloadId: number | null;
}

export interface DownloadWatcherController {
  start: (tabId: number, format: string) => { ok: true } | { ok: false; message: string };
  cancelForTab: (tabId: number | null) => void;
}

export function installDownloadWatcher(deps: { sendMessage: DownloadMessageSender }): DownloadWatcherController {
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
    deps.sendMessage("downloadFailed", { message }, watcher.tabId).catch((err: unknown) => {
      console.warn("[suno-helper] downloadFailed 中継失敗:", err);
    });
  };

  const notifyDownloadComplete = (watcher: DownloadWatcherState, filename: string, id?: number): void => {
    if (activeDownloadWatcher !== watcher) {
      return;
    }
    console.info(`[suno-helper] ZIP ダウンロード完了: ${filename}${id === undefined ? "" : ` (id=${id})`}`);
    cleanupWatcher(watcher);
    deps.sendMessage("downloadComplete", { filename }, watcher.tabId).catch((err: unknown) => {
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

  return {
    start: (tabId, format) => {
      if (activeDownloadWatcher !== null) {
        return { ok: false, message: "別の Download all 監視が進行中です。完了後に再実行してください。" } as const;
      }
      console.info(`[suno-helper] Download all 監視を開始します (format=${format})`);
      setActiveDownloadWatcher({ tabId, monitorStartedAt: Date.now(), targetDownloadId: null });
      return { ok: true } as const;
    },
    cancelForTab: (tabId) => {
      if (activeDownloadWatcher && (tabId === null || activeDownloadWatcher.tabId === tabId)) {
        cleanupWatcher(activeDownloadWatcher);
      }
    },
  };
}
