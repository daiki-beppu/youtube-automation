// background.ts の startDownload / sendTrustedCmdP ハンドラの回帰テスト (#1217)。
// Vitest env は node。chrome.downloads / chrome.debugger を stub して検証する。
// content-retry-handlers.test.ts の vi.doMock パターンを雛形とし、
// background 版の defineBackground + chrome API stub を構築する。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (msg: { data: Record<string, unknown>; sender: Record<string, unknown> }) => unknown;

interface SentMessage {
  type: string;
  data: unknown;
  tabId?: number;
}

interface DownloadDelta {
  id: number;
  state?: { current: string };
}

interface DownloadItem {
  id: number;
  filename: string;
  startTime: string;
  url: string;
  finalUrl?: string;
  referrer?: string;
  state?: string;
}

interface StoredDownloadWatcher {
  tabId: number;
  monitorStartedAt: number;
  targetDownloadId: number | null;
}

async function loadBackground(opts?: {
  searchResults?: Array<{ filename: string; startTime?: string; url?: string; finalUrl?: string; referrer?: string }>;
  searchResultsById?: Record<
    number,
    Array<{ filename: string; startTime?: string; url?: string; finalUrl?: string; referrer?: string; state?: string }>
  >;
  recentSearchResults?: Array<{
    id?: number;
    filename: string;
    startTime?: string;
    url?: string;
    finalUrl?: string;
    referrer?: string;
    state?: string;
  }>;
  debuggerAttachError?: Error;
  debuggerSendCommandError?: Error;
  postDownloadedError?: Error;
  sessionState?: StoredDownloadWatcher;
  sessionGetDelayMs?: number;
  tabCreateResult?: { id?: number };
  capturePlaylistsResult?: Array<{ title: string; url: string }>;
  capturePlaylistsError?: Error;
  useRealPostDownloaded?: boolean;
  fetchImpl?: ReturnType<typeof vi.fn>;
}) {
  vi.resetModules();

  const handlers = new Map<string, Handler>();
  const sentMessages: SentMessage[] = [];

  // --- globals ---
  // defineBackground は WXT の auto-import。stub して即座にコールバックを実行する。
  vi.stubGlobal("defineBackground", (fn: () => void) => {
    fn();
    return fn;
  });

  const browserTabs = {
    create: vi.fn(() => Promise.resolve(opts?.tabCreateResult ?? { id: 99 })),
    remove: vi.fn(() => Promise.resolve()),
  };

  vi.stubGlobal("browser", {
    runtime: {
      onInstalled: { addListener: vi.fn() },
      getManifest: () => ({ version: "0.1.0" }),
    },
    action: { onClicked: { addListener: vi.fn() } },
    tabs: browserTabs,
  });

  // chrome.downloads stub
  const createdListeners: Array<(item: DownloadItem) => void> = [];
  const removedCreatedListeners: Array<(item: DownloadItem) => void> = [];
  const downloadListeners: Array<(delta: DownloadDelta) => void> = [];
  const removedDownloadListeners: Array<(delta: DownloadDelta) => void> = [];
  const sessionStore: Record<string, unknown> = opts?.sessionState
    ? { "suno-helper:downloadWatcher": opts.sessionState }
    : {};

  const chromeDownloads = {
    onCreated: {
      addListener: vi.fn((fn: (item: DownloadItem) => void) => {
        createdListeners.push(fn);
      }),
      removeListener: vi.fn((fn: (item: DownloadItem) => void) => {
        removedCreatedListeners.push(fn);
      }),
    },
    onChanged: {
      addListener: vi.fn((fn: (delta: DownloadDelta) => void) => {
        downloadListeners.push(fn);
      }),
      removeListener: vi.fn((fn: (delta: DownloadDelta) => void) => {
        removedDownloadListeners.push(fn);
      }),
    },
    search: vi.fn(
      (
        query: { id?: number },
        cb: (results: Array<{ id: number; filename: string; startTime: string; url: string; state?: string }>) => void,
      ) => {
        if (typeof query.id !== "number") {
          const results = (opts?.recentSearchResults ?? []).map((r, index) => ({
            id: r.id ?? index + 100,
            startTime: new Date().toISOString(),
            url: "https://download.example.com/file.zip",
            ...r,
          }));
          cb(results);
          return;
        }
        const defaults = [
          {
            id: query.id,
            filename: `suno-playlist-${query.id}.zip`,
            startTime: new Date().toISOString(),
            url: "https://suno.com/api/download/zip",
          },
        ];
        const configuredResults = opts?.searchResultsById?.[query.id] ?? opts?.searchResults;
        const results = configuredResults
          ? configuredResults.map((r) => ({
              id: query.id as number,
              startTime: new Date().toISOString(),
              url: "https://suno.com/api/download/zip",
              ...r,
            }))
          : defaults;
        cb(results);
      },
    ),
  };

  // chrome.debugger stub
  const chromeDebugger = {
    attach: opts?.debuggerAttachError
      ? vi.fn(() => Promise.reject(opts.debuggerAttachError))
      : vi.fn(() => Promise.resolve()),
    sendCommand: opts?.debuggerSendCommandError
      ? vi.fn(() => Promise.reject(opts.debuggerSendCommandError))
      : vi.fn(() => Promise.resolve()),
    detach: vi.fn(() => Promise.resolve()),
  };

  vi.stubGlobal("chrome", {
    downloads: chromeDownloads,
    debugger: chromeDebugger,
    storage: {
      session: {
        get: vi.fn((key: string, cb: (items: Record<string, unknown>) => void) => {
          if (typeof opts?.sessionGetDelayMs === "number") {
            setTimeout(() => cb({ [key]: sessionStore[key] }), opts.sessionGetDelayMs);
            return;
          }
          cb({ [key]: sessionStore[key] });
        }),
        set: vi.fn((items: Record<string, unknown>) => {
          Object.assign(sessionStore, items);
        }),
        remove: vi.fn((key: string) => {
          delete sessionStore[key];
        }),
      },
    },
  });

  // --- module mocks ---
  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((type: string, handler: Handler) => {
      handlers.set(type, handler);
      return vi.fn();
    }),
    sendMessage: vi.fn((type: string, data?: unknown, tabId?: number) => {
      sentMessages.push({ type, data, tabId });
      return Promise.resolve();
    }),
  }));

  const postDownloadedMock = opts?.postDownloadedError
    ? vi.fn(() => Promise.reject(opts.postDownloadedError))
    : vi.fn(() => Promise.resolve());
  if (opts?.useRealPostDownloaded) {
    vi.doUnmock("../../shared/api");
    vi.stubGlobal("fetch", opts.fetchImpl ?? vi.fn());
  } else {
    vi.doMock("../../shared/api", () => ({
      postDownloaded: postDownloadedMock,
    }));
  }

  const captureFromTabMock = opts?.capturePlaylistsError
    ? vi.fn(() => Promise.reject(opts.capturePlaylistsError))
    : vi.fn((_tabId: number, deps: { sendCapture: (tabId: number) => Promise<unknown> }) => {
        void deps.sendCapture(99);
        return Promise.resolve(
          opts?.capturePlaylistsResult ?? [{ title: "vj | regression", url: "https://suno.com/playlist/regression" }],
        );
      });
  vi.doMock("../lib/auto-capture", () => ({
    captureFromTab: captureFromTabMock,
  }));

  vi.doMock("../components/runner-errors", () => ({
    describeRelayFailure: vi.fn(() => ({ level: "debug" as const, text: "test" })),
  }));

  vi.doMock("../lib/overlay-relay", () => ({
    relayTabId: vi.fn((sender: { tab?: { id?: number } }) =>
      typeof sender?.tab?.id === "number" ? sender.tab.id : null,
    ),
    requireRelayTab: vi.fn((sender: { tab?: { id?: number } }, action: string) => {
      const id = typeof sender?.tab?.id === "number" ? sender.tab.id : null;
      if (id === null) throw new Error(`${action} test error`);
      return id;
    }),
  }));

  // import triggers defineBackground callback → handlers get registered
  await import("../entrypoints/background");

  return {
    handlers,
    sentMessages,
    createdListeners,
    removedCreatedListeners,
    downloadListeners,
    removedDownloadListeners,
    chromeDownloads,
    chromeDebugger,
    postDownloadedMock,
    browserTabs,
    captureFromTabMock,
    sessionStore,
  };
}

