import { beforeEach, describe, expect, it, vi } from "vitest";

import { CLIPS_PER_REQUEST, PHASE } from "../../shared/constants";
import type { PromptEntry } from "../../shared/api";
import type { ResumeState, RunRange } from "../lib/resume-state";
import { makePromptEntries } from "./_helpers";

interface RunPayload {
  entries: PromptEntry[];
  playlistName?: string;
  range?: RunRange;
  collectionId?: string;
  indices?: number[];
  submittedClipIds?: string[];
  playlistExpectedClipCount?: number;
}

type Handler = (message: { data: Record<string, unknown> }) => unknown;
type RunHandler = (message: { data: RunPayload }) => { ok: true };

const writeResumeStateMock = vi.fn<(state: ResumeState) => Promise<void>>();
const clearResumeStateForCollectionMock = vi.fn(() => Promise.resolve());

interface ProgressMessage {
  phase: string;
  index?: number;
  message?: string;
}

async function loadContentScriptWithPlaylistRows(
  submittedIdsFromTracker: string[],
  playlistRowsResult: HTMLElement[] | Error,
  overrides?: {
    postDownloadedError?: Error;
    postDownloadedRejectOnCall?: number;
    downloadFormatValue?: unknown;
    // Cmd+P 前ガードが読む「実際の選択中 clip ID」(#1411)。未指定は multi-select した ID と同一
    //（= 余剰なしでガード通過）。stale selection の混入はここへ余剰 ID を足して再現する。
    guardSelectedClipIds?: string[];
    // Cmd+P 前ガードの走査自体を失敗させる (#1411 fail-open)。指定時 readSelectedClipIds が reject する。
    guardReadError?: Error;
  },
) {
  vi.resetModules();
  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => definition);

  const handlers = new Map<string, Handler>();
  const progressMessages: ProgressMessage[] = [];
  const sentMessages: Array<{ type: string; payload: unknown }> = [];
  let postDownloadedCallCount = 0;
  let lastMultiSelectIds: string[] = [];
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const scrollAndMultiSelectByIdsMock = vi.fn((ids: string[], _options: unknown) => {
    lastMultiSelectIds = ids;
    if (playlistRowsResult instanceof Error) {
      return Promise.reject(playlistRowsResult);
    }
    return Promise.resolve(playlistRowsResult instanceof Array ? playlistRowsResult.length : 0);
  });
  const readSelectedClipIdsMock = vi.fn(() => {
    if (overrides?.guardReadError) {
      return Promise.reject(overrides.guardReadError);
    }
    return Promise.resolve(overrides?.guardSelectedClipIds ?? lastMultiSelectIds);
  });
  const openAddToPlaylistDialogViaCmdPMock = vi.fn(() => Promise.resolve({} as HTMLElement));
  const scheduleRunCompleteReloadMock = vi.fn();
  const cancelScheduledRunCompleteReloadMock = vi.fn();

  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((type: string, handler: Handler) => {
      handlers.set(type, handler);
    }),
    sendMessage: vi.fn((type: string, payload?: unknown) => {
      sentMessages.push({ type, payload });
      if (type === "progress") {
        progressMessages.push(payload as ProgressMessage);
      }
      if (type === "startDownload") {
        return Promise.resolve({ ok: true });
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
      writeResumeState: writeResumeStateMock,
      clearResumeStateForCollection: clearResumeStateForCollectionMock,
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
    initSnapshot: vi.fn((entries: PromptEntry[], playlistName?: string) => ({
      entries,
      playlistName,
      itemStates: entries.map(() => "pending"),
      isRunning: true,
      submittedClipIds: [],
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
      getSubmittedIds: vi.fn(() => submittedIdsFromTracker),
      getPendingSubmittedIds: vi.fn(() => []),
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
    clickPlaylistRowByName: vi.fn(() => Promise.resolve()),
    fillPlaylistNameAndCreate: vi.fn(() => Promise.resolve()),
    openAddToPlaylistDialogViaCmdP: openAddToPlaylistDialogViaCmdPMock,
    readSelectedClipIds: readSelectedClipIdsMock,
    scrollAndMultiSelectByIds: scrollAndMultiSelectByIdsMock,
    waitForPlaylistDialogClose: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../lib/page-reload", () => ({
    scheduleRunCompleteReload: scheduleRunCompleteReloadMock,
    cancelScheduledRunCompleteReload: cancelScheduledRunCompleteReloadMock,
  }));

  vi.doMock("../../shared/playlist-scrape", () => ({
    scrapePlaylistsFromMe: vi.fn(() => [
      { title: "vj | regression", url: "https://suno.com/playlist/regression" },
      { title: "vj | manual range", url: "https://suno.com/playlist/manual-range" },
    ]),
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

  vi.doMock("../lib/download", () => ({
    triggerDownloadAll: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../../shared/api", () => ({
    postDownloaded: vi.fn(() => Promise.resolve()),
  }));

  const content = await import("../entrypoints/content");
  content.default.main({} as NonNullable<Parameters<typeof content.default.main>[0]>);

  const runHandler = handlers.get("run") as RunHandler | undefined;
  if (!runHandler) {
    throw new Error("run message handler was not registered");
  }
  return {
    handlers,
    scrollAndMultiSelectByIdsMock,
    readSelectedClipIdsMock,
    openAddToPlaylistDialogViaCmdPMock,
    scheduleRunCompleteReloadMock,
    cancelScheduledRunCompleteReloadMock,
    progressMessages,
    runHandler,
    sentMessages,
  };
}

describe("content.ts playlist 追加失敗時の resume state", () => {
  beforeEach(() => {
    writeResumeStateMock.mockReset();
    clearResumeStateForCollectionMock.mockReset();
  });

  it("Given 通常 run で playlist row 解決が失敗 When run Then tracker が観測した submittedClipIds を保存する", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", style: "style 1", lyrics: "" },
      { name: "track-2", style: "style 2", lyrics: "" },
    ];
    const currentSubmittedClipIds = Array.from(
      { length: entries.length * CLIPS_PER_REQUEST },
      (_, index) => `current-clip-${index + 1}`,
    );
    const { progressMessages, runHandler } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      new Error("playlist rows missing"),
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(writeResumeStateMock).toHaveBeenCalledTimes(1));

    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "collection-a",
        failedIndex: entries.length,
        total: entries.length,
        submittedClipIds: currentSubmittedClipIds,
        playlistExpectedClipCount: entries.length * CLIPS_PER_REQUEST,
      }),
    );
    expect(progressMessages).toContainEqual(
      expect.objectContaining({
        phase: PHASE.ERROR,
        index: entries.length,
      }),
    );
  });

  it("Given 全 entry 生成済みで playlist row 解決が失敗 When resume run Then 保存済み submittedClipIds と期待件数を保持する", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", style: "style 1", lyrics: "" },
      { name: "track-2", style: "style 2", lyrics: "" },
    ];
    const submittedClipIds = Array.from(
      { length: entries.length * CLIPS_PER_REQUEST },
      (_, index) => `clip-${index + 1}`,
    );
    const { runHandler } = await loadContentScriptWithPlaylistRows([], new Error("playlist rows missing"));

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
        range: { start: entries.length, end: entries.length - 1 },
        submittedClipIds,
      },
    });
    await vi.waitFor(() => expect(writeResumeStateMock).toHaveBeenCalledTimes(1));

    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "collection-a",
        failedIndex: entries.length,
        total: entries.length,
        submittedClipIds,
        playlistExpectedClipCount: entries.length * CLIPS_PER_REQUEST,
      }),
    );
  });

  it("Given 2 entries で 3 ID しか保存されていない When playlist-only resume Then ERROR で止めて部分 playlist を作らない", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", style: "style 1", lyrics: "" },
      { name: "track-2", style: "style 2", lyrics: "" },
    ];
    const submittedClipIds = ["clip-1", "clip-2", "clip-3"];
    const { progressMessages, scrollAndMultiSelectByIdsMock, runHandler } = await loadContentScriptWithPlaylistRows(
      [],
      [],
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
        range: { start: entries.length, end: entries.length - 1 },
        submittedClipIds,
        playlistExpectedClipCount: entries.length * CLIPS_PER_REQUEST,
      },
    });
    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          index: entries.length,
          message: expect.stringContaining("expected 4, got 3"),
        }),
      ),
    );

    expect(scrollAndMultiSelectByIdsMock).not.toHaveBeenCalled();
  });

  it("Given 保存済み ID と今回再実行 ID が混在 When title fallback を作る Then 旧 ID と今回 ID に対応 entry title を割り当てる", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", title: "Track One", style: "style 1", lyrics: "" },
      { name: "track-2", title: "Track Two", style: "style 2", lyrics: "" },
    ];
    const previousSubmittedClipIds = ["old-clip-1", "old-clip-2"];
    const currentSubmittedClipIds = ["new-clip-1", "new-clip-2"];
    const rows = [...previousSubmittedClipIds, ...currentSubmittedClipIds].map(() => ({}) as HTMLElement);
    const { scrollAndMultiSelectByIdsMock, runHandler } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      rows,
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
        indices: [1],
        submittedClipIds: previousSubmittedClipIds,
        playlistExpectedClipCount: 4,
      },
    });
    await vi.waitFor(() => expect(scrollAndMultiSelectByIdsMock).toHaveBeenCalledTimes(1));

    const [ids, options] = scrollAndMultiSelectByIdsMock.mock.calls[0] as [
      string[],
      { titleFallbackMap: Map<string, string> },
    ];
    expect(ids).toEqual([...previousSubmittedClipIds, ...currentSubmittedClipIds]);
    expect(options.titleFallbackMap.get("old-clip-1")).toBe("Track One");
    expect(options.titleFallbackMap.get("old-clip-2")).toBe("Track One");
    expect(options.titleFallbackMap.get("new-clip-1")).toBe("Track Two");
    expect(options.titleFallbackMap.get("new-clip-2")).toBe("Track Two");
  });

  it("Given 旧 payload が期待件数なしで playlist-only resume When ID が不足 Then ERROR で止める", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", style: "style 1", lyrics: "" },
      { name: "track-2", style: "style 2", lyrics: "" },
    ];
    const submittedClipIds = ["clip-1", "clip-2", "clip-3"];
    const { progressMessages, scrollAndMultiSelectByIdsMock, runHandler } = await loadContentScriptWithPlaylistRows(
      [],
      [],
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
        range: { start: entries.length, end: entries.length - 1 },
        submittedClipIds,
      },
    });
    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          index: entries.length,
          message: expect.stringContaining("expected 4, got 3"),
        }),
      ),
    );

    expect(scrollAndMultiSelectByIdsMock).not.toHaveBeenCalled();
  });

  it("Given collection の manual range run When playlist 追加 Then /downloaded には送らない", async () => {
    const entries = Array.from(
      { length: 24 },
      (_, index): PromptEntry => ({
        name: `track-${index + 1}`,
        style: `style ${index + 1}`,
        lyrics: "",
      }),
    );
    const range = { start: 4, end: 7 };
    const currentSubmittedClipIds = Array.from(
      { length: (range.end - range.start + 1) * CLIPS_PER_REQUEST },
      (_, index) => `range-clip-${index + 1}`,
    );
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const { scrollAndMultiSelectByIdsMock, runHandler, sentMessages } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      rows,
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | manual range",
        collectionId: "collection-a",
        range,
      },
    });
    await vi.waitFor(() => expect(scrollAndMultiSelectByIdsMock).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "progress")).toBe(true));

    expect(scrollAndMultiSelectByIdsMock).toHaveBeenCalledWith(
      currentSubmittedClipIds,
      expect.objectContaining({ isAborted: expect.any(Function) }),
    );
    expect(writeResumeStateMock).not.toHaveBeenCalled();
    expect(sentMessages.filter((m) => m.type === "startDownload")).toHaveLength(0);
    expect(sentMessages.filter((m) => m.type === "postDownloaded")).toHaveLength(0);
  });

  it("Given full collection run When Download all completes Then playlist URL と ZIP 完了を POST して FINISHED になる", async () => {
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const currentSubmittedClipIds = ["clip-1", "clip-2"];
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const { handlers, progressMessages, runHandler, sentMessages } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      rows,
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "startDownload")).toBe(true));

    handlers.get("downloadComplete")!({
      data: { filename: "/Users/test/Downloads/regression.zip" },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(clearResumeStateForCollectionMock).toHaveBeenCalledWith("collection-a");

    const downloadedPosts = sentMessages.filter((m) => m.type === "postDownloaded");
    expect(downloadedPosts).toHaveLength(2);
    expect(downloadedPosts[0].payload).toMatchObject({
      body: {
        file_count: 0,
        format: "mp3",
        suno_playlist_url: "https://suno.com/playlist/regression",
      },
    });
    expect(downloadedPosts[1].payload).toMatchObject({
      body: {
        file_count: 2,
        expected_file_count: 2,
        format: "mp3",
        suno_playlist_url: "https://suno.com/playlist/regression",
        download_path: "/Users/test/Downloads/regression.zip",
      },
    });
  });

  it.each(["m4a", "wav"] as const)(
    "Given download format=%s When full collection run completes Then startDownload と postDownloaded に同じ形式を渡す",
    async (format) => {
      const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
      const currentSubmittedClipIds = ["clip-1", "clip-2"];
      const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
      const { handlers, progressMessages, runHandler, sentMessages } = await loadContentScriptWithPlaylistRows(
        currentSubmittedClipIds,
        rows,
        { downloadFormatValue: format },
      );

      runHandler({
        data: {
          entries,
          playlistName: "vj | regression",
          collectionId: "collection-a",
        },
      });
      await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "startDownload")).toBe(true));

      handlers.get("downloadComplete")!({
        data: { filename: "/Users/test/Downloads/regression.zip" },
      });

      await vi.waitFor(() =>
        expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })),
      );
      expect(sentMessages.find((m) => m.type === "startDownload")?.payload).toMatchObject({ format });
      const downloadedPosts = sentMessages.filter((m) => m.type === "postDownloaded");
      expect(downloadedPosts).toHaveLength(2);
      expect(downloadedPosts[0].payload).toMatchObject({ body: { format } });
      expect(downloadedPosts[1].payload).toMatchObject({ body: { format } });
    },
  );

  it("Given full collection run When ZIP 完了後の postDownloaded が失敗 Then ERROR で止めて resume state を保持する", async () => {
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const currentSubmittedClipIds = ["clip-1", "clip-2"];
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const { handlers, progressMessages, runHandler, sentMessages } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      rows,
      {
        postDownloadedError: new Error("POST downloaded failed: 500 Internal Server Error"),
        postDownloadedRejectOnCall: 2,
      },
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "startDownload")).toBe(true));

    handlers.get("downloadComplete")!({
      data: { filename: "/Users/test/Downloads/regression.zip" },
    });

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          index: entries.length,
          message: expect.stringContaining("POST downloaded failed"),
        }),
      ),
    );
    expect(sentMessages.filter((m) => m.type === "postDownloaded")).toHaveLength(2);
    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "collection-a",
        failedIndex: entries.length,
        total: entries.length,
        submittedClipIds: currentSubmittedClipIds,
        playlistExpectedClipCount: currentSubmittedClipIds.length,
      }),
    );
    expect(clearResumeStateForCollectionMock).not.toHaveBeenCalled();
  });

  it("Given 通常 run で playlist row 解決が失敗 When ERROR 終了 Then 完了時リロードは走らない", async () => {
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const { progressMessages, scheduleRunCompleteReloadMock, runHandler } = await loadContentScriptWithPlaylistRows(
      ["clip-1", "clip-2"],
      new Error("playlist rows missing"),
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.ERROR })));

    expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
  });

  it("Given full collection run の Download all が失敗 When run Then ERROR のまま終了する", async () => {
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const currentSubmittedClipIds = ["clip-1", "clip-2"];
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const { handlers, progressMessages, runHandler, sentMessages } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      rows,
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "startDownload")).toBe(true));

    handlers.get("downloadFailed")!({
      data: { message: "ZIP ダウンロードが中断されました" },
    });

    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          index: entries.length,
          message: expect.stringContaining("ZIP ダウンロードが中断されました"),
        }),
      ),
    );
    const lastProgress = progressMessages.at(-1);
    expect(lastProgress).toMatchObject({ phase: PHASE.ERROR });
    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "collection-a",
        failedIndex: entries.length,
        total: entries.length,
        submittedClipIds: currentSubmittedClipIds,
        playlistExpectedClipCount: currentSubmittedClipIds.length,
      }),
    );
    expect(clearResumeStateForCollectionMock).not.toHaveBeenCalled();
  });
});

