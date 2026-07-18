// Queue mode の生成完了待ち stall タイムアウト時の graceful degradation (#1994)。
// waitForSubmittedClipsComplete を timedOut 結果で返すよう mock し、runAll が
// 一部 stall / 全 stall / serial stall / 全完了 の各経路で期待どおり分岐することを検証する。
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PromptEntry } from "../../shared/api";
import { PHASE } from "../../shared/constants";
import type { SubmittedClipCompletionResult } from "../lib/queue-runner";
import type { ResumeState } from "../lib/resume-state";

interface RunPayload {
  entries: PromptEntry[];
  playlistName: string;
  runMode?: "serial" | "queue";
  regenerateDurationOutliers?: boolean;
  collectionId: string;
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

async function loadContentScriptWithStalledCompletion(options: {
  initialSubmittedIds: string[];
  clipIdsByEntry: Map<number, string[]>;
  completionResult: SubmittedClipCompletionResult;
}) {
  vi.resetModules();
  vi.stubGlobal(
    "defineContentScript",
    (definition: { main: () => void }) => definition
  );

  const handlers = new Map<string, Handler>();
  const progressMessages: ProgressMessage[] = [];
  const sentMessages: Array<{ type: string; payload: unknown }> = [];
  let lastMultiSelectIds: string[] = [];
  // oxlint-disable-next-line no-unused-vars
  const scrollAndMultiSelectByIdsMock = vi.fn(
    (ids: string[], _options: unknown) => {
      lastMultiSelectIds = ids;
      return Promise.resolve(ids.length);
    }
  );
  const readSelectedClipIdsMock = vi.fn(() =>
    Promise.resolve(lastMultiSelectIds)
  );
  const scheduleRunCompleteReloadMock = vi.fn();

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
        // download watcher の完了イベントを模擬する（実物は background からの downloadComplete 中継）。
        setTimeout(() => {
          handlers.get("downloadComplete")?.({
            data: { filename: "collection.zip" },
          });
        }, 0);
        return Promise.resolve({ ok: true });
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
  }));

  vi.doMock("../lib/snapshot", () => ({
    initSnapshot: vi.fn(
      (
        entries: PromptEntry[],
        initOptions: { collectionId: string; playlistName?: string }
      ) => ({
        collectionId: initOptions.collectionId,
        entries,
        playlistName: initOptions.playlistName,
        itemStates: entries.map(() => "pending"),
        isRunning: true,
        submittedClipIds: [],
      })
    ),
    applyProgress: vi.fn((snapshot: object, payload: object) => ({
      ...snapshot,
      progress: payload,
    })),
  }));

  vi.doMock("../lib/bridge-listener", () => ({
    attachBridgeListener: vi.fn(),
    createFeedPoller: vi.fn(() => ({ start: vi.fn(), stop: vi.fn() })),
    requestFeedPoll: vi.fn(async () => []),
    requestSliderSet: vi.fn(),
  }));

  // 状態を持つ tracker mock。dropSubmittedIds で stalled entry の clip が実際に除外されないと
  // playlist 追加の期待件数照合 (resolvePlaylistClipIds の fail-loud) を通過できない。
  let submittedIds = [...options.initialSubmittedIds];
  vi.doMock("../lib/clip-tracker", () => ({
    createClipTracker: vi.fn(() => ({
      clearSubmittedIds: vi.fn(() => {
        submittedIds = [...options.initialSubmittedIds];
      }),
      getSubmittedIds: vi.fn(() => [...submittedIds]),
      getPendingSubmittedIds: vi.fn(() => []),
      getPendingIdsByIds: vi.fn(() => []),
      getDuration: vi.fn(() => 120),
      dropSubmittedIds: vi.fn((ids: string[]) => {
        const dropSet = new Set(ids);
        submittedIds = submittedIds.filter((id) => !dropSet.has(id));
      }),
      markAccepted: vi.fn(),
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
    LyricsPasteReflectionError: class LyricsPasteReflectionError extends Error {},
    POLL_INTERVAL_MS: 1,
    SETTLE_MS: 0,
    getInFlightClipCount: vi.fn(() => 0),
    injectAdvancedFields: vi.fn(() => Promise.resolve()),
    resolveAdvancedFields: vi.fn(() => ({})),
    resolveFields: vi.fn(() => ({
      style: {} as HTMLTextAreaElement,
      lyrics: null,
      title: null,
    })),
    resolveGenerateButton: vi.fn(
      () => ({ click: vi.fn() }) as unknown as HTMLButtonElement
    ),
    setLyricsValue: vi.fn(() => Promise.resolve()),
    setLyricsValueViaBeforeInput: vi.fn(() => Promise.resolve()),
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
    openAddToPlaylistDialogViaCmdP: vi.fn(() =>
      Promise.resolve({} as HTMLElement)
    ),
    readSelectedClipIds: readSelectedClipIdsMock,
    scrollAndMultiSelectByIds: scrollAndMultiSelectByIdsMock,
    waitForPlaylistDialogClose: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../lib/page-reload", () => ({
    scheduleRunCompleteReload: scheduleRunCompleteReloadMock,
    cancelScheduledRunCompleteReload: vi.fn(),
  }));

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

  vi.doMock("../lib/storage", () => ({
    serverUrlItem: {
      getValue: vi.fn(() => Promise.resolve("http://localhost:8787")),
    },
    downloadFormatItem: { getValue: vi.fn(() => Promise.resolve("mp3")) },
    readDownloadFormat: vi.fn(() => Promise.resolve("mp3")),
  }));

  vi.doMock("../lib/download", () => ({
    triggerDownloadAll: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../../shared/api", async () => ({
    ...(await vi.importActual<typeof import("../../shared/api")>(
      "../../shared/api"
    )),
    postDownloaded: vi.fn(() => Promise.resolve()),
  }));

  // 投入フェーズと完了待ちのみ mock し、entryDisplayName / finalizeQueueEntriesYield /
  // resolveStalledQueueEntries は実物で degradation の分岐を検証する。
  vi.doMock("../lib/queue-runner", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../lib/queue-runner")>();
    return {
      ...actual,
      submitQueueEntries: vi.fn(() =>
        Promise.resolve({
          completed: true,
          failedIndices: [],
          clipIdsByEntry: options.clipIdsByEntry,
        })
      ),
      waitForSubmittedClipsComplete: vi.fn(() =>
        Promise.resolve(options.completionResult)
      ),
    };
  });

  const content = await import("../entrypoints/content");
  content.default.main(
    {} as NonNullable<Parameters<typeof content.default.main>[0]>
  );

  const runHandler = handlers.get("run") as RunHandler | undefined;
  if (!runHandler) {
    throw new Error("run message handler was not registered");
  }
  return {
    progressMessages,
    sentMessages,
    scrollAndMultiSelectByIdsMock,
    scheduleRunCompleteReloadMock,
    runHandler,
  };
}

const entries: PromptEntry[] = [
  { name: "track-1", style: "style 1", lyrics: "" },
  { name: "track-2", style: "style 2", lyrics: "" },
  { name: "track-3", style: "style 3", lyrics: "" },
];

const clipIdsByEntry = new Map<number, string[]>([
  [0, ["clip-0a", "clip-0b"]],
  [1, ["clip-1a", "clip-1b"]],
  [2, ["clip-2a", "clip-2b"]],
]);

const allClipIds = Array.from(clipIdsByEntry.values()).flat();

function runQueue(
  runHandler: RunHandler,
  runMode: "serial" | "queue" = "queue"
): void {
  runHandler({
    data: {
      entries,
      playlistName: "vj | stall regression",
      collectionId: "collection-stall",
      runMode,
      regenerateDurationOutliers: false,
    },
  });
}

describe("content.ts queue mode stall graceful degradation (#1994)", () => {
  beforeEach(() => {
    writeResumeStateMock.mockReset();
    clearResumeStateForCollectionMock.mockReset();
  });

  it("Given 一部 entry の clip が stall When queue run Then 停滞 entry を失敗記録し完了分で playlist 追加とダウンロードを続行する", async () => {
    const {
      progressMessages,
      sentMessages,
      scrollAndMultiSelectByIdsMock,
      scheduleRunCompleteReloadMock,
      runHandler,
    } = await loadContentScriptWithStalledCompletion({
      initialSubmittedIds: allClipIds,
      clipIdsByEntry: new Map(clipIdsByEntry),
      completionResult: {
        timedOut: true,
        submittedIds: allClipIds,
        stalledClipIds: ["clip-1b"],
        message:
          "生成完了待ちがタイムアウトしました: submitted=6/6, pending=1, 最後の進捗からの経過時間=600000ms",
      },
    });

    runQueue(runHandler);
    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({ phase: PHASE.FINISHED })
      )
    );

    // stall した entry 1 は ENTRY_FAILED として明示され、playlist 追加は完了分のみで実行される。
    expect(progressMessages).toContainEqual(
      expect.objectContaining({ phase: PHASE.ENTRY_FAILED, index: 1 })
    );
    expect(scrollAndMultiSelectByIdsMock).toHaveBeenCalledWith(
      ["clip-0a", "clip-0b", "clip-2a", "clip-2b"],
      expect.anything()
    );
    expect(sentMessages).toContainEqual(
      expect.objectContaining({ type: "startDownload" })
    );
    const finished = progressMessages.find(
      (message) => message.phase === PHASE.FINISHED
    );
    expect(finished?.message).toContain("生成停滞");
    expect(finished?.message).toContain("失敗分のみ再実行");
    // stalled entry は resume/retry 導線の入力として保持され、resume state は消去されない。
    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({ failedIndices: [1] })
    );
    expect(clearResumeStateForCollectionMock).not.toHaveBeenCalled();
    expect(scheduleRunCompleteReloadMock).not.toHaveBeenCalled();
  });

  it("Given 全 entry の clip が stall When queue run Then playlist 追加せず失敗保留の FINISHED で再実行導線へ委ねる", async () => {
    const { progressMessages, scrollAndMultiSelectByIdsMock, runHandler } =
      await loadContentScriptWithStalledCompletion({
        initialSubmittedIds: allClipIds,
        clipIdsByEntry: new Map(clipIdsByEntry),
        completionResult: {
          timedOut: true,
          submittedIds: allClipIds,
          stalledClipIds: allClipIds,
          message:
            "生成完了待ちがタイムアウトしました: submitted=6/6, pending=6, 最後の進捗からの経過時間=600000ms",
        },
      });

    runQueue(runHandler);
    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({ phase: PHASE.FINISHED })
      )
    );

    expect(scrollAndMultiSelectByIdsMock).not.toHaveBeenCalled();
    const finished = progressMessages.find(
      (message) => message.phase === PHASE.FINISHED
    );
    expect(finished?.message).toContain(
      "「失敗分のみ再実行」で完走後に playlist 追加が実行されます"
    );
    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({ failedIndices: [0, 1, 2] })
    );
  });

  it("Given serial run で完了待ちが stall When run Then 従来どおり ERROR で中断する", async () => {
    const stallMessage =
      "生成完了待ちがタイムアウトしました: submitted=6/6, pending=1, 最後の進捗からの経過時間=600000ms";
    const { progressMessages, scrollAndMultiSelectByIdsMock, runHandler } =
      await loadContentScriptWithStalledCompletion({
        initialSubmittedIds: allClipIds,
        clipIdsByEntry: new Map(clipIdsByEntry),
        completionResult: {
          timedOut: true,
          submittedIds: allClipIds,
          stalledClipIds: ["clip-1b"],
          message: stallMessage,
        },
      });

    runQueue(runHandler, "serial");
    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({ phase: PHASE.ERROR })
      )
    );

    expect(progressMessages).toContainEqual(
      expect.objectContaining({
        phase: PHASE.ERROR,
        index: entries.length,
        message: stallMessage,
      })
    );
    expect(scrollAndMultiSelectByIdsMock).not.toHaveBeenCalled();
  });

  it("Given 全 clip が完了 When queue run Then 従来どおり playlist 追加と resume state 消去まで完走する", async () => {
    const { progressMessages, scrollAndMultiSelectByIdsMock, runHandler } =
      await loadContentScriptWithStalledCompletion({
        initialSubmittedIds: allClipIds,
        clipIdsByEntry: new Map(clipIdsByEntry),
        completionResult: {
          timedOut: false,
          submittedIds: allClipIds,
          stalledClipIds: [],
        },
      });

    runQueue(runHandler);
    await vi.waitFor(() =>
      expect(progressMessages).toContainEqual(
        expect.objectContaining({ phase: PHASE.FINISHED })
      )
    );

    expect(scrollAndMultiSelectByIdsMock).toHaveBeenCalledWith(
      allClipIds,
      expect.anything()
    );
    expect(progressMessages).not.toContainEqual(
      expect.objectContaining({ phase: PHASE.ENTRY_FAILED })
    );
    expect(clearResumeStateForCollectionMock).toHaveBeenCalled();
  });
});