function freshZip(id: number, overrides: Partial<DownloadItem> = {}): DownloadItem {
  return {
    id,
    filename: `suno-playlist-${id}.zip`,
    startTime: new Date().toISOString(),
    url: "https://suno.com/api/download/zip",
    ...overrides,
  };
}

async function flushPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

// startDownload ----------------------------------------------------------------

describe('background onMessage("startDownload"): .zip 完了で downloadComplete を中継する', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given .zip ダウンロード完了 When listener 発火 Then downloadComplete を送信元タブへ中継する", async () => {
    const { handlers, sentMessages, createdListeners, downloadListeners, removedDownloadListeners } =
      await loadBackground();

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    expect(downloadListeners).toHaveLength(1);
    expect(createdListeners).toHaveLength(1);
    const listener = downloadListeners[0];

    // .zip ダウンロード完了を simulate
    createdListeners[0](freshZip(1));
    listener({ id: 1, state: { current: "complete" } });
    await flushPromises();

    // sendMessage("downloadComplete") が tabId=42 で呼ばれたことを確認
    // chrome.downloads.search の callback は同期実行されるため、
    // sendMessage は listener 呼び出し内で同期的に push される。
    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { filename: expect.stringContaining(".zip") },
      tabId: 42,
    });

    // top-level listener は維持し、監視状態だけを解放する。
    expect(removedDownloadListeners).toHaveLength(0);
  });
});