// #1411: 連続実行時の stale selection 累積汚染対策（完了時リロード + Cmd+P 前ガード）
describe("content.ts run 一式完了時のページリロード (#1411)", () => {
  beforeEach(() => {
    writeResumeStateMock.mockReset();
    clearResumeStateForCollectionMock.mockReset();
  });

  it("Given full collection run が完走 When FINISHED Then resume state 消去の後にリロードが予約される", async () => {
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const currentSubmittedClipIds = ["clip-1", "clip-2"];
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const {
      handlers,
      progressMessages,
      runHandler,
      sentMessages,
      readSelectedClipIdsMock,
      openAddToPlaylistDialogViaCmdPMock,
      scheduleRunCompleteReloadMock,
    } = await loadContentScriptWithPlaylistRows(currentSubmittedClipIds, rows);

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "startDownload")).toBe(true));
    handlers.get("downloadComplete")!({
      data: { filename: "/Users/test/Downloads/regression.zip" },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    // ガード通過（余剰なし）で Cmd+P まで進んでいる。走査は軽量モード
    //（1 pass + 超過即打ち切り + ID 劣化 row skip）で呼ばれる (#1411)
    expect(readSelectedClipIdsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        maxScanPasses: 1,
        stopAboveCount: currentSubmittedClipIds.length,
        skipUnresolvedIds: true,
      }),
    );
    expect(openAddToPlaylistDialogViaCmdPMock).toHaveBeenCalledTimes(1);
    // リロードは resume state 消去の後（#1321 の再開フローと衝突しない順序保証）
    expect(scheduleRunCompleteReloadMock).toHaveBeenCalledTimes(1);
    expect(clearResumeStateForCollectionMock).toHaveBeenCalledWith("collection-a");
    expect(clearResumeStateForCollectionMock.mock.invocationCallOrder[0]).toBeLessThan(
      scheduleRunCompleteReloadMock.mock.invocationCallOrder[0],
    );
  });

  it("Given manual range run（download なし）が完走 When FINISHED Then リロードが予約される", async () => {
    const entries = makePromptEntries(24);
    const range = { start: 4, end: 7 };
    const currentSubmittedClipIds = Array.from(
      { length: (range.end - range.start + 1) * CLIPS_PER_REQUEST },
      (_, index) => `range-clip-${index + 1}`,
    );
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const { progressMessages, runHandler, scheduleRunCompleteReloadMock } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      rows,
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | manual range",
        collectionId: "collection-a",
        range,
      },
    });
    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));

    expect(scheduleRunCompleteReloadMock).toHaveBeenCalledTimes(1);
  });

  it("Given playlist 無しの run（単一ファイル mode）が完走 When FINISHED Then リロードは走らない", async () => {
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const { progressMessages, runHandler, scheduleRunCompleteReloadMock, scrollAndMultiSelectByIdsMock } =
      await loadContentScriptWithPlaylistRows([], []);

    runHandler({ data: { entries } });
    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));

    // multi-select 自体が走らない = 選択状態を作らないためリロード不要
    expect(scrollAndMultiSelectByIdsMock).not.toHaveBeenCalled();
    expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
  });

  it("Given resume state 消去が失敗 When run 完走 Then FINISHED は維持しリロードのみ見送る", async () => {
    // 消去失敗のままリロードすると ResumeBanner が「中断からの再開」と誤判定するため、
    // FINISHED（終端 phase の不変条件）は守りつつリロードだけ見送る (#1411)。
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const currentSubmittedClipIds = ["clip-1", "clip-2"];
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    clearResumeStateForCollectionMock.mockRejectedValueOnce(new Error("storage down"));
    const { handlers, progressMessages, runHandler, sentMessages, scheduleRunCompleteReloadMock } =
      await loadContentScriptWithPlaylistRows(currentSubmittedClipIds, rows);

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "startDownload")).toBe(true));
    handlers.get("downloadComplete")!({
      data: { filename: "/Users/test/Downloads/regression.zip" },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
  });
});

