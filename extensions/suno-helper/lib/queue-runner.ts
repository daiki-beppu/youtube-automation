import type { PromptEntry } from "../../shared/api";
import {
  CLIPS_PER_REQUEST,
  INFLIGHT_STALL_TIMEOUT_MS,
  PHASE,
  type ProgressPayload,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
} from "../../shared/constants";
import { FatalRunError, POLL_INTERVAL_MS } from "../../shared/dom";
import type { AckMarker } from "./ack-probe";
import { markAck } from "./ack-probe";
import { InjectNotAcknowledgedError, SubmittedClipIdsNotObservedError, injectWithVerification } from "./inject-retry";
import { resolveInterruptIndex } from "./resume-state";
import { runEntryWithRetry } from "./entry-retry";

export interface QueueRunnerPreset {
  interCreateDelayMs: number;
  jitterMs: number;
  maxInjectRetry: number;
  injectAckTimeoutMs: number;
  maxEntryRetry: number;
}

export interface QueueSubmissionOptions {
  entries: PromptEntry[];
  order: number[];
  total: number;
  maxGeneratingClips: number;
  preset: QueueRunnerPreset;
  isAborted: () => boolean;
  /** 当該 entry の Generate を click 済みか（= content.ts の lastSubmittedEntryIndex === index）。 */
  isEntrySubmitted: (index: number) => boolean;
  getSubmittedIds: () => string[];
  getSubmissionCount: () => number;
  getDomInFlightCount: () => number;
  hasObservedAnyTraffic: () => boolean;
  getLastChangeAt: () => number;
  currentInFlightCount: () => number;
  emitProgress: (payload: ProgressPayload) => void;
  submitEntryToQueue: (entry: PromptEntry, index: number, total: number) => Promise<void>;
  waitForAck: (
    marker: AckMarker,
    opts: { isAborted: () => boolean; pollIntervalMs: number; timeoutMs: number },
  ) => Promise<boolean>;
  waitForQueueSlot: (
    maxGeneratingClips: number,
    options: {
      isAborted: () => boolean;
      pollIntervalMs: number;
      timeoutMs: number;
      queueErrorWaitMs: number;
      getCount: () => number;
      getLastChangeAt: () => number;
      stallTimeoutMs: number;
    },
  ) => Promise<void>;
  persistInterruptState: (interruptedIndex: number, orderPosition?: number) => void;
  applyJitter: (baseMs: number, jitterMs: number) => number;
  abortableSleep: (ms: number, isAborted: () => boolean) => Promise<void>;
  sleep: (ms: number) => Promise<void>;
}

export interface QueueSubmissionResult {
  completed: boolean;
  failedIndices: number[];
}

export interface SubmittedClipCompletionOptions {
  expectedClipCount: number;
  previousSubmittedClipIds: string[];
  isAborted: () => boolean;
  getSubmittedIds: () => string[];
  getPendingIdsByIds: (ids: string[]) => string[];
  getPendingSubmittedIds: () => string[];
  requestFeedPoll: (ids: string[]) => Promise<unknown>;
  abortableSleep: (ms: number, isAborted: () => boolean) => Promise<void>;
  now?: () => number;
}

/** entry のログ/UI 表示名。content.ts と共用する（title ?? name の fallback 規則の SSOT）。 */
export function entryDisplayName(entry: PromptEntry): string {
  return entry.title ?? entry.name;
}

function describeEntry(entries: PromptEntry[], index: number): string {
  return `entry ${index} (${entryDisplayName(entries[index])})`;
}