describe('background onMessage("postDownloaded"): shared/api 実配線', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("token 取得、downloaded POST、403 retry を実 fetch で実行する", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ token: "stale-token" }) })
      .mockResolvedValueOnce({ ok: false, status: 403, statusText: "Forbidden" })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ token: "fresh-token" }) })
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: "OK" });
    const { handlers } = await loadBackground({ useRealPostDownloaded: true, fetchImpl });

    await handlers.get("postDownloaded")!({
      data: {
        baseUrl: "http://localhost:7873/",
        collectionId: "20260601 clm",
        body: {
          file_count: 0,
          format: "mp3",
          suno_playlist_url: "https://suno.com/playlist/test",
        },
      },
      sender: { tab: { id: 42 } },
    });

    expect(fetchImpl).toHaveBeenNthCalledWith(1, "http://localhost:7873/auth/token");
    expect(fetchImpl).toHaveBeenNthCalledWith(
      2,
      "http://localhost:7873/collections/20260601%20clm/downloaded",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Serve-Token": "stale-token" },
        body: JSON.stringify({
          file_count: 0,
          format: "mp3",
          suno_playlist_url: "https://suno.com/playlist/test",
        }),
      }),
    );
    expect(fetchImpl).toHaveBeenNthCalledWith(3, "http://localhost:7873/auth/token");
    expect(fetchImpl).toHaveBeenNthCalledWith(
      4,
      "http://localhost:7873/collections/20260601%20clm/downloaded",
      expect.objectContaining({
        headers: { "Content-Type": "application/json", "X-Serve-Token": "fresh-token" },
      }),
    );
  });
});

describe('background onMessage("startDownload"): 非 .zip ダウンロードは無視する', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given .mp3 ダウンロード完了 When listener 発火 Then downloadComplete を送信しない", async () => {
    const { handlers, sentMessages, downloadListeners, removedDownloadListeners } = await loadBackground({
      searchResults: [{ filename: "track.mp3", startTime: new Date().toISOString() }],
    });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    listener({ id: 1, state: { current: "complete" } });
    await flushPromises();

    // 非 .zip なので downloadComplete は送信されない
    expect(sentMessages.filter((m) => m.type === "downloadComplete")).toHaveLength(0);
    // listener も解除されない（次の .zip を待ち続ける）
    expect(removedDownloadListeners).toHaveLength(0);
  });
});

describe('background onMessage("startDownload"): タイムアウトで listener を解除する', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("Given 10 分経過 When タイムアウト Then listener を解除する", async () => {
    const { handlers, sentMessages, downloadListeners, removedDownloadListeners } = await loadBackground();

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    expect(downloadListeners).toHaveLength(1);
    expect(removedDownloadListeners).toHaveLength(0);

    // 10 分 (600000ms) を advance
    vi.advanceTimersByTime(600000);
    await flushPromises();

    expect(removedDownloadListeners).toHaveLength(0);
    expect(sentMessages).toContainEqual({
      type: "downloadFailed",
      data: { message: expect.stringContaining("タイムアウト") },
      tabId: 42,
    });
    expect(
      await handlers.get("startDownload")!({
        data: { format: "mp3" },
        sender: { tab: { id: 42 } },
      }),
    ).toEqual({ ok: true });
  });
});

describe('background onMessage("startDownload"): 成功時にタイムアウトが発火しない (#1217)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("Given .zip 完了後 When 10 分経過 Then タイムアウト warn は出ない", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { handlers, createdListeners, downloadListeners, removedDownloadListeners } = await loadBackground();

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    // .zip ダウンロード完了で listener が解除される
    createdListeners[0](freshZip(1));
    listener({ id: 1, state: { current: "complete" } });
    await flushPromises();
    expect(removedDownloadListeners).toHaveLength(0);

    // 10 分を advance — timeout は clearTimeout 済みなので発火しない
    vi.advanceTimersByTime(600000);

    // タイムアウト warn が出ていないことを確認
    const timeoutWarns = warnSpy.mock.calls.filter(
      (args) => typeof args[0] === "string" && args[0].includes("タイムアウト"),
    );
    expect(timeoutWarns).toHaveLength(0);

    warnSpy.mockRestore();
  });
});

describe('background onMessage("startDownload"): 非 Suno ZIP は無視する (#1217)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given example.com の .zip ダウンロード完了 When listener 発火 Then downloadComplete を送信しない", async () => {
    const { handlers, sentMessages, downloadListeners, removedDownloadListeners } = await loadBackground({
      searchResults: [
        { filename: "file.zip", startTime: new Date().toISOString(), url: "https://example.com/file.zip" },
      ],
    });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    listener({ id: 1, state: { current: "complete" } });
    await flushPromises();

    expect(sentMessages.filter((m) => m.type === "downloadComplete")).toHaveLength(0);
    expect(removedDownloadListeners).not.toContain(listener);
  });
});

