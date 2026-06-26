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

async function loadBackground(opts?: {
  searchResults?: Array<{ filename: string; startTime?: string; url?: string }>;
  debuggerAttachError?: Error;
  debuggerSendCommandError?: Error;
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

  vi.stubGlobal("browser", {
    runtime: {
      onInstalled: { addListener: vi.fn() },
      getManifest: () => ({ version: "0.1.0" }),
    },
    action: { onClicked: { addListener: vi.fn() } },
    tabs: {
      create: vi.fn(() => Promise.resolve({ id: 99 })),
      remove: vi.fn(() => Promise.resolve()),
    },
  });

  // chrome.downloads stub
  const downloadListeners: Array<(delta: DownloadDelta) => void> = [];
  const removedDownloadListeners: Array<(delta: DownloadDelta) => void> = [];

  const chromeDownloads = {
    onChanged: {
      addListener: vi.fn((fn: (delta: DownloadDelta) => void) => {
        downloadListeners.push(fn);
      }),
      removeListener: vi.fn((fn: (delta: DownloadDelta) => void) => {
        removedDownloadListeners.push(fn);
      }),
    },
    search: vi.fn(
      (query: { id: number }, cb: (results: Array<{ filename: string; startTime: string; url: string }>) => void) => {
        const defaults = [
          {
            filename: `suno-playlist-${query.id}.zip`,
            startTime: new Date().toISOString(),
            url: "https://suno.com/api/download/zip",
          },
        ];
        const results = opts?.searchResults
          ? opts.searchResults.map((r) => ({
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

  vi.doMock("../../shared/api", () => ({
    postCapturedPlaylists: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../components/runner-errors", () => ({
    describeRelayFailure: vi.fn(() => ({ level: "debug" as const, text: "test" })),
  }));

  vi.doMock("../lib/auto-capture", () => ({
    autoCapturePlaylists: vi.fn(() => Promise.resolve()),
    captureFromTab: vi.fn(),
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

  vi.doMock("../lib/storage", () => ({
    serverUrlItem: {
      getValue: vi.fn(() => Promise.resolve("http://localhost:8787")),
    },
  }));

  // import triggers defineBackground callback → handlers get registered
  await import("../entrypoints/background");

  return {
    handlers,
    sentMessages,
    downloadListeners,
    removedDownloadListeners,
    chromeDownloads,
    chromeDebugger,
  };
}

// startDownload ----------------------------------------------------------------

describe('background onMessage("startDownload"): .zip 完了で downloadComplete を中継する', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given .zip ダウンロード完了 When listener 発火 Then downloadComplete を送信元タブへ中継する", async () => {
    const { handlers, sentMessages, downloadListeners, removedDownloadListeners } = await loadBackground();

    handlers.get("startDownload")!({
      data: { format: "mp3", collectionId: "coll-1" },
      sender: { tab: { id: 42 } },
    });

    expect(downloadListeners).toHaveLength(1);
    const listener = downloadListeners[0];

    // .zip ダウンロード完了を simulate
    listener({ id: 1, state: { current: "complete" } });

    // sendMessage("downloadComplete") が tabId=42 で呼ばれたことを確認
    // chrome.downloads.search の callback は同期実行されるため、
    // sendMessage は listener 呼び出し内で同期的に push される。
    expect(sentMessages).toContainEqual({
      type: "downloadComplete",
      data: { downloadId: 1, filename: expect.stringContaining(".zip") },
      tabId: 42,
    });

    // listener が解除されたことを確認
    expect(removedDownloadListeners).toHaveLength(1);
    expect(removedDownloadListeners[0]).toBe(listener);
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

    handlers.get("startDownload")!({
      data: { format: "mp3", collectionId: "coll-1" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    listener({ id: 1, state: { current: "complete" } });

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
    const { handlers, downloadListeners, removedDownloadListeners } = await loadBackground();

    handlers.get("startDownload")!({
      data: { format: "mp3", collectionId: "coll-1" },
      sender: { tab: { id: 42 } },
    });

    expect(downloadListeners).toHaveLength(1);
    expect(removedDownloadListeners).toHaveLength(0);

    // 10 分 (600000ms) を advance
    vi.advanceTimersByTime(600000);

    expect(removedDownloadListeners).toHaveLength(1);
    expect(removedDownloadListeners[0]).toBe(downloadListeners[0]);
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
    const { handlers, downloadListeners, removedDownloadListeners } = await loadBackground();

    handlers.get("startDownload")!({
      data: { format: "mp3", collectionId: "coll-1" },
      sender: { tab: { id: 42 } },
    });

    const listener = downloadListeners[0];
    // .zip ダウンロード完了で listener が解除される
    listener({ id: 1, state: { current: "complete" } });
    expect(removedDownloadListeners).toHaveLength(1);

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

    await handlers.get("sendTrustedCmdP")!({
      data: { isMac: true },
      sender: { tab: { id: 42 } },
    });

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

describe('background onMessage("sendTrustedCmdP"): attach 失敗は warn のみ', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("Given attach が throw When sendTrustedCmdP Then warn のみ（sendCommand / detach は呼ばれない）", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { handlers, chromeDebugger } = await loadBackground({
      debuggerAttachError: new Error("Cannot attach"),
    });

    await handlers.get("sendTrustedCmdP")!({
      data: { isMac: true },
      sender: { tab: { id: 42 } },
    });

    // attach 失敗 → inner try-finally に入らない → sendCommand / detach は呼ばれない
    expect(chromeDebugger.sendCommand).not.toHaveBeenCalled();
    expect(chromeDebugger.detach).not.toHaveBeenCalled();
    // outer catch で warn
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("sendTrustedCmdP failed"), expect.any(Error));
  });
});
