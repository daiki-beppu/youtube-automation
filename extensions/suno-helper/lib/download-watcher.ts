import { STUDIO_EXPORT_WATCH_TIMEOUT_MS } from "../../shared/constants";

const TRUSTED_DOWNLOAD_HOSTS = [
  "suno.com",
  "suno-ai--studio-bounce-prod-web.modal.run",
];
const TRUSTED_DOWNLOAD_HOST_SUFFIXES = [".suno.com", ".suno.ai"];
const DOWNLOAD_WATCHER_SESSION_KEY = "suno-helper:downloadWatcher";
const DOWNLOAD_COMPLETE_POLL_MS = 3000;
const STUDIO_EXPORT_WATCH_TIMEOUT_MINUTES = Math.round(
  STUDIO_EXPORT_WATCH_TIMEOUT_MS / 60_000
);

type DownloadMessageSender = (
  type: "downloadComplete" | "downloadFailed",
  data: { filename: string } | { message: string },
  tabId: number
) => Promise<unknown>;

interface DownloadWatcherState {
  tabId: number;
  monitorStartedAt: number;
  targetDownloadId: number | null;
}

/** 監視開始前に「すでに保存済みの Studio export ZIP」を拾う探索窓 (#5143)。 */
export interface SavedExportWindow {
  sinceMs: number;
  untilMs?: number;
}

export interface DownloadWatcherController {
  start: (
    tabId: number,
    savedExport?: SavedExportWindow
  ) => Promise<
    { ok: true; savedFilename?: string } | { ok: false; message: string }
  >;
  cancelForTab: (tabId: number) => Promise<void>;
}

