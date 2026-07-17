// lib/queue-runner (#1586) の production ロジック回帰テスト。
//
// 元は tests/e2e/suno-queue.spec.ts に同居していたが、これらは page（実ブラウザ DOM）を
// 一切使わない純ロジックテストであり、Playwright 経由だと lib/queue-runner →
// shared/constants の transitive import が package.json スコープ外（extensions/shared）で
// CJS 判定され ESM named import が壊れる（CI 再現）。責務どおり vitest へ移設した。
// 実ブラウザ layout 上の queue 監視スモークは引き続き e2e (suno-queue.spec.ts) が担う。
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PromptEntry } from "../../shared/api";
import {
  CLIPS_PER_REQUEST,
  INFLIGHT_STALL_TIMEOUT_MS,
  MAX_INFLIGHT_REQUESTS,
  PHASE,
} from "../../shared/constants";
import {
  finalizeQueueEntriesYield,
  submitQueueEntries,
  waitForSubmittedClipsComplete,
} from "../lib/queue-runner";
import type {
  QueueSubmissionOptions,
  SubmittedClipCompletionOptions,
} from "../lib/queue-runner";
import { buildRunPayload } from "../lib/run-overrides";

function makePromptEntries(count: number): PromptEntry[] {
  return Array.from({ length: count }, (_, i) => ({
    name: `queue-entry-${i + 1}`,
    style: `style ${i + 1}`,
    lyrics: `lyrics ${i + 1}`,
  }));
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function makeQueueSubmissionOptions(input: {
  entries: PromptEntry[];
  submittedIndexes: number[];
  submittedClipIds: string[];
  waitForQueueSlot?: QueueSubmissionOptions["waitForQueueSlot"];
}): QueueSubmissionOptions {
  const waitForQueueSlot = input.waitForQueueSlot ?? (async () => {});
  return {
    entries: input.entries,
    order: input.entries.map((_, i) => i),
    total: input.entries.length,
    maxGeneratingClips: MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST,
    preset: {
      interCreateDelayMs: 0,
      jitterMs: 0,
      maxInjectRetry: 0,
      injectAckTimeoutMs: 50,
      maxEntryRetry: 0,
    },
    isAborted: () => false,
    isEntrySubmitted: (index) => input.submittedIndexes.includes(index),
    getSubmittedIds: () => [...input.submittedClipIds],
    getSubmissionCount: () => input.submittedIndexes.length,
    getDomInFlightCount: () => input.submittedClipIds.length,
    hasObservedAnyTraffic: () => true,
    getLastChangeAt: () => Date.now(),
    currentInFlightCount: () => input.submittedClipIds.length,
    emitProgress: () => {},
    submitEntryToQueue: async (_entry, index) => {
      input.submittedIndexes.push(index);
      input.submittedClipIds.push(`clip-${index}-a`, `clip-${index}-b`);
    },
    waitForAck: async () => true,
    waitForQueueSlot,
    persistInterruptState: () => {
      throw new Error(
        "interrupt state should not be persisted in the happy-path test"
      );
    },
    applyJitter: (baseMs) => baseMs,
    abortableSleep: async () => {},
    sleep: async () => {},
  };
}

function mapEntries(map: Map<number, string[]>): Array<[number, string[]]> {
  return Array.from(map.entries());
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("queue-runner: production ロジック (#1586)", () => {
  it("production payload と queue runner は queue mode で生成完了待ちなしに次 entry を投入する", async () => {
    const entries = makePromptEntries(2);
    const payload = buildRunPayload({
      entries,
      playlistName: "Queue Smoke",
      range: undefined,
      collectionId: "queue-smoke",
      runMode: "queue",
      overrides: undefined,
    });
    const submittedIndexes: number[] = [];
    const submittedClipIds: string[] = [];
    const progress: string[] = [];
    const options = makeQueueSubmissionOptions({
      entries,
      submittedIndexes,
      submittedClipIds,
    });
    options.emitProgress = (value) => {
      if (value.phase === PHASE.SUBMITTED) {
        progress.push(`${value.phase}:${value.index}`);
      }
    };

    const result = await submitQueueEntries(options);

    expect(payload.runMode).toBe("queue");
    expect(result.completed).toBe(true);
    expect(result.failedIndices).toEqual([]);
    expect(mapEntries(result.clipIdsByEntry)).toEqual([
      [0, ["clip-0-a", "clip-0-b"]],
      [1, ["clip-1-a", "clip-1-b"]],
    ]);
    expect(submittedIndexes).toEqual([0, 1]);
    expect(submittedClipIds).toEqual([
      "clip-0-a",
      "clip-0-b",
      "clip-1-a",
      "clip-1-b",
    ]);
    expect(progress).toEqual([`${PHASE.SUBMITTED}:0`, `${PHASE.SUBMITTED}:1`]);
  });

  it("Given getSubmittedIds が suffix 順を保証しない When queue entry を投入する Then 投入前後の Set 差分で mapping する", async () => {
    const entries = makePromptEntries(2);
    const submittedIndexes: number[] = [];
    const submittedClipIds: string[] = [];
    const options = makeQueueSubmissionOptions({
      entries,
      submittedIndexes,
      submittedClipIds,
    });
    options.getSubmittedIds = () => [...submittedClipIds].sort();
    options.submitEntryToQueue = async (_entry, index) => {
      submittedIndexes.push(index);
      if (index === 0) {
        submittedClipIds.push("clip-z-a", "clip-z-b");
        return;
      }
      submittedClipIds.push("clip-a-a", "clip-a-b");
    };

    const result = await submitQueueEntries(options);

    expect(result.completed).toBe(true);
    expect(result.failedIndices).toEqual([]);
    expect(mapEntries(result.clipIdsByEntry)).toEqual([
      [0, ["clip-z-a", "clip-z-b"]],
      [1, ["clip-a-a", "clip-a-b"]],
    ]);
  });

  it("Given 1回目の ACK 失敗後に clip ID が遅延観測される When entry retry が成功する Then retry attempt 分も同じ entry に帰属する", async () => {
    const entries = makePromptEntries(1);
    const submittedIndexes: number[] = [];
    const submittedClipIds: string[] = [];
    const options = makeQueueSubmissionOptions({
      entries,
      submittedIndexes,
      submittedClipIds,
    });
    options.preset = { ...options.preset, maxEntryRetry: 1 };
    options.waitForAck = vi
      .fn<QueueSubmissionOptions["waitForAck"]>()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true);
    options.submitEntryToQueue = async (_entry, index) => {
      submittedIndexes.push(index);
      if (submittedIndexes.length === 2) {
        submittedClipIds.push("clip-retry-a", "clip-retry-b");
      }
    };
    options.abortableSleep = async () => {
      submittedClipIds.push("clip-delayed-a", "clip-delayed-b");
    };

    const result = await submitQueueEntries(options);

    expect(result.completed).toBe(true);
    expect(result.failedIndices).toEqual([]);
    expect(submittedIndexes).toEqual([0, 0]);
    expect(mapEntries(result.clipIdsByEntry)).toEqual([
      [0, ["clip-delayed-a", "clip-delayed-b", "clip-retry-a", "clip-retry-b"]],
    ]);
  });

  it("production queue runner は 10 request cap 到達中に 11 件目を投入しない", async () => {
    const entries = makePromptEntries(MAX_INFLIGHT_REQUESTS + 1);
    const submittedIndexes: number[] = [];
    const submittedClipIds: string[] = [];
    const eleventhSlot = deferred();
    const maxGeneratingClipArgs: number[] = [];
    const waitForQueueSlot: QueueSubmissionOptions["waitForQueueSlot"] = async (
      maxGeneratingClips
    ) => {
      maxGeneratingClipArgs.push(maxGeneratingClips);
      if (maxGeneratingClipArgs.length === MAX_INFLIGHT_REQUESTS + 1) {
        await eleventhSlot.promise;
      }
    };
    const options = makeQueueSubmissionOptions({
      entries,
      submittedIndexes,
      submittedClipIds,
      waitForQueueSlot,
    });

    const pending = submitQueueEntries(options);

    await vi.waitFor(() =>
      expect(maxGeneratingClipArgs.length).toBe(MAX_INFLIGHT_REQUESTS + 1)
    );
    expect(maxGeneratingClipArgs).toEqual(
      Array.from(
        { length: MAX_INFLIGHT_REQUESTS + 1 },
        () => MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST
      )
    );
    expect(submittedIndexes).toEqual(
      Array.from({ length: MAX_INFLIGHT_REQUESTS }, (_, i) => i)
    );

    eleventhSlot.resolve();
    const result = await pending;
    expect(result.completed).toBe(true);
    expect(result.failedIndices).toEqual([]);
    expect(mapEntries(result.clipIdsByEntry)).toEqual(
      Array.from({ length: MAX_INFLIGHT_REQUESTS + 1 }, (_, i) => [
        i,
        [`clip-${i}-a`, `clip-${i}-b`],
      ])
    );
    expect(submittedIndexes).toEqual(
      Array.from({ length: MAX_INFLIGHT_REQUESTS + 1 }, (_, i) => i)
    );
  });

  it("Given queue finalizer と全 clip が duration filter 内 When entry を確定する Then acceptedClipIds 付き DONE を emit する", async () => {
    const entries = makePromptEntries(1);
    const emitProgress = vi.fn();
    const markAccepted = vi.fn();
    const dropSubmittedIds = vi.fn();

    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: entries.length,
      clipIdsByEntry: new Map([[0, ["clip-ok-a", "clip-ok-b"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry: vi.fn(async () => []),
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: (clipId: string) => {
        const durations: Record<string, number> = {
          "clip-ok-a": 120,
          "clip-ok-b": 180,
        };
        return durations[clipId];
      },
      markAccepted,
      dropSubmittedIds,
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [] });
    expect(markAccepted).toHaveBeenCalledWith(["clip-ok-a", "clip-ok-b"]);
    expect(dropSubmittedIds).not.toHaveBeenCalled();
    expect(emitProgress).toHaveBeenCalledWith({
      phase: PHASE.DONE,
      index: 0,
      total: entries.length,
      yieldRetryCount: 0,
      acceptedClipIds: ["clip-ok-a", "clip-ok-b"],
    });
  });

  it("Given queue finalizer と全 clip が duration filter 外 When entry を確定する Then ENTRY_FAILED と failedIndices を返す", async () => {
    const entries = makePromptEntries(2);
    const emitProgress = vi.fn();
    const markAccepted = vi.fn();
    const dropSubmittedIds = vi.fn();

    const regenerateEntry = vi
      .fn<(index: number, attempt: number) => Promise<string[]>>()
      .mockResolvedValue(["clip-ng-a", "clip-ng-b"]);
    const result = await finalizeQueueEntriesYield({
      entries,
      order: [1],
      total: entries.length,
      clipIdsByEntry: new Map([[1, ["clip-ng-a", "clip-ng-b"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry,
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: (clipId: string) => {
        const durations: Record<string, number> = {
          "clip-ng-a": 45,
          "clip-ng-b": 360,
        };
        return durations[clipId];
      },
      markAccepted,
      dropSubmittedIds,
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [1] });
    expect(markAccepted).not.toHaveBeenCalled();
    expect(dropSubmittedIds).toHaveBeenCalledWith(["clip-ng-a", "clip-ng-b"]);
    expect(emitProgress).toHaveBeenCalledWith({
      phase: PHASE.ENTRY_FAILED,
      index: 1,
      total: entries.length,
      message: "duration guard NG (75-240s): clip-ng-a, clip-ng-b",
      yieldRetryCount: 2,
      log: { kind: "skip", entryName: "queue-entry-2" },
    });
  });

  it("Given option ON と初回全NG When 再生成がOKを返す Then 同じentryを再生成してDONEにする", async () => {
    const entries = makePromptEntries(1);
    const emitProgress = vi.fn();
    const markAccepted = vi.fn();
    const dropSubmittedIds = vi.fn();
    const regenerateEntry = vi.fn(async () => ["clip-retry-a", "clip-retry-b"]);
    const durations: Record<string, number> = {
      "clip-ng-a": 45,
      "clip-ng-b": 360,
      "clip-retry-a": 120,
      "clip-retry-b": 180,
    };

    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: 1,
      clipIdsByEntry: new Map([[0, ["clip-ng-a", "clip-ng-b"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry,
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: (id) => durations[id],
      markAccepted,
      dropSubmittedIds,
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [] });
    expect(regenerateEntry).toHaveBeenCalledTimes(1);
    expect(regenerateEntry).toHaveBeenCalledWith(0, 1);
    expect(dropSubmittedIds).toHaveBeenCalledWith(["clip-ng-a", "clip-ng-b"]);
    expect(markAccepted).toHaveBeenCalledWith(["clip-retry-a", "clip-retry-b"]);
    expect(emitProgress).toHaveBeenCalledWith(
      expect.objectContaining({
        phase: PHASE.WAITING_SLOT,
        index: 0,
        yieldRetryCount: 1,
      })
    );
  });

  it("Given option ON と全attempt全NG When 上限まで再生成する Then 2回でENTRY_FAILEDにする", async () => {
    const entries = makePromptEntries(1);
    const emitProgress = vi.fn();
    const regenerateEntry = vi
      .fn<(index: number, attempt: number) => Promise<string[]>>()
      .mockResolvedValueOnce(["clip-ng-1-a", "clip-ng-1-b"])
      .mockResolvedValueOnce(["clip-ng-2-a", "clip-ng-2-b"]);

    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: 1,
      clipIdsByEntry: new Map([[0, ["clip-ng-0-a", "clip-ng-0-b"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry,
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: () => 45,
      markAccepted: vi.fn(),
      dropSubmittedIds: vi.fn(),
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [0] });
    expect(regenerateEntry).toHaveBeenCalledTimes(2);
    expect(emitProgress).toHaveBeenLastCalledWith(
      expect.objectContaining({
        phase: PHASE.ENTRY_FAILED,
        index: 0,
        yieldRetryCount: 2,
      })
    );
  });

  it("Given option ON の再生成処理がthrow When entryを確定する Then 成功扱いせずENTRY_FAILEDにする", async () => {
    const entries = makePromptEntries(1);
    const emitProgress = vi.fn();

    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: 1,
      clipIdsByEntry: new Map([[0, ["clip-ng-a", "clip-ng-b"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry: vi.fn(async () => {
          throw new Error("inject failed");
        }),
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: () => 45,
      markAccepted: vi.fn(),
      dropSubmittedIds: vi.fn(),
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [0] });
    expect(emitProgress).toHaveBeenLastCalledWith({
      phase: PHASE.ENTRY_FAILED,
      index: 0,
      total: 1,
      message: "inject failed",
      yieldRetryCount: 1,
      log: { kind: "skip", entryName: "queue-entry-1" },
    });
  });

  it("Given option OFF と全clip NG When entryを確定する Then 再生成せず全clipを採用候補に残す", async () => {
    const entries = makePromptEntries(1);
    const emitProgress = vi.fn();
    const markAccepted = vi.fn();
    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: 1,
      clipIdsByEntry: new Map([[0, ["clip-ng-a", "clip-ng-b"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: { kind: "retain" },
      getDuration: () => 45,
      markAccepted,
      dropSubmittedIds: vi.fn(),
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [] });
    expect(markAccepted).toHaveBeenCalledWith(["clip-ng-a", "clip-ng-b"]);
    expect(emitProgress).toHaveBeenLastCalledWith(
      expect.objectContaining({
        phase: PHASE.DONE,
        acceptedClipIds: ["clip-ng-a", "clip-ng-b"],
        message: expect.stringContaining("再生成 OFF"),
        durationOutlierWarning: expect.stringContaining("再生成 OFF"),
      })
    );
  });

  it("Given queue 再生成の投入直後にstop When finalizerを確定する Then retry clipを除去して中断indexを返す", async () => {
    const isAborted = vi.fn(() => true);
    const dropSubmittedIds = vi.fn();

    const result = await finalizeQueueEntriesYield({
      entries: makePromptEntries(1),
      order: [0],
      total: 1,
      clipIdsByEntry: new Map([[0, ["clip-ng-a", "clip-ng-b"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry: vi.fn(async () => ["clip-retry-a", "clip-retry-b"]),
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      isAborted,
      getDuration: () => 45,
      markAccepted: vi.fn(),
      dropSubmittedIds,
      emitProgress: vi.fn(),
    });

    expect(result).toEqual({ failedIndices: [], abortedIndex: 0 });
    expect(dropSubmittedIds).toHaveBeenCalledOnce();
    expect(dropSubmittedIds).toHaveBeenCalledWith([
      "clip-retry-a",
      "clip-retry-b",
    ]);
  });

  it("Given option OFF とOK/NG混在 When entryを確定する Then NGをdropせず全clipを採用候補に残す", async () => {
    const entries = makePromptEntries(1);
    const markAccepted = vi.fn();
    const durations: Record<string, number> = { "clip-ok": 180, "clip-ng": 45 };

    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: 1,
      clipIdsByEntry: new Map([[0, ["clip-ok", "clip-ng"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: { kind: "retain" },
      getDuration: (id) => durations[id],
      markAccepted,
      dropSubmittedIds: vi.fn(),
      emitProgress: vi.fn(),
    });

    expect(result).toEqual({ failedIndices: [] });
    expect(markAccepted).toHaveBeenCalledWith(["clip-ok", "clip-ng"]);
  });

  it("Given queue duration評価が失敗 When option ONで確定する Then 上限までretryしてENTRY_FAILEDにする", async () => {
    const emitProgress = vi.fn();
    const regenerateEntry = vi.fn(async () => ["clip-retry"]);

    const result = await finalizeQueueEntriesYield({
      entries: makePromptEntries(1),
      order: [0],
      total: 1,
      clipIdsByEntry: new Map([[0, ["clip-original"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry,
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: () => {
        throw new Error("feed unavailable");
      },
      markAccepted: vi.fn(),
      dropSubmittedIds: vi.fn(),
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [0] });
    expect(regenerateEntry).toHaveBeenCalledTimes(2);
    expect(emitProgress).toHaveBeenLastCalledWith(
      expect.objectContaining({
        phase: PHASE.ENTRY_FAILED,
        message: "feed unavailable",
        yieldRetryCount: 2,
      })
    );
  });

  it("Given queue finalizer と一部 clip だけが duration filter 内 When entry を確定する Then OK clip だけ accepted にして DONE にする", async () => {
    const entries = makePromptEntries(1);
    const emitProgress = vi.fn();
    const markAccepted = vi.fn();
    const dropSubmittedIds = vi.fn();

    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: entries.length,
      clipIdsByEntry: new Map([[0, ["clip-partial-ok", "clip-partial-ng"]]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry: vi.fn(async () => []),
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: (clipId: string) => {
        const durations: Record<string, number> = {
          "clip-partial-ok": 180,
          "clip-partial-ng": 45,
        };
        return durations[clipId];
      },
      markAccepted,
      dropSubmittedIds,
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [] });
    expect(markAccepted).toHaveBeenCalledWith(["clip-partial-ok"]);
    expect(dropSubmittedIds).not.toHaveBeenCalled();
    expect(emitProgress).toHaveBeenCalledWith({
      phase: PHASE.DONE,
      index: 0,
      total: entries.length,
      yieldRetryCount: 0,
      acceptedClipIds: ["clip-partial-ok"],
    });
  });

  it("Given queue finalizer と entry の clip ID mapping が空 When entry を確定する Then warn して DONE に縮退する", async () => {
    const entries = makePromptEntries(1);
    const emitProgress = vi.fn();
    const markAccepted = vi.fn();
    const dropSubmittedIds = vi.fn();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: entries.length,
      clipIdsByEntry: new Map([[0, []]]),
      durationFilter: { min_sec: 75, max_sec: 240 },
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry: vi.fn(async () => []),
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: () => {
        throw new Error("duration should not be read without clip IDs");
      },
      markAccepted,
      dropSubmittedIds,
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [] });
    expect(markAccepted).not.toHaveBeenCalled();
    expect(dropSubmittedIds).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledWith(
      "[suno-helper] entry 0 の clip ID を bridge で観測できなかったため duration guard を skip します。"
    );
    expect(emitProgress).toHaveBeenCalledWith({
      phase: PHASE.DONE,
      index: 0,
      total: entries.length,
      yieldRetryCount: 0,
    });
  });

  it("Given queue finalizer に durationFilter が未指定 When entry を確定する Then DEFAULT_DURATION_FILTER で検査する", async () => {
    const entries = makePromptEntries(1);
    const emitProgress = vi.fn();

    const result = await finalizeQueueEntriesYield({
      entries,
      order: [0],
      total: entries.length,
      clipIdsByEntry: new Map([[0, ["clip-short"]]]),
      durationOutlierStrategy: {
        kind: "regenerate",
        regenerateEntry: vi.fn(async () => ["clip-short"]),
        waitForRegeneratedClips: vi.fn(async () => {}),
      },
      getDuration: () => 45,
      markAccepted: vi.fn(),
      dropSubmittedIds: vi.fn(),
      emitProgress,
    });

    expect(result).toEqual({ failedIndices: [0] });
    expect(emitProgress).toHaveBeenCalledWith(
      expect.objectContaining({
        phase: PHASE.ENTRY_FAILED,
        index: 0,
        message: "duration guard NG (60-300s): clip-short",
      })
    );
  });

  it("production completion gate は resume 済み未完了 clip を playlist 前に feed poll 対象へ入れる", async () => {
    const previousSubmittedClipIds = ["previous-clip-a", "previous-clip-b"];
    const pendingClipIds = new Set(previousSubmittedClipIds);
    const feedPollStarted = deferred();
    const feedPollMayFinish = deferred();
    const feedPollRequests: string[][] = [];
    let playlistReached = false;
    const options: SubmittedClipCompletionOptions = {
      expectedClipCount: previousSubmittedClipIds.length,
      previousSubmittedClipIds,
      isAborted: () => false,
      getSubmittedIds: () => [],
      getPendingIdsByIds: (ids) => ids.filter((id) => pendingClipIds.has(id)),
      getPendingSubmittedIds: () => [],
      requestFeedPoll: async (ids) => {
        feedPollRequests.push([...ids]);
        feedPollStarted.resolve();
        await feedPollMayFinish.promise;
        pendingClipIds.clear();
      },
      abortableSleep: async () => {},
    };

    const pendingCompletion = waitForSubmittedClipsComplete(options).then(
      () => {
        playlistReached = true;
      }
    );

    await feedPollStarted.promise;
    expect(feedPollRequests).toEqual([previousSubmittedClipIds]);
    expect(playlistReached).toBe(false);

    feedPollMayFinish.resolve();
    await pendingCompletion;
    expect(playlistReached).toBe(true);
  });

  it("production completion gate は pending 減少時に stall deadline をリセットする", async () => {
    let currentTime = 0;
    const pendingClipIds = new Set(["clip-a", "clip-b"]);
    let pollCount = 0;
    const options: SubmittedClipCompletionOptions = {
      expectedClipCount: 2,
      previousSubmittedClipIds: [],
      isAborted: () => false,
      getSubmittedIds: () => ["clip-a", "clip-b"],
      getPendingIdsByIds: (ids) => ids.filter((id) => pendingClipIds.has(id)),
      getPendingSubmittedIds: () => Array.from(pendingClipIds),
      requestFeedPoll: async () => {
        pollCount += 1;
        if (pollCount === 1) {
          pendingClipIds.delete("clip-a");
        }
      },
      abortableSleep: async () => {
        currentTime += INFLIGHT_STALL_TIMEOUT_MS;
      },
      now: () => currentTime,
    };

    await expect(waitForSubmittedClipsComplete(options)).rejects.toThrow(
      `最後の進捗からの経過時間=${INFLIGHT_STALL_TIMEOUT_MS}ms`
    );
    expect(pollCount).toBe(2);
  });

  it("production completion gate は pending 増加時に stall deadline をリセットしない", async () => {
    let currentTime = 0;
    const pendingClipIds = new Set(["clip-a", "clip-b"]);
    let pollCount = 0;
    const options: SubmittedClipCompletionOptions = {
      expectedClipCount: 3,
      previousSubmittedClipIds: [],
      isAborted: () => false,
      getSubmittedIds: () => ["clip-a", "clip-b", "clip-c"],
      getPendingIdsByIds: (ids) => ids.filter((id) => pendingClipIds.has(id)),
      getPendingSubmittedIds: () => Array.from(pendingClipIds),
      requestFeedPoll: async () => {
        pollCount += 1;
        pendingClipIds.add("clip-c");
      },
      abortableSleep: async () => {
        currentTime += INFLIGHT_STALL_TIMEOUT_MS;
      },
      now: () => currentTime,
    };

    await expect(waitForSubmittedClipsComplete(options)).rejects.toThrow(
      `最後の進捗からの経過時間=${INFLIGHT_STALL_TIMEOUT_MS}ms`
    );
    expect(pollCount).toBe(1);
  });
});
