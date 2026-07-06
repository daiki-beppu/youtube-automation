// 完了時リロード (#1411) を跨いだ popup 進捗復元の回帰テスト。
//
// リロードは content script の in-memory snapshot（queryProgress の復元 SSOT, #852）を破棄する。
// content.ts は以下の契約で「直近完了 run の結果」を引き継ぐ:
//   - FINISHED 到達後・リロード予約の直前に snapshot を chrome.storage.local へ退避する
//   - 退避に失敗したらリロードを見送る（in-memory snapshot を生かして復元性を守る）
//   - queryProgress は in-memory を優先し、無ければ退避分を fallback で返す
//   - 次の実行開始（run / retryPlaylist / retryDownload の initSnapshot）で退避分を消去する
// content-playlist-error.test.ts の vi.doMock パターンを雛形とする。snapshot reducer
// (lib/snapshot.ts) は mock せず実物を使い、「FINISHED 適用済みの snapshot が退避される」
// ことを実データで検証する。
import { afterEach, describe, expect, it, vi } from "vitest";

import { PHASE, type SnapshotPayload } from "../../shared/constants";
import type { RunPayload } from "../lib/messaging";
import { makePromptEntries } from "./_helpers";

type Handler = (message: { data?: Record<string, unknown> }) => unknown;

interface ProgressMessage {
  phase: string;
  index?: number;
  message?: string;
}

