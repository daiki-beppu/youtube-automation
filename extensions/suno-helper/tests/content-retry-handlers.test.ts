// retryPlaylist / retryDownload メッセージハンドラの回帰テスト (#1251)。
// content-playlist-error.test.ts の vi.doMock パターンを雛形とし、
// retry 系ハンドラの running ガード・正常完了・throw→ERROR を網羅する。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PHASE } from "../../shared/constants";

interface ProgressMessage {
  phase: string;
  total: number;
  index?: number;
  message?: string;
}

// biome-ignore lint: handler types are intentionally loose for test flexibility
type Handler = (message: { data: any }) => unknown;

const clearResumeStateMock = vi.fn(() => Promise.resolve());

async function loadContentScript(overrides?: {
  addClipsToPlaylistError?: Error;
  triggerDownloadAllError?: Error;
}) {
  vi.resetModules();
  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => definition);

  const handlers = new Map<string, Handler>();
  const progressMessages: ProgressMessage[] = [];

  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((type: string, handler: Handler) => {
      handlers.set(type, handler);
      return vi.fn();
    }),
    sendMessage: vi.fn((type: string, payload?: ProgressMessage) => {
      if (type === "progress") {
        progressMessages.push(payload as ProgressMessage);
      }
      return Promise.resolve();
    }),
  }));

  vi.doMock("../lib/resume-state", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../lib/resume-state")>();
    return {
      ...actual,
      writeResumeState: vi.fn(() => Promise.resolve()),
      clearResumeStateForCollection: clearResumeStateMock,
    };
  });

  vi.doMock("../lib/preset-state", () => ({
    applyJitter: (baseMs: number) => baseMs,
    readSpeedPresetId: vi.fn(() => Promise.resolve("balanced")),
    resolveSpeedPreset: vi.fn(() => ({
      maxInflightRequests: 10,
      maxInjectRetry: 0,
      maxEntryRetry: 0,
      injectAckTimeoutMs: 1,
      interCreateDelayMs: 0,
      jitterMs: 0,
    })),
  }));

  vi.doMock("../lib/snapshot", () => ({
    initSnapshot: vi.fn((_entries: unknown[], _playlistName?: string) => ({
      entries: [],
      itemStates: [],
      isRunning: true,
    })),
    applyProgress: vi.fn((snapshot: object, payload: object) => ({ ...snapshot, progress: payload })),
  }));

  vi.doMock("../lib/bridge-listener", () => ({
    attachBridgeListener: vi.fn(),
    createFeedPoller: vi.fn(() => ({ start: vi.fn(), stop: vi.fn() })),
    requestSliderSet: vi.fn(),
  }));

  vi.doMock("../lib/clip-tracker", () => ({
    createClipTracker: vi.fn(() => ({
      clearSubmittedIds: vi.fn(),
      getSubmittedIds: vi.fn(() => []),
      getInFlightCount: vi.fn(() => 0),
      hasObservedAnyTraffic: vi.fn(() => true),
      lastChangeAt: vi.fn(() => Date.now()),
      submissionCount: vi.fn(() => 0),
    })),
  }));

  vi.doMock("../../shared/dom", () => ({
    abortableSleep: vi.fn(() => Promise.resolve()),
    CAPTCHA_WAIT_TIMEOUT_MS: 1,
    FatalRunError: class FatalRunError extends Error {},
    GENERATE_TIMEOUT_MS: 1,
    POLL_INTERVAL_MS: 1,
    SETTLE_MS: 0,
    getInFlightClipCount: vi.fn(() => 0),
    injectAdvancedFields: vi.fn(() => Promise.resolve()),
    resolveAdvancedFields: vi.fn(() => ({})),
    resolveFields: vi.fn(() => ({ style: {} as HTMLTextAreaElement, lyrics: null, title: null })),
    resolveGenerateButton: vi.fn(() => ({ click: vi.fn() }) as unknown as HTMLButtonElement),
    setNativeValue: vi.fn(),
    sleep: vi.fn(() => Promise.resolve()),
    waitForCaptchaClear: vi.fn(() => Promise.resolve()),
    waitForGeneration: vi.fn(() => Promise.resolve()),
    waitForQueueSlot: vi.fn(() => Promise.resolve()),
    detectSunoViewMode: vi.fn(() => "list"),
  }));

  vi.doMock("../../shared/playlist-dom", () => ({
    clickPlaylistRowByName: overrides?.addClipsToPlaylistError
      ? vi.fn(() => Promise.reject(overrides.addClipsToPlaylistError))
      : vi.fn(() => Promise.resolve()),
    fillPlaylistNameAndCreate: vi.fn(() => Promise.resolve()),
    openAddToPlaylistDialogViaCmdP: vi.fn(() => Promise.resolve({} as HTMLElement)),
    scrollAndMultiSelectByIds: vi.fn(() => Promise.resolve(0)),
    waitForPlaylistDialogClose: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../../shared/playlist-scrape", () => ({
    scrapePlaylistsFromMe: vi.fn(() => []),
  }));

  vi.doMock("../lib/auto-capture", () => ({
    triggerPlaylistCaptureFailSoft: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../lib/ack-probe", () => ({
    createAckWaiter: vi.fn(() => vi.fn(() => Promise.resolve())),
    markAck: vi.fn(() => Promise.resolve({ submissions: 0, domInFlight: 0 })),
  }));

  vi.doMock("../lib/entry-retry", () => ({
    runEntryWithRetry: vi.fn(() => Promise.resolve({ outcome: "success" })),
  }));

  vi.doMock("../lib/inject-retry", () => ({
    InjectNotAcknowledgedError: class InjectNotAcknowledgedError extends Error {},
    injectWithVerification: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../lib/storage", () => ({
    serverUrlItem: { getValue: vi.fn(() => Promise.resolve("http://localhost:8787")) },
    downloadFormatItem: { getValue: vi.fn(() => Promise.resolve("mp3")) },
  }));

  vi.doMock("../lib/download", () => ({
    triggerDownloadAll: overrides?.triggerDownloadAllError
      ? vi.fn(() => Promise.reject(overrides.triggerDownloadAllError))
      : vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../../shared/api", () => ({
    postDownloaded: vi.fn(() => Promise.resolve()),
  }));

  const content = await import("../entrypoints/content");
  content.default.main({} as NonNullable<Parameters<typeof content.default.main>[0]>);

  return { handlers, progressMessages };
}