describe("content.ts Cmd+P 前の stale selection ガード (#1411)", () => {
  beforeEach(() => {
    writeResumeStateMock.mockReset();
    clearResumeStateForCollectionMock.mockReset();
  });

  it("Given 前回 run の選択が残っている When playlist 追加 Then Cmd+P 前に fail-loud で ERROR にする", async () => {
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const currentSubmittedClipIds = ["clip-1", "clip-2"];
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const { progressMessages, runHandler, openAddToPlaylistDialogViaCmdPMock, scheduleRunCompleteReloadMock } =
      await loadContentScriptWithPlaylistRows(currentSubmittedClipIds, rows, {
        // 完了時リロードが走らなかった経路の再現: target 2 件 + 前回 run の残り 2 件が選択中
        guardSelectedClipIds: ["clip-1", "clip-2", "stale-1", "stale-2"],
      });

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({
          phase: PHASE.ERROR,
          index: entries.length,
          message: expect.stringContaining("ページをリロード"),
        }),
      ),
    );

    // 汚染された playlist を作らない: Cmd+P まで到達しない
    expect(openAddToPlaylistDialogViaCmdPMock).not.toHaveBeenCalled();
    expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
    // ERROR メッセージに余剰 ID を含め、運用者が混入源を特定できるようにする
    const errorMessage = progressMessages.find((m) => m.phase === PHASE.ERROR)?.message ?? "";
    expect(errorMessage).toContain("stale-1");
    expect(errorMessage).toContain("stale-2");
    // resume state は保持され、リロード後に playlist-only 再開できる
    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "collection-a",
        failedIndex: entries.length,
        submittedClipIds: currentSubmittedClipIds,
      }),
    );
    expect(clearResumeStateForCollectionMock).not.toHaveBeenCalled();
  });

  it("Given ガード走査自体が失敗（render flake 等） When playlist 追加 Then fail-open でスキップし run を完走させる", async () => {
    // ガードは保険であり、走査失敗（0 件 throw / scroller 不在）で生成完了済みの run を
    // 巻き添えに ERROR 化しない。警告のみで Cmd+P へ続行する (#1411)。
    const entries: PromptEntry[] = [{ name: "track-1", style: "style 1", lyrics: "" }];
    const currentSubmittedClipIds = ["clip-1", "clip-2"];
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const { handlers, progressMessages, runHandler, sentMessages, openAddToPlaylistDialogViaCmdPMock } =
      await loadContentScriptWithPlaylistRows(currentSubmittedClipIds, rows, {
        guardReadError: new Error("選択中の clip がありません。Suno で対象曲を選択してから再実行してください。"),
      });

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(sentMessages.some((m) => m.type === "startDownload")).toBe(true));
    handlers.get("downloadComplete")!({
      data: { filename: "/Users/test/Downloads/regression.zip" },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(openAddToPlaylistDialogViaCmdPMock).toHaveBeenCalledTimes(1);
    expect(progressMessages).not.toContainEqual(expect.objectContaining({ phase: PHASE.ERROR }));
  });
});