describe('background onMessage("startDownload"): interrupted 状態でクリーンアップする (#1217)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("Given ダウンロード中断 When listener 発火 Then listener を解除しタイムアウトをキャンセルする", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { handlers, sentMessages, createdListeners, downloadListeners, removedDownloadListeners } =
      await loadBackground();

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    expect(downloadListeners).toHaveLength(1);
    const listener = downloadListeners[0];

    // interrupted 状態を simulate
    createdListeners[0](freshZip(1));
    listener({ id: 1, state: { current: "interrupted" } });
    await flushPromises();

    // top-level listener は維持し、監視状態だけを解放する。
    expect(removedDownloadListeners).toHaveLength(0);

    // downloadComplete は送信されず、downloadFailed が即時に中継される
    expect(sentMessages.filter((m) => m.type === "downloadComplete")).toHaveLength(0);
    expect(sentMessages).toContainEqual({
      type: "downloadFailed",
      data: { message: expect.stringContaining("中断") },
      tabId: 42,
    });

    // タイムアウトが clearTimeout されたか: 10 分経過しても warn が出ない
    vi.advanceTimersByTime(600000);
    const timeoutWarns = warnSpy.mock.calls.filter(
      (args) => typeof args[0] === "string" && args[0].includes("タイムアウト"),
    );
    expect(timeoutWarns).toHaveLength(0);

    warnSpy.mockRestore();
  });
});

describe('background onMessage("startDownload"): 無関係な interrupted は無視する (#1217)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("Given fresh ZIP の interrupted When listener 発火 Then 失敗通知する", async () => {
    const { handlers, sentMessages, createdListeners, downloadListeners, removedDownloadListeners } =
      await loadBackground({
        searchResults: [
          { filename: "file.zip", startTime: new Date().toISOString(), url: "https://suno.com/api/download/zip" },
        ],
      });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    createdListeners[0](freshZip(1, { filename: "file.zip" }));
    listener({ id: 1, state: { current: "interrupted" } });
    await flushPromises();

    expect(sentMessages).toContainEqual({
      type: "downloadFailed",
      data: { message: expect.stringContaining("中断") },
      tabId: 42,
    });
    expect(removedDownloadListeners).not.toContain(listener);
  });

  it("Given 非 zip の interrupted When listener 発火 Then listener を維持し失敗通知しない", async () => {
    const { handlers, sentMessages, downloadListeners, removedDownloadListeners } = await loadBackground({
      searchResults: [{ filename: "track.mp3", startTime: new Date().toISOString(), url: "https://suno.com/api/file" }],
    });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    listener({ id: 1, state: { current: "interrupted" } });
    await flushPromises();

    expect(sentMessages.filter((m) => m.type === "downloadFailed")).toHaveLength(0);
    expect(removedDownloadListeners).toHaveLength(0);
  });

  it("Given 監視開始前の interrupted When listener 発火 Then listener を維持し失敗通知しない", async () => {
    const oldStart = new Date(Date.now() - 60_000).toISOString();
    const { handlers, sentMessages, downloadListeners, removedDownloadListeners } = await loadBackground({
      searchResults: [{ filename: "old.zip", startTime: oldStart, url: "https://suno.com/api/download/zip" }],
    });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    listener({ id: 1, state: { current: "interrupted" } });
    await flushPromises();

    expect(sentMessages.filter((m) => m.type === "downloadFailed")).toHaveLength(0);
    expect(removedDownloadListeners).toHaveLength(0);
  });
});