// retryPlaylist ----------------------------------------------------------------

describe('content onMessage("retryPlaylist"): running ガード', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given retryPlaylist 実行中 When 再度 retryPlaylist Then ok を返す（no-op）", async () => {
    const { handlers } = await loadContentScript();

    // 最初の retryPlaylist を投入（async で走り始める → running=true）
    const retryHandler = handlers.get("retryPlaylist")!;
    retryHandler({
      data: { playlistName: "test", submittedClipIds: [], expectedClipCount: 0 },
    });

    // running=true の間に再度呼ぶ → running ガードで即 ok
    const result = retryHandler({
      data: { playlistName: "test2", submittedClipIds: [], expectedClipCount: 0 },
    });
    expect(result).toEqual({ ok: true });
  });
});

describe('content onMessage("retryPlaylist"): 正常完了', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given collectionId 付き When retryPlaylist Then FINISHED phase を emit し resume state を消去する", async () => {
    const { handlers, progressMessages } = await loadContentScript();

    // submittedClipIds を指定し resolvePlaylistClipIds が正常に返るようにする
    const clipIds = ["clip-1", "clip-2"];
    handlers.get("retryPlaylist")!({
      data: {
        playlistName: "test-playlist",
        submittedClipIds: clipIds,
        expectedClipCount: clipIds.length,
        collectionId: "coll-1",
      },
    });

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })),
    );
    expect(clearResumeStateMock).toHaveBeenCalledWith("coll-1");
  });
});

describe('content onMessage("retryPlaylist"): throw→ERROR', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given addClipsToPlaylist 内部で throw When retryPlaylist Then ERROR phase を emit する", async () => {
    // submittedClipIds=[] + expectedClipCount=0 の場合、addClipsToPlaylist 内の
    // resolvePlaylistClipIds が「clip ID が 0 件」で throw する（自然なエラー経路）。
    const { handlers, progressMessages } = await loadContentScript();

    handlers.get("retryPlaylist")!({
      data: {
        playlistName: "test-playlist",
        submittedClipIds: [],
        expectedClipCount: 0,
      },
    });

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({ phase: PHASE.ERROR, message: expect.stringContaining("clip ID") }),
      ),
    );
  });
});

// retryDownload ----------------------------------------------------------------

describe('content onMessage("retryDownload"): running ガード', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given retryDownload 実行中 When 再度 retryDownload Then ok を返す（no-op）", async () => {
    // triggerDownloadAll をエラーにしてすぐ終了させる（waitForDownloadComplete に入らないようにする）
    const { handlers } = await loadContentScript({
      triggerDownloadAllError: new Error("immediate exit"),
    });

    // 最初の retryDownload を投入
    const retryHandler = handlers.get("retryDownload")!;
    retryHandler({
      data: { collectionId: "coll-1", submittedClipIds: [] },
    });

    // running=true の間に再度呼ぶ → running ガードで即 ok
    const result = retryHandler({
      data: { collectionId: "coll-2", submittedClipIds: [] },
    });
    expect(result).toEqual({ ok: true });
  });
});

describe('content onMessage("retryDownload"): throw→ERROR', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given triggerDownloadAll が throw When retryDownload Then ERROR phase を emit する", async () => {
    const { handlers, progressMessages } = await loadContentScript({
      triggerDownloadAllError: new Error("download trigger failed"),
    });

    handlers.get("retryDownload")!({
      data: { collectionId: "coll-1", submittedClipIds: [] },
    });

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          message: expect.stringContaining("download trigger failed"),
        }),
      ),
    );
  });
});