async function waitForQueueCapacity(options: QueueSubmissionOptions, index: number): Promise<void> {
  options.emitProgress({
    phase: PHASE.WAITING_SLOT,
    index,
    total: options.total,
    message: options.hasObservedAnyTraffic() ? undefined : "bridge 未観測: DOM 計数で待機中",
    yieldRetryCount: 0,
  });
  await options.waitForQueueSlot(options.maxGeneratingClips, {
    isAborted: options.isAborted,
    pollIntervalMs: POLL_INTERVAL_MS,
    timeoutMs: QUEUE_SLOT_WAIT_TIMEOUT_MS,
    queueErrorWaitMs: QUEUE_ERROR_WAIT_MS,
    getCount: options.currentInFlightCount,
    getLastChangeAt: options.getLastChangeAt,
    stallTimeoutMs: INFLIGHT_STALL_TIMEOUT_MS,
  });
}

function assertQueueClipIdsObserved(options: QueueSubmissionOptions, submittedStart: number, index: number): void {
  const observed = options.getSubmittedIds().length - submittedStart;
  if (observed < CLIPS_PER_REQUEST) {
    throw new SubmittedClipIdsNotObservedError(
      `${describeEntry(options.entries, index)} の投入 clip ID を ${observed}/${CLIPS_PER_REQUEST} 件しか観測できませんでした`,
    );
  }
}

async function submitQueueEntry(options: QueueSubmissionOptions, index: number): Promise<void> {
  const submittedStart = options.getSubmittedIds().length;
  await waitForQueueCapacity(options, index);
  if (options.isAborted()) {
    return;
  }
  options.emitProgress({ phase: PHASE.INJECTING, index, total: options.total, yieldRetryCount: 0 });
  await injectWithVerification({
    inject: () => options.submitEntryToQueue(options.entries[index], index, options.total),
    markBeforeInject: () =>
      markAck({
        getSubmissionCount: options.getSubmissionCount,
        getDomInFlightCount: options.getDomInFlightCount,
        sleep: options.sleep,
      }),
    waitForAck: options.waitForAck,
    isAborted: options.isAborted,
    maxRetry: options.preset.maxInjectRetry,
    ackTimeoutMs: options.preset.injectAckTimeoutMs,
    pollIntervalMs: POLL_INTERVAL_MS,
    describeEntry: () => describeEntry(options.entries, index),
  });
  if (!options.isAborted()) {
    assertQueueClipIdsObserved(options, submittedStart, index);
  }
}

export function emitQueueEntriesDone(
  order: number[],
  total: number,
  emitProgress: (payload: ProgressPayload) => void,
): void {
  for (const index of order) {
    emitProgress({ phase: PHASE.DONE, index, total, yieldRetryCount: 0 });
  }
}

