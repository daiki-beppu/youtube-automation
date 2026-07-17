import { DEFAULT_DURATION_FILTER, type DurationFilter, type PromptEntry } from "../../shared/api";
import {
  INFLIGHT_STALL_TIMEOUT_MS,
  PHASE,
  type ProgressPayload,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
  MAX_YIELD_RETRY,
} from "../../shared/constants";
import { FatalRunError, POLL_INTERVAL_MS } from "../../shared/dom";
import type { AckMarker } from "./ack-probe";
import { markAck } from "./ack-probe";
import { InjectNotAcknowledgedError, injectWithVerification } from "./inject-retry";
import { resolveInterruptIndex } from "./resume-state";
import { runEntryWithRetry } from "./entry-retry";
import { decideDurationAttempt, evaluateClips } from "./yield-guard";

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

export interface SubmittedClipCompletionResult {
  /** stall タイムアウトで待機を打ち切ったか (#1994)。true のとき stalledClipIds に停滞 clip を保持する。 */
  timedOut: boolean;
  submittedIds: string[];
  /** 非終端 status のまま停滞した clip ID。timedOut=false のときは常に空。 */
  stalledClipIds: string[];
  /** timedOut 時のユーザー向けメッセージ。 */
  message?: string;
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
  durationOutlierStrategy:
    | { kind: "retain" }
    | {
        kind: "regenerate";
        regenerateEntry: (index: number, attempt: number) => Promise<string[]>;
        waitForRegeneratedClips: (clipIds: string[]) => Promise<void>;
      };
  isAborted?: () => boolean;
}

export interface QueueEntriesYieldResult {
  failedIndices: number[];
  abortedIndex?: number;
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
  const pendingEntries = new Map<number, { clipIds: string[]; yieldRetryCount: number }>();

  for (const index of options.order) {
    const entryClipIds = options.clipIdsByEntry.get(index) ?? [];
    if (entryClipIds.length === 0) {
      console.warn(
        `[suno-helper] entry ${index} の clip ID を bridge で観測できなかったため duration guard を skip します。`,
      );
      options.emitProgress({ phase: PHASE.DONE, index, total: options.total, yieldRetryCount: 0 });
      continue;
    }
    pendingEntries.set(index, { clipIds: entryClipIds, yieldRetryCount: 0 });
  }