async function loadContentScript(
  submittedIdsFromTracker: string[],
  overrides?: {
    writeFinishedSnapshotError?: Error;
    persistedFinishedSnapshot?: SnapshotPayload | null;
  },
) {
  vi.resetModules();
  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => definition);

  const handlers = new Map<string, Handler>();
  const progressMessages: ProgressMessage[] = [];
  let lastMultiSelectIds: string[] = [];

  const writeFinishedSnapshotMock = overrides?.writeFinishedSnapshotError
    ? vi.fn(() => Promise.reject(overrides.writeFinishedSnapshotError))
    : vi.fn(() => Promise.resolve());
  const readFreshFinishedSnapshotMock = vi.fn(() => Promise.resolve(overrides?.persistedFinishedSnapshot ?? null));
  const clearFinishedSnapshotMock = vi.fn(() => Promise.resolve());
  const scheduleRunCompleteReloadMock = vi.fn();
  const clearResumeStateForCollectionMock = vi.fn(() => Promise.resolve());

  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((type: string, handler: Handler) => {
      handlers.set(type, handler);
    }),
    sendMessage: vi.fn((type: string, payload?: unknown) => {
      if (type === "progress") {
        progressMessages.push(payload as ProgressMessage);
      }
      return Promise.resolve();
    }),
  }));

  vi.doMock("../lib/finished-snapshot", () => ({
    writeFinishedSnapshot: writeFinishedSnapshotMock,
    readFreshFinishedSnapshot: readFreshFinishedSnapshotMock,
    clearFinishedSnapshot: clearFinishedSnapshotMock,
  }));

  vi.doMock("../lib/page-reload", () => ({
    scheduleRunCompleteReload: scheduleRunCompleteReloadMock,
    cancelScheduledRunCompleteReload: vi.fn(),
  }));

  vi.doMock("../lib/resume-state", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../lib/resume-state")>();
    return {
      ...actual,
      writeResumeState: vi.fn(() => Promise.resolve()),
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
    setLyricsValue: vi.fn(() => Promise.resolve()),
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
    openAddToPlaylistDialogViaCmdP: vi.fn(() => Promise.resolve({} as HTMLElement)),
    readSelectedClipIds: vi.fn(() => Promise.resolve(lastMultiSelectIds)),
    scrollAndMultiSelectByIds: vi.fn((ids: string[]) => {
      lastMultiSelectIds = ids;
      return Promise.resolve(ids.length);
    }),
    waitForPlaylistDialogClose: vi.fn(() => Promise.resolve()),
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
    readDownloadFormat: vi.fn(() => Promise.resolve("mp3")),
  }));

  vi.doMock("../lib/download", () => ({
    triggerDownloadAll: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../../shared/api", () => ({}));

  const content = await import("../entrypoints/content");
  content.default.main({} as NonNullable<Parameters<typeof content.default.main>[0]>);

  const runHandler = handlers.get("run") as ((message: { data: RunPayload }) => { ok: true }) | undefined;
  if (!runHandler) {
    throw new Error("run message handler was not registered");
  }
  return {
    handlers,
    runHandler,
    progressMessages,
    writeFinishedSnapshotMock,
    readFreshFinishedSnapshotMock,
    clearFinishedSnapshotMock,
    scheduleRunCompleteReloadMock,
    clearResumeStateForCollectionMock,
  };
}

/** manual range run（download phase を skip する部分実行）で完走させる共通ペイロード。 */
function partialRunPayload(): RunPayload {
  return {
    entries: makePromptEntries(2),
    playlistName: "pl",
    range: { start: 0, end: 0 },
    collectionId: "coll-1",
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("content.ts 完了時リロード前の FINISHED snapshot 退避", () => {
  it("Given collection run が完走 When FINISHED Then FINISHED 適用済み snapshot を退避してからリロードを予約する", async () => {
    const { runHandler, progressMessages, writeFinishedSnapshotMock, scheduleRunCompleteReloadMock } =
      await loadContentScript(["clip-1", "clip-2"]);

    runHandler({ data: partialRunPayload() });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(writeFinishedSnapshotMock).toHaveBeenCalledTimes(1);
    expect(writeFinishedSnapshotMock).toHaveBeenCalledWith({
      snapshot: expect.objectContaining({
        collectionId: "coll-1",
        isRunning: false,
        progress: expect.objectContaining({ phase: PHASE.FINISHED }),
        // range {0,0} の部分実行: entry 0 のみ done、entry 1 は未実行のまま（per-entry 状態の引き継ぎ）
        itemStates: ["done", "idle"],
        playlistName: "pl",
      }),
      timestamp: expect.any(Number),
    });
    // 退避の完了を待ってからリロードを予約する（逆順だとリロードが write を巻き添えに殺しうる）
    expect(scheduleRunCompleteReloadMock).toHaveBeenCalledTimes(1);
    expect(writeFinishedSnapshotMock.mock.invocationCallOrder[0]).toBeLessThan(
      scheduleRunCompleteReloadMock.mock.invocationCallOrder[0],
    );
  });

  it("Given snapshot 退避が失敗 When FINISHED Then リロードを見送る（in-memory snapshot を生かして復元性を守る）", async () => {
    const { runHandler, progressMessages, scheduleRunCompleteReloadMock } = await loadContentScript(
      ["clip-1", "clip-2"],
      { writeFinishedSnapshotError: new Error("storage down") },
    );

    runHandler({ data: partialRunPayload() });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(progressMessages).not.toContainEqual(expect.objectContaining({ phase: PHASE.ERROR }));
    expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
  });

  it("Given retryPlaylist が完走 When FINISHED Then 退避してからリロードを予約する", async () => {
    const { handlers, progressMessages, writeFinishedSnapshotMock, scheduleRunCompleteReloadMock } =
      await loadContentScript([]);

    handlers.get("retryPlaylist")!({
      data: {
        playlistName: "pl",
        submittedClipIds: ["clip-1", "clip-2"],
        expectedClipCount: 2,
        collectionId: "coll-1",
        shouldDownload: false,
      },
    });

    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));
    expect(writeFinishedSnapshotMock).toHaveBeenCalledWith(
      expect.objectContaining({
        snapshot: expect.objectContaining({ collectionId: "coll-1" }),
        timestamp: expect.any(Number),
      }),
    );
    expect(scheduleRunCompleteReloadMock).toHaveBeenCalledTimes(1);
    expect(writeFinishedSnapshotMock.mock.invocationCallOrder[0]).toBeLessThan(
      scheduleRunCompleteReloadMock.mock.invocationCallOrder[0],
    );
  });
});

describe("content.ts 実行開始時の退避 snapshot 消去", () => {
  it("Given run 受理 When initSnapshot Then 直近完了 run の退避 snapshot を消去する", async () => {
    const { runHandler, clearFinishedSnapshotMock } = await loadContentScript([]);

    runHandler({ data: partialRunPayload() });

    expect(clearFinishedSnapshotMock).toHaveBeenCalledTimes(1);
  });

  it("Given retryPlaylist 受理 When initSnapshot Then 退避 snapshot を消去する", async () => {
    const { handlers, clearFinishedSnapshotMock } = await loadContentScript([]);

    handlers.get("retryPlaylist")!({
      data: { playlistName: "pl", submittedClipIds: ["clip-1"], expectedClipCount: 1, collectionId: "coll-1" },
    });

    // 消去は initSnapshot 直後に同期で発火する（完了を待つ必要はない）
    expect(clearFinishedSnapshotMock).toHaveBeenCalledTimes(1);
  });

  it("Given retryDownload 受理 When initSnapshot Then 退避 snapshot を消去する", async () => {
    const { handlers, clearFinishedSnapshotMock } = await loadContentScript([]);

    handlers.get("retryDownload")!({
      data: { collectionId: "coll-1", playlistName: "pl", submittedClipIds: ["clip-1"] },
    });

    expect(clearFinishedSnapshotMock).toHaveBeenCalledTimes(1);
  });
});

describe('content.ts onMessage("queryProgress"): 退避 snapshot への fallback', () => {
  it("Given run 実行済み（in-memory snapshot あり）When queryProgress Then in-memory を返し storage は読まない", async () => {
    const { handlers, runHandler, progressMessages, readFreshFinishedSnapshotMock } = await loadContentScript([
      "clip-1",
      "clip-2",
    ]);

    runHandler({ data: partialRunPayload() });
    await vi.waitFor(() => expect(progressMessages).toContainEqual(expect.objectContaining({ phase: PHASE.FINISHED })));

    const snapshot = (await handlers.get("queryProgress")!({})) as SnapshotPayload | null;

    expect(snapshot).toMatchObject({ isRunning: false, progress: { phase: PHASE.FINISHED } });
    expect(readFreshFinishedSnapshotMock).not.toHaveBeenCalled();
  });

  it("Given run 未実行 + 退避 snapshot あり（リロード直後）When queryProgress Then 退避分を返す", async () => {
    const persisted: SnapshotPayload = {
      collectionId: "collection-a",
      entries: makePromptEntries(2),
      itemStates: ["done", "done"],
      isRunning: false,
      progress: { phase: PHASE.FINISHED, total: 2 },
      playlistName: "pl",
    };
    const { handlers, readFreshFinishedSnapshotMock } = await loadContentScript([], {
      persistedFinishedSnapshot: persisted,
    });

    const snapshot = (await handlers.get("queryProgress")!({})) as SnapshotPayload | null;

    expect(snapshot).toEqual(persisted);
    // stale 判定の基準 now を渡している（判定自体は readFreshFinishedSnapshot 側の契約）
    expect(readFreshFinishedSnapshotMock).toHaveBeenCalledWith(expect.any(Number));
  });

  it("Given run 未実行 + 退避も無し When queryProgress Then null（buildRestoreState が従来表示へフォールバック）", async () => {
    const { handlers } = await loadContentScript([]);

    const snapshot = (await handlers.get("queryProgress")!({})) as SnapshotPayload | null;

    expect(snapshot).toBeNull();
  });
});