describe('background onMessage("startDownload"): 監視開始前の .zip は無視する (#1217)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given 古い startTime の Suno .zip When listener 発火 Then listener を維持し失敗通知しない", async () => {
    const oldStart = new Date(Date.now() - 60_000).toISOString();
    const { handlers, sentMessages, downloadListeners, removedDownloadListeners } = await loadBackground({
      searchResults: [{ filename: "old.zip", startTime: oldStart, url: "https://suno.com/api/download/zip" }],
    });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    listener({ id: 7, state: { current: "complete" } });
    await flushPromises();

    expect(removedDownloadListeners).toHaveLength(0);
    expect(sentMessages.filter((m) => m.type === "downloadFailed")).toHaveLength(0);
    expect(sentMessages.filter((m) => m.type === "downloadComplete")).toHaveLength(0);
  });

  it("Given 古い ZIP 後に新しい ZIP が完了 When listener 発火 Then 新しい ZIP だけ完了通知する", async () => {
    const oldStart = new Date(Date.now() - 60_000).toISOString();
    const freshStart = new Date().toISOString();
    const { handlers, sentMessages, createdListeners, downloadListeners, removedDownloadListeners } =
      await loadBackground({
        searchResultsById: {
          7: [{ filename: "old.zip", startTime: oldStart, url: "https://suno.com/api/download/zip" }],
          8: [{ filename: "new.zip", startTime: freshStart, url: "https://suno.com/api/download/zip" }],
        },
      });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    createdListeners[0](freshZip(7, { filename: "old.zip", startTime: oldStart }));
    listener({ id: 7, state: { current: "complete" } });
    await flushPromises();
    expect(removedDownloadListeners).toHaveLength(0);

    createdListeners[0](freshZip(8, { filename: "new.zip", startTime: freshStart }));
    listener({ id: 8, state: { current: "complete" } });
    await flushPromises();

    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { filename: "new.zip" },
      tabId: 42,
    });
    expect(removedDownloadListeners).not.toContain(listener);
  });

  it("Given 対象外の fresh Suno ZIP When 別 id の listener 発火 Then 完了扱いしない", async () => {
    const { handlers, sentMessages, createdListeners, downloadListeners, removedDownloadListeners } =
      await loadBackground({
        searchResultsById: {
          1: [
            { filename: "target.zip", startTime: new Date().toISOString(), url: "https://suno.com/api/download/zip" },
          ],
          2: [{ filename: "other.zip", startTime: new Date().toISOString(), url: "https://suno.com/api/download/zip" }],
        },
      });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    createdListeners[0](freshZip(1, { filename: "target.zip" }));
    listener({ id: 2, state: { current: "complete" } });
    await flushPromises();

    expect(sentMessages.filter((m) => m.type === "downloadComplete")).toHaveLength(0);
    expect(removedDownloadListeners).not.toContain(listener);
  });

  it("Given onCreated を取り逃した fresh Suno ZIP When complete event だけ届く Then 対象確定して完了通知する", async () => {
    const freshStart = new Date().toISOString();
    const { handlers, sentMessages, downloadListeners, sessionStore } = await loadBackground({
      searchResultsById: {
        33: [{ filename: "missed-created.zip", startTime: freshStart, url: "https://suno.com/api/download/zip" }],
      },
    });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    downloadListeners[0]({ id: 33, state: { current: "complete" } });
    await flushPromises();

    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { filename: "missed-created.zip" },
      tabId: 42,
    });
    expect(sessionStore["suno-helper:downloadWatcher"]).toBeUndefined();
  });
});

describe('background onMessage("startDownload"): timeout fallback で完了済み ZIP を拾う', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("Given onChanged を取り逃した fresh ZIP When timeout Then downloadComplete を中継する", async () => {
    const freshStart = new Date().toISOString();
    const { handlers, sentMessages, createdListeners, downloadListeners, removedDownloadListeners } =
      await loadBackground({
        searchResultsById: {
          88: [
            {
              filename: "/Users/test/Downloads/soulful-grooves.zip",
              startTime: freshStart,
              url: "https://cdn1.suno.ai/soulful-grooves.zip",
              state: "complete",
            },
          ],
        },
      });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    createdListeners[0](
      freshZip(88, {
        filename: "/Users/test/Downloads/soulful-grooves.zip",
        startTime: freshStart,
        url: "https://cdn1.suno.ai/soulful-grooves.zip",
      }),
    );
    await flushPromises();
    vi.advanceTimersByTime(600000);
    await flushPromises();

    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { filename: "/Users/test/Downloads/soulful-grooves.zip" },
      tabId: 42,
    });
    expect(removedDownloadListeners).not.toContain(downloadListeners[0]);
  });
});

describe('background onMessage("startDownload"): polling fallback で完了済み ZIP を即時に拾う', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("Given onChanged を取り逃した fresh ZIP When poll interval 経過 Then timeout を待たず downloadComplete を中継する", async () => {
    const freshStart = new Date().toISOString();
    const { handlers, sentMessages, createdListeners, downloadListeners, removedDownloadListeners } =
      await loadBackground({
        searchResultsById: {
          89: [
            {
              filename: "/Users/test/Downloads/soulful-grooves.zip",
              startTime: freshStart,
              url: "https://cdn1.suno.ai/soulful-grooves.zip",
              state: "complete",
            },
          ],
        },
      });

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    createdListeners[0](
      freshZip(89, {
        filename: "/Users/test/Downloads/soulful-grooves.zip",
        startTime: freshStart,
        url: "https://cdn1.suno.ai/soulful-grooves.zip",
      }),
    );
    await flushPromises();
    vi.advanceTimersByTime(3000);
    await flushPromises();

    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { filename: "/Users/test/Downloads/soulful-grooves.zip" },
      tabId: 42,
    });
    expect(removedDownloadListeners).not.toContain(downloadListeners[0]);
  });
});