export function installDownloadWatcher(deps: {
  sendMessage: DownloadMessageSender;
}): DownloadWatcherController {
  let activeDownloadWatcher: DownloadWatcherState | null = null;
  const watchTimeout: { id?: ReturnType<typeof setTimeout> } = {};
  const completedPoll: { id?: ReturnType<typeof setInterval> } = {};

  const isTrustedSunoDownloadUrl = (value: string | undefined): boolean => {
    if (!value) {
      return false;
    }
    if (!URL.canParse(value)) {
      return false;
    }
    const url = new URL(value);
    if (url.protocol === "blob:") {
      return url.origin === "https://suno.com";
    }
    const { hostname } = url;
    return (
      TRUSTED_DOWNLOAD_HOSTS.includes(hostname) ||
      TRUSTED_DOWNLOAD_HOST_SUFFIXES.some((suffix) => hostname.endsWith(suffix))
    );
  };

  const isTrustedSunoDownload = (
    item: chrome.downloads.DownloadItem
  ): boolean =>
    isTrustedSunoDownloadUrl(item.url) ||
    isTrustedSunoDownloadUrl(item.finalUrl);

  const isZipStartedAfter = (
    item: chrome.downloads.DownloadItem,
    startedAfterMs: number
  ): boolean => {
    const filename = item.filename ?? "";
    if (!filename.toLowerCase().endsWith(".zip")) {
      return false;
    }
    if (!isTrustedSunoDownload(item)) {
      return false;
    }
    const downloadStartMs = new Date(item.startTime).getTime();
    return (
      Number.isFinite(downloadStartMs) &&
      downloadStartMs >= startedAfterMs - 5000
    );
  };

  /** 中断通知されてもファイルが完全に保存済みなら採用する (#5143)。
   *  Chrome は書き込み完了後に ERR_ABORTED 等で interrupted 化することがあり、
   *  その場合の item は exists=true・受信バイト数 >= fileSize になる。
   *  サーバー側が ZIP 内容を検証するため、ここでは「保存済みか」の判定だけ行う。 */
  const isFullySavedZip = (item: chrome.downloads.DownloadItem): boolean =>
    item.exists === true &&
    item.fileSize > 0 &&
    item.bytesReceived >= item.fileSize;

  /** 採用できる終端 ZIP: 完了、または「中断扱いだがファイルは保存済み」。 */
  const isFinishedStudioZip = (
    item: chrome.downloads.DownloadItem,
    startedAfterMs: number
  ): boolean =>
    isZipStartedAfter(item, startedAfterMs) &&
    (item.state === "complete" || isFullySavedZip(item));

  const describeInterruptedItem = (
    item: chrome.downloads.DownloadItem
  ): string => {
    const expected = item.fileSize > 0 ? item.fileSize : item.totalBytes;
    const received =
      expected > 0
        ? `${item.bytesReceived}/${expected}`
        : `${item.bytesReceived}/不明`;
    return `error=${item.error ?? "不明"}, 受信 ${received} bytes, 保存ファイル${item.exists ? "あり" : "なし"}`;
  };

  const normalizeWatcherState = (
    value: unknown
  ): DownloadWatcherState | null => {
    if (typeof value !== "object" || value === null) {
      return null;
    }
    const record = value as Record<string, unknown>;
    if (
      typeof record.tabId !== "number" ||
      typeof record.monitorStartedAt !== "number"
    ) {
      return null;
    }
    const targetDownloadId =
      typeof record.targetDownloadId === "number" ||
      record.targetDownloadId === null
        ? record.targetDownloadId
        : null;
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
        if (item && isFinishedStudioZip(item, watcher.monitorStartedAt)) {
          const currentWatcher =
            watcher.targetDownloadId === null
              ? replaceActiveDownloadWatcher(watcher, {
                  ...watcher,
                  targetDownloadId: item.id,
                })
              : watcher;
          notifyDownloadComplete(currentWatcher, item.filename ?? "", item.id);
        }
      });
    }, DOWNLOAD_COMPLETE_POLL_MS);

    const elapsedMs = Date.now() - watcher.monitorStartedAt;
    watchTimeout.id = setTimeout(
      () => {
        findTargetDownload(watcher, (item) => {
          if (item && isFinishedStudioZip(item, watcher.monitorStartedAt)) {
            const currentWatcher =
              watcher.targetDownloadId === null
                ? replaceActiveDownloadWatcher(watcher, {
                    ...watcher,
                    targetDownloadId: item.id,
                  })
                : watcher;
            notifyDownloadComplete(
              currentWatcher,
              item.filename ?? "",
              item.id
            );
            return;
          }
          const message = `Studio export 監視タイムアウト（${STUDIO_EXPORT_WATCH_TIMEOUT_MINUTES} 分）。listener を解除しました。Download から export を再実行できます。`;
          console.warn(`[suno-helper] ${message}`);
          cleanupWatcher(watcher);
          notifyDownloadFailed(watcher, message);
        });
      },
      Math.max(0, STUDIO_EXPORT_WATCH_TIMEOUT_MS - elapsedMs)
    );
  }

  const setActiveDownloadWatcher = (watcher: DownloadWatcherState): void => {
    activeDownloadWatcher = watcher;
    persistWatcherState(watcher);
    scheduleWatcherTimers(watcher);
  };

  const replaceActiveDownloadWatcher = (
    current: DownloadWatcherState,
    next: DownloadWatcherState
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

  const notifyDownloadFailed = (
    watcher: DownloadWatcherState,
    message: string
  ): void => {
    deps
      .sendMessage("downloadFailed", { message }, watcher.tabId)
      .catch((err: unknown) => {
        console.warn("[suno-helper] downloadFailed 中継失敗:", err);
      });
  };

  const notifyDownloadComplete = (
    watcher: DownloadWatcherState,
    filename: string,
    id?: number
  ): void => {
    if (activeDownloadWatcher !== watcher) {
      return;
    }
    console.info(
      `[suno-helper] ZIP ダウンロード完了: ${filename}${id === undefined ? "" : ` (id=${id})`}`
    );
    cleanupWatcher(watcher);
    deps
      .sendMessage("downloadComplete", { filename }, watcher.tabId)
      .catch((err: unknown) => {
        console.warn("[suno-helper] downloadComplete 中継失敗:", err);
      });
  };

  const findTargetDownload = (
    watcher: DownloadWatcherState,
    callback: (item: chrome.downloads.DownloadItem | null) => void
  ): void => {
    if (watcher.targetDownloadId === null) {
      // state を絞らず直近 50 件を取り、「中断だが保存済み」の ZIP も拾う (#5143)。
      chrome.downloads.search(
        { limit: 50, orderBy: ["-startTime"] },
        (results) => {
          callback(
            results.find((item) =>
              isFinishedStudioZip(item, watcher.monitorStartedAt)
            ) ?? null
          );
        }
      );
      return;
    }
    chrome.downloads.search({ id: watcher.targetDownloadId }, (results) => {
      callback(results[0] ?? null);
    });
  };

  /** 中断 run の再実行時に、監視開始前から保存済みの Studio export ZIP を探す (#5143)。 */
  const findSavedStudioExport = (
    windowBounds: SavedExportWindow
  ): Promise<chrome.downloads.DownloadItem | null> =>
    new Promise((resolve) => {
      chrome.downloads.search(
        { limit: 50, orderBy: ["-startTime"] },
        (results) => {
          resolve(
            results.find((item) => {
              if (!isFinishedStudioZip(item, windowBounds.sinceMs)) {
                return false;
              }
              if (windowBounds.untilMs === undefined) {
                return true;
              }
              const startMs = new Date(item.startTime).getTime();
              return (
                Number.isFinite(startMs) && startMs <= windowBounds.untilMs
              );
            }) ?? null
          );
        }
      );
    });

  const hydration = readStoredWatcherState().then((watcher) => {
    if (watcher !== null) {
      activeDownloadWatcher = watcher;
      scheduleWatcherTimers(watcher);
    }
  });

  const withWatcherState = (
    fn: (watcher: DownloadWatcherState) => void
  ): void => {
    void hydration.then(() => {
      if (activeDownloadWatcher !== null) {
        fn(activeDownloadWatcher);
      }
    });
  };

  const createdListener = (item: chrome.downloads.DownloadItem): void => {
    withWatcherState((watcher) => {
      if (
        watcher.targetDownloadId !== null ||
        !isZipStartedAfter(item, watcher.monitorStartedAt)
      ) {
        return;
      }
      replaceActiveDownloadWatcher(watcher, {
        ...watcher,
        targetDownloadId: item.id,
      });
    });
  };

  const handleDownloadState = (
    watcher: DownloadWatcherState,
    item: chrome.downloads.DownloadItem,
    state: "complete" | "interrupted"
  ): void => {
    const filename = item.filename ?? "";
    if (!isZipStartedAfter(item, watcher.monitorStartedAt)) {
      console.debug(
        "[suno-helper] Studio export 監視対象外の download event を無視:",
        {
          filename,
          url: item.url,
          startTime: item.startTime,
          state,
        }
      );
      return;
    }
    const currentWatcher =
      watcher.targetDownloadId === null
        ? replaceActiveDownloadWatcher(watcher, {
            ...watcher,
            targetDownloadId: item.id,
          })
        : watcher;
    if (state === "interrupted") {
      handleInterruptedDownload(currentWatcher, item);
      return;
    }
    notifyDownloadComplete(currentWatcher, filename, item.id);
  };

  /** interrupted を即失敗にしない。実ファイルの保存状況と他の終端 ZIP を
   * 別途確認してから失敗を宣言する (#5143)。 */
  const handleInterruptedDownload = (
    watcher: DownloadWatcherState,
    item: chrome.downloads.DownloadItem
  ): void => {
    const filename = item.filename ?? "";
    if (isFullySavedZip(item)) {
      console.info(
        `[suno-helper] 中断通知だがファイルは保存済み。完了として継続: ${filename} (id=${item.id})`
      );
      notifyDownloadComplete(watcher, filename, item.id);
      return;
    }
    chrome.downloads.search(
      { limit: 50, orderBy: ["-startTime"] },
      (results) => {
        if (activeDownloadWatcher !== watcher) {
          return;
        }
        const fallback = results.find(
          (candidate) =>
            candidate.id !== item.id &&
            isFinishedStudioZip(candidate, watcher.monitorStartedAt)
        );
        if (fallback) {
          console.info(
            `[suno-helper] 中断イベントの代わりに保存済み ZIP を採用: ${fallback.filename} (id=${fallback.id})`
          );
          notifyDownloadComplete(watcher, fallback.filename ?? "", fallback.id);
          return;
        }
        const message = `ZIP ダウンロードが中断されました: ${filename} (id=${item.id}, ${describeInterruptedItem(item)})。Download から export を再実行できます`;
        console.warn(`[suno-helper] ${message}`);
        cleanupWatcher(watcher);
        notifyDownloadFailed(watcher, message);
      }
    );
  };

  const changedListener = (delta: chrome.downloads.DownloadDelta): void => {
    const state = delta.state?.current;
    if (state !== "complete" && state !== "interrupted") {
      return;
    }
    withWatcherState((watcher) => {
      if (
        watcher.targetDownloadId !== null &&
        watcher.targetDownloadId !== delta.id
      ) {
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

  return {
    start: async (tabId, savedExport) => {
      await hydration;
      if (activeDownloadWatcher !== null) {
        if (
          activeDownloadWatcher.tabId === tabId &&
          activeDownloadWatcher.targetDownloadId === null
        ) {
          console.warn(
            "[suno-helper] 未確定の Studio export 監視を同一タブの再実行で解除します。"
          );
          cleanupWatcher(activeDownloadWatcher);
        } else {
          return {
            ok: false,
            message:
              "別の Studio export 監視が進行中です。完了後に再実行してください。",
          } as const;
        }
      }
      if (activeDownloadWatcher !== null) {
        return {
          ok: false,
          message:
            "別の Studio export 監視が進行中です。完了後に再実行してください。",
        } as const;
      }
      if (savedExport !== undefined) {
        const saved = await findSavedStudioExport(savedExport);
        if (saved !== null) {
          const filename = saved.filename ?? "";
          console.info(
            `[suno-helper] 保存済み Studio export ZIP を検出。再 export せず取り込みを再開: ${filename} (id=${saved.id})`
          );
          return { ok: true, savedFilename: filename } as const;
        }
      }
      console.info("[suno-helper] Studio export 監視を開始します");
      setActiveDownloadWatcher({
        tabId,
        monitorStartedAt: Date.now(),
        targetDownloadId: null,
      });
      return { ok: true } as const;
    },
    cancelForTab: async (tabId) => {
      await hydration;
      if (activeDownloadWatcher && activeDownloadWatcher.tabId === tabId) {
        cleanupWatcher(activeDownloadWatcher);
      }
    },
  };
}
