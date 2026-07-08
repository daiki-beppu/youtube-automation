// lib/queue-runner (#1586) の production ロジック回帰テスト。
//
// 元は tests/e2e/suno-queue.spec.ts に同居していたが、これらは page（実ブラウザ DOM）を
// 一切使わない純ロジックテストであり、Playwright 経由だと lib/queue-runner →
// shared/constants の transitive import が package.json スコープ外（extensions/shared）で
// CJS 判定され ESM named import が壊れる（CI 再現）。責務どおり vitest へ移設した。
// 実ブラウザ layout 上の queue 監視スモークは引き続き e2e (suno-queue.spec.ts) が担う。
import { describe, expect, it, vi } from "vitest";

import type { PromptEntry } from "../../shared/api";
import { CLIPS_PER_REQUEST, MAX_INFLIGHT_REQUESTS, PHASE } from "../../shared/constants";
import { submitQueueEntries, waitForSubmittedClipsComplete } from "../lib/queue-runner";
import type { QueueSubmissionOptions, SubmittedClipCompletionOptions } from "../lib/queue-runner";
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
      throw new Error("interrupt state should not be persisted in the happy-path test");
    },
    applyJitter: (baseMs) => baseMs,
    abortableSleep: async () => {},
    sleep: async () => {},
  };
}

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
    const options = makeQueueSubmissionOptions({ entries, submittedIndexes, submittedClipIds });
    options.emitProgress = (value) => {
      if (value.phase === PHASE.SUBMITTED) {
        progress.push(`${value.phase}:${value.index}`);
      }
    };

    const result = await submitQueueEntries(options);

    expect(payload.runMode).toBe("queue");
    expect(result).toEqual({ completed: true, failedIndices: [] });
    expect(submittedIndexes).toEqual([0, 1]);
    expect(submittedClipIds).toEqual(["clip-0-a", "clip-0-b", "clip-1-a", "clip-1-b"]);
    expect(progress).toEqual([`${PHASE.SUBMITTED}:0`, `${PHASE.SUBMITTED}:1`]);
  });

  it("production queue runner は 10 request cap 到達中に 11 件目を投入しない", async () => {
    const entries = makePromptEntries(MAX_INFLIGHT_REQUESTS + 1);
    const submittedIndexes: number[] = [];
    const submittedClipIds: string[] = [];
    const eleventhSlot = deferred();
    const maxGeneratingClipArgs: number[] = [];
    const waitForQueueSlot: QueueSubmissionOptions["waitForQueueSlot"] = async (maxGeneratingClips) => {
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

    await vi.waitFor(() => expect(maxGeneratingClipArgs.length).toBe(MAX_INFLIGHT_REQUESTS + 1));
    expect(maxGeneratingClipArgs).toEqual(
      Array.from({ length: MAX_INFLIGHT_REQUESTS + 1 }, () => MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST),
    );
    expect(submittedIndexes).toEqual(Array.from({ length: MAX_INFLIGHT_REQUESTS }, (_, i) => i));

    eleventhSlot.resolve();
    await expect(pending).resolves.toEqual({ completed: true, failedIndices: [] });
    expect(submittedIndexes).toEqual(Array.from({ length: MAX_INFLIGHT_REQUESTS + 1 }, (_, i) => i));
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

    const pendingCompletion = waitForSubmittedClipsComplete(options).then(() => {
      playlistReached = true;
    });

    await feedPollStarted.promise;
    expect(feedPollRequests).toEqual([previousSubmittedClipIds]);
    expect(playlistReached).toBe(false);

    feedPollMayFinish.resolve();
    await pendingCompletion;
    expect(playlistReached).toBe(true);
  });
});