describe("background downloads listener: service worker restart 後も session watcher を復元する (#1217)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("Given 保存済み watcher When background が再初期化され complete event を受ける Then downloadComplete を中継する", async () => {
    const freshStart = new Date().toISOString();
    const { sentMessages, downloadListeners, sessionStore } = await loadBackground({
      sessionState: {
        tabId: 42,
        monitorStartedAt: Date.now(),
        targetDownloadId: 77,
      },
      searchResultsById: {
        77: [
          {
            filename: "/Users/test/Downloads/restored.zip",
            startTime: freshStart,
            url: "https://cdn1.suno.ai/restored.zip",
          },
        ],
      },
    });
    await flushPromises();

    downloadListeners[0]({ id: 77, state: { current: "complete" } });
    await flushPromises();

    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { filename: "/Users/test/Downloads/restored.zip" },
      tabId: 42,
    });
    expect(sessionStore["suno-helper:downloadWatcher"]).toBeUndefined();
  });

  it("Given target 未確定の保存済み watcher When complete event を受ける Then 対象確定して downloadComplete を中継する", async () => {
    const freshStart = new Date().toISOString();
    const { sentMessages, downloadListeners, sessionStore } = await loadBackground({
      sessionState: {
        tabId: 42,
        monitorStartedAt: Date.now(),
        targetDownloadId: null,
      },
      searchResultsById: {
        78: [
          {
            filename: "/Users/test/Downloads/restored-null.zip",
            startTime: freshStart,
            url: "https://cdn1.suno.ai/restored-null.zip",
          },
        ],
      },
    });
    await flushPromises();

    downloadListeners[0]({ id: 78, state: { current: "complete" } });
    await flushPromises();

    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { filename: "/Users/test/Downloads/restored-null.zip" },
      tabId: 42,
    });
    expect(sessionStore["suno-helper:downloadWatcher"]).toBeUndefined();
  });

  it("Given session 復元が遅延 When startDownload が先に来る Then 復元完了を待って stale watcher を上書きしない", async () => {
    const freshStart = new Date().toISOString();
    const { handlers, sentMessages, downloadListeners } = await loadBackground({
      sessionGetDelayMs: 100,
      sessionState: {
        tabId: 41,
        monitorStartedAt: Date.now(),
        targetDownloadId: 77,
      },
      searchResultsById: {
        77: [
          {
            filename: "/Users/test/Downloads/restored-race.zip",
            startTime: freshStart,
            url: "https://cdn1.suno.ai/restored-race.zip",
          },
        ],
      },
    });

    const resultPromise = handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    }) as Promise<unknown>;
    vi.advanceTimersByTime(100);
    await flushPromises();

    await expect(resultPromise).resolves.toEqual({
      ok: false,
      message: "別の Download all 監視が進行中です。完了後に再実行してください。",
    });

    downloadListeners[0]({ id: 77, state: { current: "complete" } });
    await flushPromises();
    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { filename: "/Users/test/Downloads/restored-race.zip" },
      tabId: 41,
    });
  });
});

describe('background onMessage("startDownload"): 同時監視を排他する (#1217)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given 監視中 When 別タブが startDownload Then 新しい監視を作らず失敗通知する", async () => {
    const { handlers, sentMessages, downloadListeners } = await loadBackground();

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });
    const result = await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 43 } },
    });

    expect(downloadListeners).toHaveLength(1);
    expect(result).toEqual({ ok: false, message: expect.stringContaining("監視が進行中") });
    expect(sentMessages.filter((m) => m.type === "downloadFailed")).toHaveLength(0);
  });
});

describe('background onMessage("cancelDownload"): active watcher を解除する (#1217)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("Given startDownload 済み When 同一タブから cancelDownload Then listener を解除し次の startDownload を許可する", async () => {
    const { handlers, sentMessages, downloadListeners, removedDownloadListeners } = await loadBackground();

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });
    const listener = downloadListeners[0];

    await handlers.get("cancelDownload")!({
      data: {},
      sender: { tab: { id: 42 } },
    });

    expect(removedDownloadListeners).not.toContain(listener);

    const result = await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    expect(result).toEqual({ ok: true });
    expect(downloadListeners).toHaveLength(1);
    expect(sentMessages.filter((m) => m.type === "downloadFailed")).toHaveLength(0);
  });

  it("Given startDownload 済み When 別タブから cancelDownload Then watcher を維持し次の startDownload を拒否する", async () => {
    const { handlers, downloadListeners, removedDownloadListeners } = await loadBackground();

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });
    const listener = downloadListeners[0];

    await handlers.get("cancelDownload")!({
      data: {},
      sender: { tab: { id: 43 } },
    });

    expect(removedDownloadListeners).not.toContain(listener);

    const result = await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 43 } },
    });

    expect(result).toEqual({
      ok: false,
      message: "別の Download all 監視が進行中です。完了後に再実行してください。",
    });
  });

  it("Given sender tab が無い When cancelDownload Then watcher を解除しない", async () => {
    const { handlers } = await loadBackground();

    await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 42 } },
    });

    await expect(
      handlers.get("cancelDownload")!({
        data: {},
        sender: {},
      }) as Promise<unknown>,
    ).rejects.toThrow("cancelDownload test error");

    const result = await handlers.get("startDownload")!({
      data: { format: "mp3" },
      sender: { tab: { id: 43 } },
    });
    expect(result).toEqual({
      ok: false,
      message: "別の Download all 監視が進行中です。完了後に再実行してください。",
    });
  });
});