  while (pendingEntries.size > 0) {
    const retries: Array<{ index: number; previousClipIds: string[]; yieldRetryCount: number }> = [];
    for (const index of options.order) {
      const pendingEntry = pendingEntries.get(index);
      if (pendingEntry === undefined) {
        continue;
      }
      const { clipIds: entryClipIds, yieldRetryCount } = pendingEntry;
      let attemptResult;
      try {
        attemptResult = {
          kind: "evaluated" as const,
          evaluation: evaluateClips(
            entryClipIds.map((id) => ({ id, duration: options.getDuration(id) })),
            durationFilter,
          ),
        };
      } catch (error) {
        attemptResult = {
          kind: "evaluation-failed" as const,
          message: error instanceof Error ? error.message : String(error),
        };
      }
      const decision = decideDurationAttempt({
        clipIds: entryClipIds,
        result: attemptResult,
        filter: durationFilter,
        policy: options.durationOutlierStrategy,
        attemptCount: yieldRetryCount,
        maxRetry: MAX_YIELD_RETRY,
      });
      if (decision.kind === "accept") {
        options.markAccepted(decision.acceptedClipIds);
        if (decision.warning) {
          console.warn(`[suno-helper] entry ${index}: ${decision.warning}`);
        }
        options.emitProgress({
          phase: PHASE.DONE,
          index,
          total: options.total,
          ...(decision.warning ? { message: decision.warning } : {}),
          ...(decision.warning ? { durationOutlierWarning: decision.warning } : {}),
          yieldRetryCount,
          acceptedClipIds: decision.acceptedClipIds,
        });
        pendingEntries.delete(index);
        continue;
      }
      if (decision.kind === "retry") {
        if (options.durationOutlierStrategy.kind !== "regenerate") {
          throw new Error("duration retain policy returned an invalid retry decision");
        }
        const nextYieldRetryCount = yieldRetryCount + 1;
        console.warn(
          `[suno-helper] entry ${index} duration guard NG、同一 prompt で再生成します (${nextYieldRetryCount}/${MAX_YIELD_RETRY}): ${decision.message}`,
        );
        options.emitProgress({
          phase: PHASE.WAITING_SLOT,
          index,
          total: options.total,
          message: `${decision.message}; retry ${nextYieldRetryCount}/${MAX_YIELD_RETRY}`,
          yieldRetryCount: nextYieldRetryCount,
          log: {
            kind: "retry",
            entryName: entryDisplayName(options.entries[index]),
            attempt: nextYieldRetryCount,
            max: MAX_YIELD_RETRY,
          },
        });
        retries.push({ index, previousClipIds: entryClipIds, yieldRetryCount: nextYieldRetryCount });
        continue;
      }
      options.dropSubmittedIds(entryClipIds);
      failedIndices.push(index);
      console.warn(
        `[suno-helper] entry ${index} は duration guard ${decision.reason === "evaluation" ? "評価失敗" : "全滅"}のためスキップします: ${decision.message}`,
      );
      options.emitProgress({
        phase: PHASE.ENTRY_FAILED,
        index,
        total: options.total,
        message: decision.message,
        yieldRetryCount,
        log: { kind: "skip", entryName: entryDisplayName(options.entries[index]) },
      });
      pendingEntries.delete(index);
    }

    if (retries.length === 0) {
      continue;
    }
    const { durationOutlierStrategy } = options;
    if (durationOutlierStrategy.kind !== "regenerate") {
      throw new Error("duration retain policy returned retry entries");
    }

    const submittedRetries: Array<{
      index: number;
      previousClipIds: string[];
      regeneratedClipIds: string[];
      yieldRetryCount: number;
    }> = [];
    for (const retry of retries) {
      try {
        const regeneratedClipIds = await durationOutlierStrategy.regenerateEntry(retry.index, retry.yieldRetryCount);
        if (options.isAborted?.()) {
          options.dropSubmittedIds(regeneratedClipIds);
          for (const submittedRetry of submittedRetries) {
            options.dropSubmittedIds(submittedRetry.regeneratedClipIds);
          }
          return { failedIndices, abortedIndex: retries[0].index };
        }
        submittedRetries.push({ ...retry, regeneratedClipIds });
      } catch (error) {
        const regenerationMessage = error instanceof Error ? error.message : String(error);
        options.dropSubmittedIds(retry.previousClipIds);
        failedIndices.push(retry.index);
        pendingEntries.delete(retry.index);
        console.warn(`[suno-helper] entry ${retry.index} の duration 再生成に失敗しました: ${regenerationMessage}`);
        options.emitProgress({
          phase: PHASE.ENTRY_FAILED,
          index: retry.index,
          total: options.total,
          message: regenerationMessage,
          yieldRetryCount: retry.yieldRetryCount,
          log: { kind: "skip", entryName: entryDisplayName(options.entries[retry.index]) },
        });
      }
    }

    const completionResults = await Promise.all(
      submittedRetries.map(async (retry) => {
        try {
          await durationOutlierStrategy.waitForRegeneratedClips(retry.regeneratedClipIds);
          return { ...retry, error: undefined };
        } catch (error) {
          return { ...retry, error: error instanceof Error ? error.message : String(error) };
        }
      }),
    );
    if (options.isAborted?.()) {
      for (const completion of completionResults) {
        options.dropSubmittedIds(completion.regeneratedClipIds);
      }
      return { failedIndices, abortedIndex: completionResults[0]?.index };
    }
    for (const completion of completionResults) {
      if (completion.error !== undefined) {
        options.dropSubmittedIds(completion.regeneratedClipIds);
        options.dropSubmittedIds(completion.previousClipIds);
        failedIndices.push(completion.index);
        pendingEntries.delete(completion.index);
        console.warn(`[suno-helper] entry ${completion.index} の duration 再生成に失敗しました: ${completion.error}`);
        options.emitProgress({
          phase: PHASE.ENTRY_FAILED,
          index: completion.index,
          total: options.total,
          message: completion.error,
          yieldRetryCount: completion.yieldRetryCount,
          log: { kind: "skip", entryName: entryDisplayName(options.entries[completion.index]) },
        });
        continue;
      }
      options.dropSubmittedIds(completion.previousClipIds);
      options.clipIdsByEntry.set(completion.index, completion.regeneratedClipIds);
      pendingEntries.set(completion.index, {
        clipIds: completion.regeneratedClipIds,
        yieldRetryCount: completion.yieldRetryCount,
      });
    }
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

export async function waitForSubmittedClipsComplete(
  options: SubmittedClipCompletionOptions,
): Promise<SubmittedClipCompletionResult> {
  const now = options.now ?? Date.now;
  let lastProgressAt = now();
  let deadline = lastProgressAt + INFLIGHT_STALL_TIMEOUT_MS;
  let lastPendingCount: number | undefined;
  while (!options.isAborted()) {
    const submittedIds = options.getSubmittedIds();
    const observedSubmittedCount = new Set([...options.previousSubmittedClipIds, ...submittedIds]).size;
    const pendingSubmittedIds = Array.from(
      new Set([...options.getPendingIdsByIds(options.previousSubmittedClipIds), ...options.getPendingSubmittedIds()]),
    );
    if (observedSubmittedCount >= options.expectedClipCount && pendingSubmittedIds.length === 0) {
      return { timedOut: false, submittedIds, stalledClipIds: [] };
    }
    if (pendingSubmittedIds.length === 0) {
      throw new Error(
        `playlist 対象の clip ID 数が不足しています: expected ${options.expectedClipCount}, got ${observedSubmittedCount}`,
      );
    }
    const currentNow = now();
    const pendingCountDecreased = lastPendingCount !== undefined && pendingSubmittedIds.length < lastPendingCount;
    if (pendingCountDecreased) {
      lastProgressAt = currentNow;
      deadline = lastProgressAt + INFLIGHT_STALL_TIMEOUT_MS;
    }
    if (pendingSubmittedIds.length !== lastPendingCount) {
      console.info(
        `[suno-helper] final clip completion wait: submitted=${observedSubmittedCount}/${options.expectedClipCount}, pending=${pendingSubmittedIds.length}`,
      );
    }
    lastPendingCount = pendingSubmittedIds.length;
    if (currentNow >= deadline) {
      // stall タイムアウトは throw せず結果で返す (#1994)。呼び出し元が完了済み clip での
      // graceful degradation（playlist 追加 / download の続行）を判断できるようにする。
      return {
        timedOut: true,
        submittedIds,
        stalledClipIds: pendingSubmittedIds,
        message: `生成完了待ちがタイムアウトしました: submitted=${observedSubmittedCount}/${options.expectedClipCount}, pending=${pendingSubmittedIds.length}, 最後の進捗からの経過時間=${currentNow - lastProgressAt}ms`,
      };
    }
    await options.requestFeedPoll(pendingSubmittedIds);
    await options.abortableSleep(POLL_INTERVAL_MS, options.isAborted);
  }
  return { timedOut: false, submittedIds: options.getSubmittedIds(), stalledClipIds: [] };
}

/** stall した clip ID を queue mode の entry index へ対応付ける (#1994)。
 * clipIdsByEntry に載らない stalled ID（resume 由来の previousSubmittedClipIds 等）は
 * unmappedStalledClipIds に分離し、呼び出し元が graceful degradation の可否を判定する。 */
export function resolveStalledQueueEntries(
  stalledClipIds: string[],
  clipIdsByEntry: Map<number, string[]>,
): { stalledEntryIndices: number[]; unmappedStalledClipIds: string[] } {
  const stalledSet = new Set(stalledClipIds);
  const stalledEntryIndices: number[] = [];
  const mappedIds = new Set<string>();
  for (const [index, clipIds] of clipIdsByEntry) {
    const stalledInEntry = clipIds.filter((id) => stalledSet.has(id));
    if (stalledInEntry.length === 0) {
      continue;
    }
    stalledEntryIndices.push(index);
    for (const id of stalledInEntry) {
      mappedIds.add(id);
    }
  }
  stalledEntryIndices.sort((a, b) => a - b);
  const unmappedStalledClipIds = stalledClipIds.filter((id) => !mappedIds.has(id));
  return { stalledEntryIndices, unmappedStalledClipIds };
}