export async function submitQueueEntries(options: QueueSubmissionOptions): Promise<QueueSubmissionResult> {
  const failedIndices: number[] = [];
  for (const [orderPosition, index] of options.order.entries()) {
    if (options.isAborted()) {
      options.persistInterruptState(index, orderPosition);
      options.emitProgress({ phase: PHASE.STOPPED, index, total: options.total });
      return { completed: false, failedIndices };
    }
    const result = await runEntryWithRetry({
      attempt: () => submitQueueEntry(options, index),
      isAborted: options.isAborted,
      wasSubmitted: (error) => options.isEntrySubmitted(index) && !(error instanceof InjectNotAcknowledgedError),
      isFatal: (error) => error instanceof FatalRunError || error instanceof SubmittedClipIdsNotObservedError,
      maxRetry: options.preset.maxEntryRetry,
      retryDelayMs: () => options.applyJitter(options.preset.interCreateDelayMs, options.preset.jitterMs),
      onRetry: (attempt, max) =>
        options.emitProgress({
          phase: PHASE.WAITING_SLOT,
          index,
          total: options.total,
          yieldRetryCount: 0,
          log: { kind: "retry", entryName: entryDisplayName(options.entries[index]), attempt, max },
        }),
      sleep: options.abortableSleep,
      describeEntry: () => describeEntry(options.entries, index),
    });
    if (result.outcome === "fatal") {
      const message = result.error instanceof Error ? result.error.message : String(result.error);
      // SubmittedClipIdsNotObservedError は InjectNotAcknowledgedError ではないため第 3 引数は false になり、
      // 投入済みなら index+1（再開時に再クリックせず skip）へ倒れる — DOM ACK 済み entry の重複生成を防ぐ意図どおり。
      const interruptIndex = resolveInterruptIndex(
        index,
        options.isEntrySubmitted(index),
        result.error instanceof InjectNotAcknowledgedError,
      );
      options.emitProgress({ phase: PHASE.ERROR, index: interruptIndex, total: options.total, message });
      options.persistInterruptState(interruptIndex, orderPosition);
      return { completed: false, failedIndices };
    }
    if (result.outcome === "aborted" || options.isAborted()) {
      const interruptIndex = resolveInterruptIndex(index, options.isEntrySubmitted(index), false);
      options.persistInterruptState(interruptIndex, orderPosition);
      options.emitProgress({ phase: PHASE.STOPPED, index: interruptIndex, total: options.total });
      return { completed: false, failedIndices };
    }
    if (result.outcome === "failed") {
      const message = result.error instanceof Error ? result.error.message : String(result.error);
      failedIndices.push(index);
      console.warn(`[suno-helper] entry ${index} をスキップして続行します: ${message}`);
      options.emitProgress({
        phase: PHASE.ENTRY_FAILED,
        index,
        total: options.total,
        message,
        yieldRetryCount: 0,
        log: { kind: "skip", entryName: entryDisplayName(options.entries[index]) },
      });
    } else {
      if (result.outcome === "presumed-done") {
        const message = result.error instanceof Error ? result.error.message : String(result.error);
        console.warn(`[suno-helper] entry ${index} は投入済みのため生成済み扱いで続行します: ${message}`);
      }
      options.emitProgress({ phase: PHASE.SUBMITTED, index, total: options.total, yieldRetryCount: 0 });
    }
    // Create→clip-row DOM 反映ラグによる過剰投入 (race) を避けるため、次の投入前に間隔を空ける (#847)。
    await options.abortableSleep(
      options.applyJitter(options.preset.interCreateDelayMs, options.preset.jitterMs),
      options.isAborted,
    );
  }
  return { completed: true, failedIndices };
}

export async function waitForSubmittedClipsComplete(options: SubmittedClipCompletionOptions): Promise<string[]> {
  const now = options.now ?? Date.now;
  const deadline = now() + INFLIGHT_STALL_TIMEOUT_MS;
  let lastPendingCount = Number.POSITIVE_INFINITY;
  while (!options.isAborted()) {
    const submittedIds = options.getSubmittedIds();
    const observedSubmittedCount = new Set([...options.previousSubmittedClipIds, ...submittedIds]).size;
    const pendingSubmittedIds = Array.from(
      new Set([...options.getPendingIdsByIds(options.previousSubmittedClipIds), ...options.getPendingSubmittedIds()]),
    );
    if (observedSubmittedCount >= options.expectedClipCount && pendingSubmittedIds.length === 0) {
      return submittedIds;
    }
    if (pendingSubmittedIds.length === 0) {
      throw new Error(
        `playlist 対象の clip ID 数が不足しています: expected ${options.expectedClipCount}, got ${observedSubmittedCount}`,
      );
    }
    if (pendingSubmittedIds.length !== lastPendingCount) {
      lastPendingCount = pendingSubmittedIds.length;
      console.info(
        `[suno-helper] final clip completion wait: submitted=${observedSubmittedCount}/${options.expectedClipCount}, pending=${pendingSubmittedIds.length}`,
      );
    }
    if (now() >= deadline) {
      throw new Error(
        `生成完了待ちがタイムアウトしました: submitted=${observedSubmittedCount}/${options.expectedClipCount}, pending=${pendingSubmittedIds.length}`,
      );
    }
    await options.requestFeedPoll(pendingSubmittedIds);
    await options.abortableSleep(POLL_INTERVAL_MS, options.isAborted);
  }
  return options.getSubmittedIds();
}