describe('background onMessage("postDownloaded"): privileged POST boundary', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given postDownloaded message When handler runs Then shared api に委譲する", async () => {
    const { handlers, postDownloadedMock } = await loadBackground();
    const body = { file_count: 0, format: "mp3", suno_playlist_url: "https://suno.com/playlist/test" };

    await handlers.get("postDownloaded")!({
      data: { baseUrl: "http://localhost:8787", collectionId: "coll-1", body },
      sender: { tab: { id: 42 } },
    });

    expect(postDownloadedMock).toHaveBeenCalledWith("http://localhost:8787", "coll-1", body);
  });

  it("Given shared api rejects When handler runs Then rejection を呼び出し側へ伝播する", async () => {
    const { handlers } = await loadBackground({
      postDownloadedError: new Error("POST downloaded failed: 403 Forbidden"),
    });

    await expect(
      handlers.get("postDownloaded")!({
        data: {
          baseUrl: "http://localhost:8787",
          collectionId: "coll-1",
          body: { file_count: 0, format: "mp3", suno_playlist_url: "https://suno.com/playlist/test" },
        },
        sender: { tab: { id: 42 } },
      }),
    ).rejects.toThrow("403");
  });

  it("Given sender tab が無い When handler runs Then shared api に委譲しない", async () => {
    const { handlers, postDownloadedMock } = await loadBackground();

    await expect(
      handlers.get("postDownloaded")!({
        data: {
          baseUrl: "http://localhost:8787",
          collectionId: "coll-1",
          body: { file_count: 0, format: "mp3", suno_playlist_url: "https://suno.com/playlist/test" },
        },
        sender: {},
      }) as Promise<unknown>,
    ).rejects.toThrow("postDownloaded test error");

    expect(postDownloadedMock).not.toHaveBeenCalled();
  });
});

describe('background onMessage("resolvePlaylistUrl"): playlist URL 解決タブ境界', () => {
  it("Given matching playlist When handler runs Then hidden tab で capture して URL を返し tab を閉じる", async () => {
    const { handlers, browserTabs, captureFromTabMock, sentMessages } = await loadBackground({
      capturePlaylistsResult: [
        { title: "vj | other", url: "https://suno.com/playlist/other" },
        { title: "vj | regression", url: "https://suno.com/playlist/regression" },
      ],
    });

    await expect(
      handlers.get("resolvePlaylistUrl")!({
        data: { playlistName: "vj | regression" },
        sender: { tab: { id: 42 } },
      }),
    ).resolves.toEqual({ url: "https://suno.com/playlist/regression" });

    expect(browserTabs.create).toHaveBeenCalledWith({ url: "https://suno.com/me/playlists", active: false });
    expect(captureFromTabMock).toHaveBeenCalledWith(99, expect.objectContaining({ sendCapture: expect.any(Function) }));
    expect(sentMessages).toContainEqual({ type: "capturePlaylists", data: undefined, tabId: 99 });
    expect(browserTabs.remove).toHaveBeenCalledWith(99);
  });

  it("Given playlist が見つからない When handler runs Then reject して tab を閉じる", async () => {
    const { handlers, browserTabs } = await loadBackground({
      capturePlaylistsResult: [{ title: "vj | other", url: "https://suno.com/playlist/other" }],
    });

    await expect(
      handlers.get("resolvePlaylistUrl")!({
        data: { playlistName: "vj | missing" },
        sender: { tab: { id: 42 } },
      }),
    ).rejects.toThrow(/playlist URL を解決できません/);

    expect(browserTabs.remove).toHaveBeenCalledWith(99);
  });

  it("Given capture が失敗 When handler runs Then reject して tab を閉じる", async () => {
    const { handlers, browserTabs } = await loadBackground({
      capturePlaylistsError: new Error("capture failed"),
    });

    await expect(
      handlers.get("resolvePlaylistUrl")!({
        data: { playlistName: "vj | regression" },
        sender: { tab: { id: 42 } },
      }),
    ).rejects.toThrow(/capture failed/);

    expect(browserTabs.remove).toHaveBeenCalledWith(99);
  });

  it("Given tab id が返らない When handler runs Then capture せず reject する", async () => {
    const { handlers, browserTabs, captureFromTabMock } = await loadBackground({
      tabCreateResult: {},
    });

    await expect(
      handlers.get("resolvePlaylistUrl")!({
        data: { playlistName: "vj | regression" },
        sender: { tab: { id: 42 } },
      }),
    ).rejects.toThrow(/タブを作成できません/);

    expect(captureFromTabMock).not.toHaveBeenCalled();
    expect(browserTabs.remove).not.toHaveBeenCalled();
  });

  it("Given sender tab が無い When handler runs Then hidden tab を作成しない", async () => {
    const { handlers, browserTabs, captureFromTabMock } = await loadBackground();

    await expect(
      handlers.get("resolvePlaylistUrl")!({
        data: { playlistName: "vj | regression" },
        sender: {},
      }) as Promise<unknown>,
    ).rejects.toThrow("resolvePlaylistUrl test error");

    expect(browserTabs.create).not.toHaveBeenCalled();
    expect(captureFromTabMock).not.toHaveBeenCalled();
  });
});

