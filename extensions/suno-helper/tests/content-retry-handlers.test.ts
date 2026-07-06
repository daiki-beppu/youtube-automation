// retryPlaylist / retryDownload メッセージハンドラの回帰テスト (#1251)。
// content-playlist-error.test.ts の vi.doMock パターンを雛形とし、
// retry 系ハンドラの running ガード・正常完了・throw→ERROR を網羅する。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PHASE } from "../../shared/constants";
import type { RetryPlaylistPayload } from "../lib/messaging";

interface ProgressMessage {
  phase: string;
  total: number;
  index?: number;
  message?: string;
}

type Handler = (message: { data: unknown }) => unknown;

const clearResumeStateMock = vi.fn(() => Promise.resolve());
const scheduleRunCompleteReloadMock = vi.fn();
const cancelScheduledRunCompleteReloadMock = vi.fn();

function expectPostDownloadedBody(payload: unknown, expectedBody: Record<string, unknown>): void {
  expect(payload).toMatchObject({ body: expectedBody });
  const body = (payload as { body?: Record<string, unknown> }).body;
  expect(body).not.toHaveProperty("suno_playlist_url");
}

function retryPlaylistMessage(overrides: Partial<RetryPlaylistPayload> = {}): { data: RetryPlaylistPayload } {
  return {
    data: {
      playlistName: "test-playlist",
      submittedClipIds: [],
      expectedClipCount: 0,
      collectionId: "coll-1",
      ...overrides,
    },
  };
}

