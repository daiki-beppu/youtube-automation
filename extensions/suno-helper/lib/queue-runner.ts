import { DEFAULT_DURATION_FILTER, type DurationFilter, type PromptEntry } from "../../shared/api";
import {
  INFLIGHT_STALL_TIMEOUT_MS,
  PHASE,
  type ProgressPayload,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
} from "../../shared/constants";
import { FatalRunError, POLL_INTERVAL_MS } from "../../shared/dom";
import type { AckMarker } from "./ack-probe";
import { markAck } from "./ack-probe";
import { InjectNotAcknowledgedError, injectWithVerification } from "./inject-retry";
import { resolveInterruptIndex } from "./resume-state";
import { runEntryWithRetry } from "./entry-retry";
import { evaluateClips, formatYieldFailure } from "./yield-guard";

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
  clipIdsByEntry: Map<number, string[]>;
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

export interface QueueEntriesYieldOptions {
  entries: PromptEntry[];
  order: number[];
  total: number;
  clipIdsByEntry: Map<number, string[]>;
  durationFilter?: DurationFilter;
  getDuration: (clipId: string) => number | undefined;
  markAccepted: (ids: string[]) => void;
  dropSubmittedIds: (ids: string[]) => void;
  emitProgress: (payload: ProgressPayload) => void;
}

export interface QueueEntriesYieldResult {
  failedIndices: number[];
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

function getNewSubmittedIds(before: ReadonlySet<string>, current: string[]): string[] {
  return current.filter((id) => !before.has(id));
}

async function submitQueueEntry(options: QueueSubmissionOptions, index: number): Promise<void> {
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
}

export async function finalizeQueueEntriesYield(options: QueueEntriesYieldOptions): Promise<QueueEntriesYieldResult> {
  const failedIndices: number[] = [];
  const durationFilter = options.durationFilter ?? DEFAULT_DURATION_FILTER;
  for (const index of options.order) {
    const entryClipIds = options.clipIdsByEntry.get(index) ?? [];
    if (entryClipIds.length === 0) {
      console.warn(
        `[suno-helper] entry ${index} の clip ID を bridge で観測できなかったため duration guard を skip します。`,
      );
      options.emitProgress({ phase: PHASE.DONE, index, total: options.total, yieldRetryCount: 0 });
      continue;
    }
    const evaluation = evaluateClips(
      entryClipIds.map((id) => ({ id, duration: options.getDuration(id) })),
      durationFilter,
    );
    if (evaluation.ok.length > 0) {
      options.markAccepted(evaluation.ok);
      options.emitProgress({
        phase: PHASE.DONE,
        index,
        total: options.total,
        yieldRetryCount: 0,
        acceptedClipIds: evaluation.ok,
      });
      continue;
    }
    const message = formatYieldFailure(evaluation, durationFilter);
    options.dropSubmittedIds(entryClipIds);
    failedIndices.push(index);
    console.warn(`[suno-helper] entry ${index} は duration guard 全滅のためスキップします: ${message}`);
    options.emitProgress({
      phase: PHASE.ENTRY_FAILED,
      index,
      total: options.total,
      message,
      yieldRetryCount: 0,
      log: { kind: "skip", entryName: entryDisplayName(options.entries[index]) },
    });
  }
  return { failedIndices };
}

export async function submitQueueEntries(options: QueueSubmissionOptions): Promise<QueueSubmissionResult> {
  const failedIndices: number[] = [];
  const clipIdsByEntry = new Map<number, string[]>();
  for (const [orderPosition, index] of options.order.entries()) {
    if (options.isAborted()) {
      options.persistInterruptState(index, orderPosition);
      options.emitProgress({ phase: PHASE.STOPPED, index, total: options.total });
      return { completed: false, failedIndices, clipIdsByEntry };
    }
    const submittedBeforeEntry = new Set(options.getSubmittedIds());
    const result = await runEntryWithRetry({
      attempt: async () => {
        await submitQueueEntry(options, index);
      },
      isAborted: options.isAborted,
      wasSubmitted: (error) => options.isEntrySubmitted(index) && !(error instanceof InjectNotAcknowledgedError),
      isFatal: (error) => error instanceof FatalRunError,
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
      const interruptIndex = resolveInterruptIndex(
        index,
        options.isEntrySubmitted(index),
        result.error instanceof InjectNotAcknowledgedError,
      );
      options.emitProgress({ phase: PHASE.ERROR, index: interruptIndex, total: options.total, message });
      options.persistInterruptState(interruptIndex, orderPosition);
      return { completed: false, failedIndices, clipIdsByEntry };
    }
    if (result.outcome === "aborted" || options.isAborted()) {
      const interruptIndex = resolveInterruptIndex(index, options.isEntrySubmitted(index), false);
      options.persistInterruptState(interruptIndex, orderPosition);
      options.emitProgress({ phase: PHASE.STOPPED, index: interruptIndex, total: options.total });
      return { completed: false, failedIndices, clipIdsByEntry };
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
      clipIdsByEntry.set(index, getNewSubmittedIds(submittedBeforeEntry, options.getSubmittedIds()));
      options.emitProgress({ phase: PHASE.SUBMITTED, index, total: options.total, yieldRetryCount: 0 });
    }
    // Create→clip-row DOM 反映ラグによる過剰投入 (race) を避けるため、次の投入前に間隔を空ける (#847)。
    await options.abortableSleep(
      options.applyJitter(options.preset.interCreateDelayMs, options.preset.jitterMs),
      options.isAborted,
    );
  }
  return { completed: true, failedIndices, clipIdsByEntry };
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