// sendTrustedCmdP --------------------------------------------------------------

describe('background onMessage("sendTrustedCmdP"): Mac は modifiers=4 (Meta) を使う', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given isMac=true When sendTrustedCmdP Then modifiers=4 で sendCommand する", async () => {
    const { handlers, chromeDebugger } = await loadBackground();

    await handlers.get("sendTrustedCmdP")!({
      data: { isMac: true },
      sender: { tab: { id: 42 } },
    });

    expect(chromeDebugger.attach).toHaveBeenCalledWith({ tabId: 42 }, "1.3");
    expect(chromeDebugger.sendCommand).toHaveBeenCalledWith(
      { tabId: 42 },
      "Input.dispatchKeyEvent",
      expect.objectContaining({ type: "rawKeyDown", modifiers: 4, key: "p" }),
    );
    expect(chromeDebugger.sendCommand).toHaveBeenCalledWith(
      { tabId: 42 },
      "Input.dispatchKeyEvent",
      expect.objectContaining({ type: "keyUp", modifiers: 4, key: "p" }),
    );
    expect(chromeDebugger.detach).toHaveBeenCalledWith({ tabId: 42 });
  });
});

describe('background onMessage("sendTrustedCmdP"): 非 Mac は modifiers=2 (Ctrl) を使う', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given isMac=false When sendTrustedCmdP Then modifiers=2 で sendCommand する", async () => {
    const { handlers, chromeDebugger } = await loadBackground();

    await handlers.get("sendTrustedCmdP")!({
      data: { isMac: false },
      sender: { tab: { id: 42 } },
    });

    expect(chromeDebugger.sendCommand).toHaveBeenCalledWith(
      { tabId: 42 },
      "Input.dispatchKeyEvent",
      expect.objectContaining({ modifiers: 2 }),
    );
    expect(chromeDebugger.detach).toHaveBeenCalledWith({ tabId: 42 });
  });
});

describe('background onMessage("sendTrustedCmdP"): sendCommand 失敗でも detach する', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("Given sendCommand が throw When sendTrustedCmdP Then finally で detach される", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { handlers, chromeDebugger } = await loadBackground({
      debuggerSendCommandError: new Error("sendCommand failed"),
    });

    await expect(
      handlers.get("sendTrustedCmdP")!({
        data: { isMac: true },
        sender: { tab: { id: 42 } },
      }),
    ).rejects.toThrow("sendCommand failed");

    // attach は成功
    expect(chromeDebugger.attach).toHaveBeenCalledWith({ tabId: 42 }, "1.3");
    // sendCommand は 1 回目で失敗（2 回目は到達しない）
    expect(chromeDebugger.sendCommand).toHaveBeenCalledTimes(1);
    // finally で detach は呼ばれる
    expect(chromeDebugger.detach).toHaveBeenCalledWith({ tabId: 42 });
    // outer catch で warn
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("sendTrustedCmdP failed"), expect.any(Error));
  });
});

describe('background onMessage("sendTrustedCmdP"): attach 失敗は reject する', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("Given attach が throw When sendTrustedCmdP Then reject する（sendCommand / detach は呼ばれない）", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { handlers, chromeDebugger } = await loadBackground({
      debuggerAttachError: new Error("Cannot attach"),
    });

    await expect(
      handlers.get("sendTrustedCmdP")!({
        data: { isMac: true },
        sender: { tab: { id: 42 } },
      }),
    ).rejects.toThrow("Cannot attach");

    // attach 失敗 → inner try-finally に入らない → sendCommand / detach は呼ばれない
    expect(chromeDebugger.sendCommand).not.toHaveBeenCalled();
    expect(chromeDebugger.detach).not.toHaveBeenCalled();
    // outer catch で warn
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("sendTrustedCmdP failed"), expect.any(Error));
  });
});