async function loadContentScript(overrides?: {
  addClipsToPlaylistError?: Error;
  durationsById?: Record<string, number | undefined>;
  guardSelectedClipIds?: string[];
  readSelectedClipIdsError?: Error;
  triggerDownloadAllError?: Error;
  startDownloadResult?: { ok: true } | { ok: false; message: string };
  postDownloadedError?: Error;
  postDownloadedRejectOnCall?: number;
  downloadFormatValue?: unknown;
}) {
  vi.resetModules();
  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => definition);
  scheduleRunCompleteReloadMock.mockReset();
  cancelScheduledRunCompleteReloadMock.mockReset();

  const handlers = new Map<string, Handler>();
  const progressMessages: ProgressMessage[] = [];
  const sentMessages: Array<{ type: string; payload: unknown }> = [];
  let postDownloadedCallCount = 0;

  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((type: string, handler: Handler) => {
      handlers.set(type, handler);
      return vi.fn();
    }),
    sendMessage: vi.fn((type: string, payload?: unknown) => {
      sentMessages.push({ type, payload });
      if (type === "progress") {
        progressMessages.push(payload as ProgressMessage);
      }
      if (type === "startDownload") {
        return Promise.resolve(overrides?.startDownloadResult ?? { ok: true });
      }
      if (type === "postDownloaded" && overrides?.postDownloadedError) {
        postDownloadedCallCount += 1;
        if ((overrides.postDownloadedRejectOnCall ?? 1) === postDownloadedCallCount) {
          return Promise.reject(overrides.postDownloadedError);
        }
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
    initSnapshot: vi.fn((_entries: unknown[], options: { collectionId: string; playlistName?: string }) => ({
      collectionId: options.collectionId,
      playlistName: options.playlistName,
      entries: [],
      itemStates: [],
      isRunning: true,
    })),
    applyProgress: vi.fn((snapshot: object, payload: object) => ({ ...snapshot, progress: payload })),
  }));

  vi.doMock("../lib/bridge-listener", () => ({
    attachBridgeListener: vi.fn(),
    createFeedPoller: vi.fn(() => ({ start: vi.fn(), stop: vi.fn() })),
    requestFeedPoll: vi.fn(() => Promise.resolve([])),
    requestSliderSet: vi.fn(),
  }));

  vi.doMock("../lib/clip-tracker", () => ({
    createClipTracker: vi.fn(() => ({
      clearSubmittedIds: vi.fn(),
      getSubmittedIds: vi.fn(() => []),
      getPendingSubmittedIds: vi.fn(() => []),
      getDuration: vi.fn((clipId: string) =>
        overrides?.durationsById && Object.prototype.hasOwnProperty.call(overrides.durationsById, clipId)
          ? overrides.durationsById[clipId]
          : 120,
      ),
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

  const scrollAndMultiSelectByIdsMock = vi.fn((ids: string[]) => Promise.resolve(ids.length));
  vi.doMock("../../shared/playlist-dom", () => ({
    clickPlaylistRowByName: overrides?.addClipsToPlaylistError
      ? vi.fn(() => Promise.reject(overrides.addClipsToPlaylistError))
      : vi.fn(() => Promise.resolve()),
    fillPlaylistNameAndCreate: vi.fn(() => Promise.resolve()),
    openAddToPlaylistDialogViaCmdP: vi.fn(() => Promise.resolve({} as HTMLElement)),
    readSelectedClipIds: overrides?.readSelectedClipIdsError
      ? vi.fn(() => Promise.reject(overrides.readSelectedClipIdsError))
      : vi.fn(() => Promise.resolve(overrides?.guardSelectedClipIds ?? ["clip-1", "clip-2"])),
    scrollAndMultiSelectByIds: scrollAndMultiSelectByIdsMock,
    waitForPlaylistDialogClose: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../lib/page-reload", () => ({
    scheduleRunCompleteReload: scheduleRunCompleteReloadMock,
    cancelScheduledRunCompleteReload: cancelScheduledRunCompleteReloadMock,
  }));

  // 完了時リロード前の snapshot 退避。実物は chrome.storage へアクセスするため node 環境では mock 必須。
  // 退避契約そのものの検証は content-finished-snapshot.test.ts が担う。
  vi.doMock("../lib/finished-snapshot", () => ({
    writeFinishedSnapshot: vi.fn(() => Promise.resolve()),
    readFreshFinishedSnapshot: vi.fn(() => Promise.resolve(null)),
    clearFinishedSnapshot: vi.fn(() => Promise.resolve()),
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

  const normalizeDownloadFormat = (value: unknown): "mp3" | "m4a" | "wav" =>
    value === "mp3" || value === "m4a" || value === "wav" ? value : "mp3";
  vi.doMock("../lib/storage", () => ({
    serverUrlItem: { getValue: vi.fn(() => Promise.resolve("http://localhost:8787")) },
    downloadFormatItem: { getValue: vi.fn(() => Promise.resolve(overrides?.downloadFormatValue ?? "mp3")) },
    readDownloadFormat: vi.fn(() => Promise.resolve(normalizeDownloadFormat(overrides?.downloadFormatValue ?? "mp3"))),
  }));

  const triggerDownloadAllMock = overrides?.triggerDownloadAllError
    ? vi.fn(() => Promise.reject(overrides.triggerDownloadAllError))
    : vi.fn(() => Promise.resolve());
  vi.doMock("../lib/download", () => ({
    triggerDownloadAll: triggerDownloadAllMock,
  }));

  vi.doMock("../../shared/api", () => ({}));

  const content = await import("../entrypoints/content");
  content.default.main({} as NonNullable<Parameters<typeof content.default.main>[0]>);

  return {
    handlers,
    progressMessages,
    sentMessages,
    triggerDownloadAllMock,
    scrollAndMultiSelectByIdsMock,
    scheduleRunCompleteReloadMock,
  };
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
    retryHandler(retryPlaylistMessage({ playlistName: "test" }));

    // running=true の間に再度呼ぶ → running ガードで即 ok
    const result = retryHandler(retryPlaylistMessage({ playlistName: "test2" }));
    expect(result).toEqual({ ok: true });
  });
});

describe('content onMessage("retryPlaylist"): payload contract', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    ["collectionId 欠落", { collectionId: undefined }, /retryPlaylist\.collectionId/],
    ["playlistName 欠落", { playlistName: undefined }, /retryPlaylist\.playlistName/],
    ["durationFilter が不正", { durationFilter: { min_sec: true, max_sec: 300 } }, /retryPlaylist\.durationFilter/],
  ] as const)(
    "Given %s payload When retryPlaylist Then fail-loud し副作用を起こさない",
    async (_label, override, message) => {
      const { handlers, progressMessages, scheduleRunCompleteReloadMock } = await loadContentScript();
      const retryHandler = handlers.get("retryPlaylist")!;

      expect(() =>
        retryHandler({
          data: { ...retryPlaylistMessage({ submittedClipIds: ["clip-1"], expectedClipCount: 1 }).data, ...override },
        }),
      ).toThrow(message);
      expect(progressMessages).toHaveLength(0);
      expect(clearResumeStateMock).not.toHaveBeenCalled();
      expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
    },
  );
});

describe('content onMessage("retryPlaylist"): 正常完了', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given collectionId 付き When retryPlaylist Then playlist 追加後に download まで進めて resume state を消去する", async () => {
    const { handlers, progressMessages, sentMessages, scheduleRunCompleteReloadMock } = await loadContentScript();

    // submittedClipIds を指定し resolvePlaylistClipIds が正常に返るようにする
    const clipIds = ["clip-1", "clip-2"];
    handlers.get("retryPlaylist")!({
      data: {
        playlistName: "test-playlist",
        submittedClipIds: clipIds,
        expectedClipCount: clipIds.length,
        collectionId: "coll-1",
        shouldDownload: true,
      },
    });

    await new Promise((r) => setTimeout(r, 0));
    handlers.get("downloadComplete")!({
      data: { filename: "/Users/test/Downloads/test-playlist.zip" },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(clearResumeStateMock).toHaveBeenCalledWith("coll-1");
    // 完了時リロード (#1411): resume state 消去の後に予約される（再開誤判定の防止）
    expect(scheduleRunCompleteReloadMock).toHaveBeenCalledTimes(1);
    expect(clearResumeStateMock.mock.invocationCallOrder[0]).toBeLessThan(
      scheduleRunCompleteReloadMock.mock.invocationCallOrder[0],
    );
    const downloadedPosts = sentMessages.filter((m) => m.type === "postDownloaded");
    expect(downloadedPosts).toHaveLength(1);
    expectPostDownloadedBody(downloadedPosts[0].payload, {
      file_count: clipIds.length,
      expected_file_count: clipIds.length,
      download_path: "/Users/test/Downloads/test-playlist.zip",
    });
  });

  it("Given partial collection retryPlaylist When playlist 追加 Then download/post は実行しない", async () => {
    const { handlers, progressMessages, sentMessages } = await loadContentScript();
    const clipIds = ["clip-1", "clip-2"];

    handlers.get("retryPlaylist")!({
      data: {
        playlistName: "test-playlist",
        submittedClipIds: clipIds,
        expectedClipCount: clipIds.length,
        collectionId: "coll-1",
        shouldDownload: false,
      },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(clearResumeStateMock).toHaveBeenCalledWith("coll-1");
    expect(sentMessages.filter((m) => m.type === "startDownload")).toHaveLength(0);
    expect(sentMessages.filter((m) => m.type === "postDownloaded")).toHaveLength(0);
  });

  it("Given retryPlaylist に duration NG clip が混在 When 未正規化 payload Then OK clip IDs のみを multi-select する", async () => {
    const { handlers, progressMessages, scrollAndMultiSelectByIdsMock } = await loadContentScript({
      durationsById: {
        "clip-ok": 120,
        "clip-short": 30,
        "clip-unknown": undefined,
      },
      guardSelectedClipIds: ["clip-ok"],
    });

    handlers.get("retryPlaylist")!({
      data: {
        playlistName: "test-playlist",
        submittedClipIds: ["clip-ok", "clip-short", "clip-unknown"],
        expectedClipCount: 3,
        collectionId: "coll-1",
        durationFilter: { min_sec: 60, max_sec: 300 },
        submittedClipIdsAreDurationFiltered: false,
        shouldDownload: false,
      },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(scrollAndMultiSelectByIdsMock).toHaveBeenCalledWith(
      ["clip-ok"],
      expect.objectContaining({ titleFallbackMap: expect.any(Map) }),
    );
  });

  it("Given resume state 消去が失敗 When retryPlaylist 成功 Then FINISHED を維持しリロードのみ見送る（ERROR にしない）", async () => {
    // 消去失敗を catch へ流すと ERROR → 再試行誘導 → 同名 playlist の重複作成につながる。
    // playlist 追加自体は成功しているため FINISHED を維持し、再開バナー誤判定を避けるため
    // リロードだけ見送る (#1411)。
    clearResumeStateMock.mockRejectedValueOnce(new Error("storage down"));
    const { handlers, progressMessages, scheduleRunCompleteReloadMock } = await loadContentScript();
    const clipIds = ["clip-1", "clip-2"];

    handlers.get("retryPlaylist")!({
      data: {
        playlistName: "test-playlist",
        submittedClipIds: clipIds,
        expectedClipCount: clipIds.length,
        collectionId: "coll-1",
        shouldDownload: false,
      },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(progressMessages).not.toContainEqual(expect.objectContaining({ phase: PHASE.ERROR }));
    expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
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
    const { handlers, progressMessages, scheduleRunCompleteReloadMock } = await loadContentScript();

    handlers.get("retryPlaylist")!(retryPlaylistMessage());

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({ phase: PHASE.ERROR, message: expect.stringContaining("clip ID") }),
      ),
    );
    // ERROR 終了時は完了時リロードを走らせない (#1411)
    expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
  });
});

// retryDownload ----------------------------------------------------------------

describe('content onMessage("retryDownload"): 正常完了', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given collectionId 付き When retryDownload Then FINISHED phase を emit し resume state を消去する", async () => {
    const { handlers, progressMessages, sentMessages, scheduleRunCompleteReloadMock } = await loadContentScript();

    const clipIds = ["clip-1", "clip-2"];
    handlers.get("retryDownload")!({
      data: { collectionId: "coll-1", submittedClipIds: clipIds, expectedClipCount: 4 },
    });

    // async フロー（scrollAndMultiSelectByIds → performDownload → waitForDownloadComplete）
    // が downloadCompleteResolver を設定するのを待つ。
    await new Promise((r) => setTimeout(r, 0));

    // background からの downloadComplete 通知を simulate して waitForDownloadComplete を解決する
    handlers.get("downloadComplete")!({
      data: { filename: "/Users/test/Downloads/test-playlist.zip" },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(clearResumeStateMock).toHaveBeenCalledWith("coll-1");
    // retryDownload も selectClipIds で multi-select 状態を作るため、完了時リロードを予約する (#1411)。
    // 順序は resume state 消去 → FINISHED → リロード（再開バナー誤判定の防止）。
    expect(scheduleRunCompleteReloadMock).toHaveBeenCalledTimes(1);
    expect(clearResumeStateMock.mock.invocationCallOrder[0]).toBeLessThan(
      scheduleRunCompleteReloadMock.mock.invocationCallOrder[0],
    );
    const downloadedPosts = sentMessages.filter((m) => m.type === "postDownloaded");
    expect(downloadedPosts).toHaveLength(1);
    expectPostDownloadedBody(downloadedPosts[0].payload, {
      file_count: 4,
      expected_file_count: 4,
      download_path: "/Users/test/Downloads/test-playlist.zip",
    });
  });

  it("Given 不正な保存済み download format When retryDownload Then mp3 に正規化して実行する", async () => {
    const { handlers, sentMessages, triggerDownloadAllMock } = await loadContentScript({
      downloadFormatValue: "flac",
    });

    const clipIds = ["clip-1", "clip-2"];
    handlers.get("retryDownload")!({
      data: { collectionId: "coll-1", submittedClipIds: clipIds, expectedClipCount: 4 },
    });

    await new Promise((r) => setTimeout(r, 0));
    handlers.get("downloadComplete")!({
      data: { filename: "/Users/test/Downloads/test-playlist.zip" },
    });

    await vi.waitFor(() => expect(triggerDownloadAllMock).toHaveBeenCalledWith("mp3"));
    expect(sentMessages.find((m) => m.type === "startDownload")?.payload).toMatchObject({ format: "mp3" });
    await vi.waitFor(() => expect(sentMessages.filter((m) => m.type === "postDownloaded")).toHaveLength(1));
    const downloadedPosts = sentMessages.filter((m) => m.type === "postDownloaded");
    expectPostDownloadedBody(downloadedPosts[0].payload, { format: "mp3" });
  });
});

describe('content onMessage("retryDownload"): payload contract', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    ["collectionId 欠落", { collectionId: undefined }, /retryDownload\.collectionId/],
    ["submittedClipIds 欠落", { submittedClipIds: undefined }, /retryDownload\.submittedClipIds/],
  ] as const)(
    "Given %s payload When retryDownload Then fail-loud し副作用を起こさない",
    async (_label, override, message) => {
      const { handlers, progressMessages, scheduleRunCompleteReloadMock } = await loadContentScript();
      const retryHandler = handlers.get("retryDownload")!;

      expect(() =>
        retryHandler({
          data: {
            collectionId: "coll-1",
            submittedClipIds: ["clip-1"],
            ...override,
          },
        }),
      ).toThrow(message);
      expect(progressMessages).toHaveLength(0);
      expect(clearResumeStateMock).not.toHaveBeenCalled();
      expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
    },
  );
});

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
      data: { collectionId: "coll-1", submittedClipIds: ["clip-1"] },
    });

    // running=true の間に再度呼ぶ → running ガードで即 ok
    const result = retryHandler({
      data: { collectionId: "coll-2", submittedClipIds: ["clip-1"] },
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
    const { handlers, progressMessages, sentMessages } = await loadContentScript({
      triggerDownloadAllError: new Error("download trigger failed"),
    });

    handlers.get("retryDownload")!({
      data: { collectionId: "coll-1", submittedClipIds: ["clip-1"] },
    });

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          message: expect.stringContaining("download trigger failed"),
        }),
      ),
    );
    expect(sentMessages.some((m) => m.type === "cancelDownload")).toBe(true);
  });

  it("Given startDownload が拒否された When retryDownload Then Download all を押さず ERROR phase を emit する", async () => {
    const { handlers, progressMessages, sentMessages, triggerDownloadAllMock } = await loadContentScript({
      startDownloadResult: { ok: false, message: "別の Download all 監視が進行中です" },
    });

    handlers.get("retryDownload")!({
      data: { collectionId: "coll-1", submittedClipIds: ["clip-1"] },
    });

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          message: expect.stringContaining("別の Download all 監視が進行中です"),
        }),
      ),
    );
    expect(triggerDownloadAllMock).not.toHaveBeenCalled();
    expect(sentMessages.some((m) => m.type === "cancelDownload")).toBe(false);
  });

  it("Given Download all 待機中に stop When retryDownload Then watcher を cancel し downloaded POST しない", async () => {
    const { handlers, sentMessages } = await loadContentScript();

    handlers.get("retryDownload")!({
      data: { collectionId: "coll-1", submittedClipIds: ["clip-1"] },
    });

    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "startDownload")).toBe(true));
    handlers.get("stop")!({ data: {} });

    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "cancelDownload")).toBe(true), {
      timeout: 1500,
    });
    expect(sentMessages.some((m) => m.type === "postDownloaded")).toBe(false);
  });
});

// adoptSelectedClips -----------------------------------------------------------

describe('content onMessage("adoptSelectedClips"): 手動選択 clip 採用', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given 選択済み clip が期待件数分ある When adoptSelectedClips Then clipIds を返す", async () => {
    const { handlers } = await loadContentScript();

    const result = await handlers.get("adoptSelectedClips")!({
      data: { expectedClipCount: 2 },
    });

    expect(result).toEqual({ ok: true, clipIds: ["clip-1", "clip-2"] });
  });

  it("Given 選択済み clip が不足 When adoptSelectedClips Then caller にエラーを返す", async () => {
    const { handlers } = await loadContentScript({
      readSelectedClipIdsError: new Error("選択中 clip 数が一致しません: expected 2, got 1"),
    });

    await expect(
      handlers.get("adoptSelectedClips")!({
        data: { expectedClipCount: 2 },
      }) as Promise<unknown>,
    ).rejects.toThrow("選択中 clip 数が一致しません");
  });
});

describe('content onMessage("retryDownload"): postDownloaded 失敗→ERROR (#1217 TEST-1217-001)', () => {
  beforeEach(() => {
    clearResumeStateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Given postDownloaded が reject When retryDownload Then ERROR phase を emit する", async () => {
    const { handlers, progressMessages } = await loadContentScript({
      postDownloadedError: new Error("POST downloaded failed: 403 Forbidden"),
      postDownloadedRejectOnCall: 1,
    });

    const clipIds = ["clip-1", "clip-2"];
    handlers.get("retryDownload")!({
      data: { collectionId: "coll-1", submittedClipIds: clipIds },
    });

    // async フロー（scrollAndMultiSelectByIds → performDownload → waitForDownloadComplete）
    // が downloadCompleteResolver を設定するのを待つ。
    await new Promise((r) => setTimeout(r, 0));

    // background からの downloadComplete 通知を simulate
    handlers.get("downloadComplete")!({
      data: { filename: "test-playlist.zip" },
    });

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          message: expect.stringContaining("403"),
        }),
      ),
    );
    expect(clearResumeStateMock).not.toHaveBeenCalled();
  });
});
