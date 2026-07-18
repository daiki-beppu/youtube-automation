// Suno の Advanced タブへの Style / Lyrics 注入と Generate 連続実行 (content script)。
// DOM 操作は shared/dom の純関数へ委譲し、本ファイルは連続実行のフロー制御に専念する。
import {
  type CollectionSummary,
  DEFAULT_DURATION_FILTER,
  type DurationFilter,
  extractPlaylistName,
  type PromptEntry,
  type PromptResponse,
} from "../../shared/api";
import {
  BALANCED_RUN_PACING,
  CLIPS_PER_REQUEST,
  DEFAULT_REGENERATE_DURATION_OUTLIERS,
  INFLIGHT_STALL_TIMEOUT_MS,
  MAX_YIELD_RETRY,
  PHASE,
  type ProgressPayload,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
  RUN_MODES,
  type RunModeId,
  type SnapshotPayload,
  SUNO_MATCHES,
} from "../../shared/constants";
import {
  abortableSleep,
  CAPTCHA_WAIT_TIMEOUT_MS,
  detectRecaptcha,
  diagnoseLyricsInputState,
  FatalRunError,
  GENERATE_TIMEOUT_MS,
  LyricsPasteReflectionError,
  POLL_INTERVAL_MS,
  SETTLE_MS,
  detectSunoViewMode,
  getInFlightClipCount,
  injectAdvancedFields,
  resolveAdvancedFields,
  resolveFields,
  resolveGenerateButton,
  setLyricsValue,
  setLyricsValueViaBeforeInput,
  setNativeValue,
  sleep,
  waitForCaptchaClear,
  waitForGeneration,
  waitForQueueSlot,
} from "../../shared/dom";
import {
  clickPlaylistRowByName,
  findPlaylistUrlsByName,
  fillPlaylistNameAndCreate,
  openAddToPlaylistDialogViaCmdP,
  readSelectedClipIds,
  scrollAndMultiSelectByIds,
  waitForPlaylistDialogClose,
  waitForNewPlaylistUrlByName,
} from "../../shared/playlist-dom";
import { createAckWaiter, markAck } from "../lib/ack-probe";
import {
  attachBridgeListener,
  createFeedPoller,
  requestFeedPoll,
  requestSliderSet,
} from "../lib/bridge-listener";
import { createClipTracker } from "../lib/clip-tracker";
import { acquireDomRunLock, releaseDomRunLock } from "../lib/dom-run-lock";
import { createDownloadFlow } from "../lib/download-flow";
import type { DownloadContext } from "../lib/download-flow";
import { runEntryWithRetry } from "../lib/entry-retry";
import {
  clearFinishedSnapshot,
  readFreshFinishedSnapshot,
  writeFinishedSnapshot,
} from "../lib/finished-snapshot";
import {
  InjectNotAcknowledgedError,
  injectWithVerification,
  retryInjectStepWithFallback,
} from "../lib/inject-retry";
import { onMessage, sendMessage } from "../lib/messaging";
import type {
  RetryDownloadPayload,
  RetryPlaylistPayload,
  RunPayload,
} from "../lib/messaging";
import {
  cancelScheduledRunCompleteReload,
  scheduleRunCompleteReload,
} from "../lib/page-reload";
import { applyJitter } from "../lib/preset-state";
import {
  entryDisplayName,
  finalizeQueueEntriesYield,
  resolveStalledQueueEntries,
  submitQueueEntries,
  waitForSubmittedClipsComplete,
} from "../lib/queue-runner";
import {
  clearResumeStateForCollection,
  readResumeState,
  resolvePlaylistClipIds,
  resolveInterruptIndex,
  type RunRange,
  writeResumeState,
} from "../lib/resume-state";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import {
  downloadFormatItem,
  readDownloadFormat,
  serverUrlItem,
} from "../lib/storage";
import {
  assertUnattendedRunRequest,
  createUnattendedManualState,
  hasCompleteUnattendedArtifacts,
  nextUnattendedRunState,
  parseUnattendedLaunchHash,
  planUnattendedRun,
  type UnattendedRunRequest,
} from "../lib/unattended-run";
import {
  exposeUnattendedRunState,
  readUnattendedRunState,
  writeUnattendedRunState,
} from "../lib/unattended-state";
import {
  decideDurationAttempt,
  evaluateClips,
  type DurationOutlierPolicy,
} from "../lib/yield-guard";

function assertNonEmptyString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${field} must be non-empty string`);
  }
  return value;
}

function assertRecord(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${field} must be object`);
  }
  return value as Record<string, unknown>;
}

function assertStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${field} must be string array`);
  }
  return value;
}

function assertOptionalStringArray(
  value: unknown,
  field: string
): string[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  return assertStringArray(value, field);
}

function assertOptionalNonNegativeInteger(
  value: unknown,
  field: string
): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0 ||
    Object.is(value, -0)
  ) {
    throw new Error(`${field} must be non-negative integer`);
  }
  return value;
}

function assertOptionalNonNegativeNumber(
  value: unknown,
  field: string
): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < 0 ||
    Object.is(value, -0)
  ) {
    throw new Error(`${field} must be non-negative number`);
  }
  return value;
}

function assertOptionalBoolean(
  value: unknown,
  field: string
): boolean | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== "boolean") {
    throw new Error(`${field} must be boolean`);
  }
  return value;
}

export interface AttemptClipCompletionOptions {
  getPendingIdsByIds: (clipIds: string[]) => string[];
  requestFeedPoll: (clipIds: string[]) => Promise<unknown>;
  abortableSleep: (
    milliseconds: number,
    isAborted: () => boolean
  ) => Promise<void>;
  isAborted: () => boolean;
  now: () => number;
}

export async function waitForAttemptClipsComplete(
  clipIds: string[],
  options: AttemptClipCompletionOptions
): Promise<void> {
  if (clipIds.length === 0) {
    throw new Error(
      "duration guard 用の clip ID を観測できませんでした。bridge の generate 観測を確認してください。"
    );
  }
  let lastProgressAt = options.now();
  let deadline = lastProgressAt + INFLIGHT_STALL_TIMEOUT_MS;
  let lastPendingCount: number | undefined;
  while (!options.isAborted()) {
    const pendingIds = options.getPendingIdsByIds(clipIds);
    if (pendingIds.length === 0) {
      return;
    }
    const currentNow = options.now();
    const pendingCountDecreased =
      lastPendingCount !== undefined && pendingIds.length < lastPendingCount;
    if (pendingCountDecreased) {
      lastProgressAt = currentNow;
      deadline = lastProgressAt + INFLIGHT_STALL_TIMEOUT_MS;
    }
    if (pendingIds.length !== lastPendingCount) {
      console.info(
        `[suno-helper] yield guard wait: pending=${pendingIds.length}/${clipIds.length}`
      );
    }
    lastPendingCount = pendingIds.length;
    if (currentNow >= deadline) {
      throw new Error(
        `duration guard の clip 完了待ちがタイムアウトしました: pending=${pendingIds.length}, 最後の進捗からの経過時間=${currentNow - lastProgressAt}ms`
      );
    }
    await options.requestFeedPoll(pendingIds);
    await options.abortableSleep(POLL_INTERVAL_MS, options.isAborted);
  }
}

function assertOptionalDurationFilter(
  value: unknown,
  field: string
): DurationFilter | undefined {
  if (value === undefined) {
    return undefined;
  }
  const record = assertRecord(value, field);
  const minSec = assertOptionalNonNegativeNumber(
    record.min_sec,
    `${field}.min_sec`
  );
  const maxSec = assertOptionalNonNegativeNumber(
    record.max_sec,
    `${field}.max_sec`
  );
  if (minSec === undefined || maxSec === undefined) {
    throw new Error(`${field}.min_sec and ${field}.max_sec are required`);
  }
  if (minSec > maxSec) {
    throw new Error(`${field}.min_sec must be less than or equal to max_sec`);
  }
  return { min_sec: minSec, max_sec: maxSec };
}

function assertRunMode(value: unknown, field: string): RunModeId {
  if (typeof value !== "string" || !Object.hasOwn(RUN_MODES, value)) {
    throw new Error(`${field} must be serial or queue`);
  }
  return value as RunModeId;
}

function assertOptionalIndices(
  value: unknown,
  field: string,
  entryCount: number,
  allowEmpty = false
): number[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    throw new Error(`${field} must be number array`);
  }
  if (value.length === 0 && !allowEmpty) {
    throw new Error(`${field} must not be empty`);
  }
  const seen = new Set<number>();
  return value.map((item, index) => {
    if (typeof item !== "number" || !Number.isInteger(item)) {
      throw new Error(`${field}[${index}] must be integer`);
    }
    if (item < 0 || item >= entryCount) {
      throw new Error(`${field}[${index}] must be within entries range`);
    }
    if (seen.has(item)) {
      throw new Error(`${field}[${index}] must be unique`);
    }
    seen.add(item);
    return item;
  });
}

// fallow-ignore-next-line complexity
function assertRunPayload(value: unknown): RunPayload {
  const record = assertRecord(value, "run payload");
  if (!Array.isArray(record.entries)) {
    throw new Error("run.entries must be array");
  }
  const unattendedRecord =
    record.unattended === undefined
      ? undefined
      : assertRecord(record.unattended, "run.unattended");
  const unattended = unattendedRecord
    ? {
        request: assertUnattendedRunRequest(unattendedRecord.request),
        deferredIndices:
          assertOptionalIndices(
            unattendedRecord.deferredIndices,
            "run.unattended.deferredIndices",
            record.entries.length,
            true
          ) ?? [],
        leaseToken: assertNonEmptyString(
          unattendedRecord.leaseToken,
          "run.unattended.leaseToken"
        ),
      }
    : undefined;
  const payload = {
    ...(record as unknown as RunPayload),
    entries: record.entries as PromptEntry[],
    playlistName: assertNonEmptyString(record.playlistName, "run.playlistName"),
    collectionId: assertNonEmptyString(record.collectionId, "run.collectionId"),
    runMode: assertRunMode(record.runMode, "run.runMode"),
    regenerateDurationOutliers:
      assertOptionalBoolean(
        record.regenerateDurationOutliers,
        "run.regenerateDurationOutliers"
      ) ?? DEFAULT_REGENERATE_DURATION_OUTLIERS,
    durationFilter: assertOptionalDurationFilter(
      record.durationFilter,
      "run.durationFilter"
    ),
    indices: assertOptionalIndices(
      record.indices,
      "run.indices",
      record.entries.length
    ),
    submittedClipIds: assertOptionalStringArray(
      record.submittedClipIds,
      "run.submittedClipIds"
    ),
    submittedClipIdsAreDurationFiltered: assertOptionalBoolean(
      record.submittedClipIdsAreDurationFiltered,
      "run.submittedClipIdsAreDurationFiltered"
    ),
    playlistExpectedClipCount: assertOptionalNonNegativeInteger(
      record.playlistExpectedClipCount,
      "run.playlistExpectedClipCount"
    ),
    durationOutlierWarnings: assertOptionalDurationOutlierWarnings(
      record.durationOutlierWarnings
    ),
    unattended,
  };
  if (unattended) {
    if (unattended.request.collectionId !== payload.collectionId) {
      throw new Error(
        "run.unattended request collection must match run.collectionId"
      );
    }
    const selectedCount = payload.indices?.length ?? payload.entries.length;
    if (selectedCount > unattended.request.limits.maxEntries) {
      throw new Error("run.indices exceeds unattended maxEntries");
    }
  }
  return payload;
}

function assertOptionalDurationOutlierWarnings(
  value: unknown
): Record<number, string> | undefined {
  if (value === undefined) {
    return undefined;
  }
  const record = assertRecord(value, "run.durationOutlierWarnings");
  return Object.fromEntries(
    Object.entries(record).map(([index, warning]) => {
      if (!/^\d+$/.test(index) || typeof warning !== "string") {
        throw new Error(
          "run.durationOutlierWarnings must map entry indexes to strings"
        );
      }
      return [Number(index), warning];
    })
  );
}

function assertRetryPlaylistPayload(value: unknown): RetryPlaylistPayload {
  const record = assertRecord(value, "retryPlaylist payload");
  const unattendedRecord =
    record.unattended === undefined
      ? undefined
      : assertRecord(record.unattended, "retryPlaylist.unattended");
  const unattended = unattendedRecord
    ? {
        request: assertUnattendedRunRequest(unattendedRecord.request),
        deferredIndices:
          assertOptionalIndices(
            unattendedRecord.deferredIndices,
            "retryPlaylist.unattended.deferredIndices",
            0,
            true
          ) ?? [],
        leaseToken: assertNonEmptyString(
          unattendedRecord.leaseToken,
          "retryPlaylist.unattended.leaseToken"
        ),
      }
    : undefined;
  const collectionId = assertNonEmptyString(
    record.collectionId,
    "retryPlaylist.collectionId"
  );
  if (unattended && unattended.request.collectionId !== collectionId) {
    throw new Error(
      "retryPlaylist.unattended request collection must match collectionId"
    );
  }
  return {
    playlistName: assertNonEmptyString(
      record.playlistName,
      "retryPlaylist.playlistName"
    ),
    submittedClipIds: assertStringArray(
      record.submittedClipIds,
      "retryPlaylist.submittedClipIds"
    ),
    expectedClipCount:
      assertOptionalNonNegativeInteger(
        record.expectedClipCount,
        "retryPlaylist.expectedClipCount"
      ) ?? 0,
    collectionId,
    durationFilter: assertOptionalDurationFilter(
      record.durationFilter,
      "retryPlaylist.durationFilter"
    ),
    regenerateDurationOutliers:
      assertOptionalBoolean(
        record.regenerateDurationOutliers,
        "retryPlaylist.regenerateDurationOutliers"
      ) ?? DEFAULT_REGENERATE_DURATION_OUTLIERS,
    durationOutlierWarnings: assertOptionalDurationOutlierWarnings(
      record.durationOutlierWarnings
    ),
    submittedClipIdsAreDurationFiltered: assertOptionalBoolean(
      record.submittedClipIdsAreDurationFiltered,
      "retryPlaylist.submittedClipIdsAreDurationFiltered"
    ),
    shouldDownload: assertOptionalBoolean(
      record.shouldDownload,
      "retryPlaylist.shouldDownload"
    ),
    unattended,
  };
}

function assertRetryDownloadPayload(value: unknown): RetryDownloadPayload {
  const record = assertRecord(value, "retryDownload payload");
  const collectionId = assertNonEmptyString(
    record.collectionId,
    "retryDownload.collectionId"
  );
  const unattendedRecord =
    record.unattended === undefined
      ? undefined
      : assertRecord(record.unattended, "retryDownload.unattended");
  const unattended = unattendedRecord
    ? {
        request: assertUnattendedRunRequest(unattendedRecord.request),
        deferredIndices:
          assertOptionalIndices(
            unattendedRecord.deferredIndices,
            "retryDownload.unattended.deferredIndices",
            0,
            true
          ) ?? [],
        leaseToken: assertNonEmptyString(
          unattendedRecord.leaseToken,
          "retryDownload.unattended.leaseToken"
        ),
      }
    : undefined;
  if (unattended && unattended.request.collectionId !== collectionId) {
    throw new Error(
      "retryDownload.unattended request collection must match collectionId"
    );
  }
  return {
    collectionId,
    submittedClipIds: assertStringArray(
      record.submittedClipIds,
      "retryDownload.submittedClipIds"
    ),
    expectedClipCount: assertOptionalNonNegativeInteger(
      record.expectedClipCount,
      "retryDownload.expectedClipCount"
    ),
    unattended,
  };
}

function buildTitleFallbackMap(
  entries: PromptEntry[],
  order: number[],
  submittedIds: string[]
): Map<string, string> {
  const map = new Map<string, string>();
  for (let i = 0; i < order.length; i++) {
    const entry = entries[order[i]];
    if (!entry) continue;
    const title = entry.title ?? entry.name;
    const clipBase = i * CLIPS_PER_REQUEST;
    for (let c = 0; c < CLIPS_PER_REQUEST; c++) {
      const clipId = submittedIds[clipBase + c];
      if (clipId) {
        map.set(clipId, title);
      }
    }
  }
  return map;
}

interface PlaylistClipPlan {
  clipIds: string[];
  expectedClipCount: number;
  titleFallbackMap: Map<string, string>;
}

interface PlaylistClipPersistInfo {
  submittedClipIds: string[];
  submittedClipIdsAreDurationFiltered: boolean;
  playlistExpectedClipCount: number;
  playlistUrlsBeforeCreate?: string[];
}

async function resolveDownloadContext(
  formatOverride?: DownloadContext["format"]
): Promise<DownloadContext> {
  return {
    baseUrl: (await serverUrlItem.getValue()).trim(),
    format: formatOverride ?? (await readDownloadFormat()),
  };
}

function isVisibleElement(element: Element): boolean {
  if (!(element instanceof HTMLElement) || element.hidden) return false;
  if (element.getAttribute("aria-hidden") === "true") return false;
  const style = getComputedStyle(element);
  if (style.display === "none" || style.visibility === "hidden") return false;
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function detectUnattendedPreflightBlocker(): {
  reason: "login-required" | "captcha-required" | "cost-confirmation-required";
  message: string;
} | null {
  if (detectRecaptcha()) {
    return {
      reason: "captcha-required",
      message: "Suno に未解決の CAPTCHA challenge が表示されています。",
    };
  }
  const loginElement = Array.from(
    document.querySelectorAll('a[href*="/login" i], button, [role="button"]')
  ).find(
    (element) =>
      isVisibleElement(element) &&
      /^(sign[ -]?in|log[ -]?in|ログイン)$/i.test(
        element.textContent?.trim() ?? ""
      )
  );
  if (loginElement) {
    return {
      reason: "login-required",
      message: "Suno のログイン操作が必要です。",
    };
  }
  const costDialog = Array.from(
    document.querySelectorAll('[role="dialog"], [aria-modal="true"]')
  ).find((element) => {
    if (!isVisibleElement(element)) return false;
    const text = element.textContent?.toLowerCase() ?? "";
    return /credit|payment|purchase|subscribe|upgrade|課金|料金|購入/.test(
      text
    );
  });
  if (costDialog) {
    return {
      reason: "cost-confirmation-required",
      message: "Suno に料金または credit 消費の確認画面が表示されています。",
    };
  }
  return null;
}

function playlistNameForCollection(collection: CollectionSummary): string {
  if (collection.channel && collection.theme) {
    return `${collection.channel} | ${collection.theme}`;
  }
  const theme = (collection.theme ?? collection.name).replace(
    /-collection$/,
    ""
  );
  return extractPlaylistName(collection.id, theme);
}

export default defineContentScript({
  matches: [...SUNO_MATCHES],
  main(ctx) {
    // 更新前に残った content script は service worker と別バージョンになり得る。
    // handshake 自体の失敗も古い context では起こり得るため、必ず catch して未処理 rejection を残さない。
    try {
      const version = browser.runtime.getManifest().version;
      void sendMessage("extensionVersionHandshake", { version })
        .then((result) => {
          if (!result.matches) {
            console.warn(
              `[suno-helper] content script のバージョンが不一致です（${version} / ${result.version}）`
            );
          }
        })
        .catch((error: unknown) => {
          console.warn(
            "[suno-helper] content script の version handshake に失敗しました（context invalidated?）:",
            error
          );
        });
    } catch (error) {
      console.warn(
        "[suno-helper] content script の version handshake を開始できません（context invalidated?）:",
        error
      );
    }
    let aborted = false;
    // 連続実行の二重起動ガード (#892 要件7)。runAll 実行中の run 再着信を弾く。
    let running = false;
    const runLockOwner = `${Date.now()}-${Math.random()}`;
    // WXT 実行時 context がある実ブラウザだけDOM共有lockを使う。node単体テストの簡易contextでは
    // 従来のclosure内 runningガードへ縮退し、テスト間でdocument属性を共有しない。
    const runLockRoot =
      typeof document !== "undefined" &&
      typeof ctx?.onInvalidated === "function"
        ? document.documentElement
        : null;
    const acquireRunLock = (): boolean =>
      runLockRoot === null || acquireDomRunLock(runLockRoot, runLockOwner);
    const releaseRunLock = (): void => {
      if (runLockRoot !== null) releaseDomRunLock(runLockRoot, runLockOwner);
    };
    ctx?.onInvalidated?.(releaseRunLock);
    // 直近の injectEntryAndClickGenerate で Generate を click した entry の 0-based index (#924)。
    // -1 は「まだ click していない」。中断時に submitted 判定と組み合わせて interruptIndex を決定する。
    // run ハンドラで -1 にリセットし、injectEntryAndClickGenerate の冒頭でも attempt ごとにリセットする（理由は同関数コメント参照）。
    let lastSubmittedEntryIndex = -1;
    // popup を閉じても進捗を維持・復元するための SSOT (#852)。run 開始で initSnapshot、
    // 以降は emitProgress が sendMessage より前に同期更新する（queryProgress と race しないため）。
    let currentSnapshot: SnapshotPayload | null = null;
    let activeUnattended: RunPayload["unattended"];
    // progress は高頻度で到着するため、storage 書き込みを直列化して古い phase が
    // FINISHED / manual-intervention を後から上書きする race を防ぐ。
    let unattendedStateWrite: Promise<void> = Promise.resolve();
    let resumeStateWrite: Promise<void> = Promise.resolve();
    const verifiedUnattendedRequests = new Set<string>();

    // bridge（MAIN world）の観測を集約する in-flight の SSOT (#948)。run の外でも常時受信し、
    // run 前のページ操作（手動投入等）や前 run の残留 in-flight も passive 合流で数える。
    const tracker = createClipTracker();
    attachBridgeListener(tracker);
    // status 更新は WebSocket 経由でページの feed fetch を期待できないため、run 中は
    // 未終端 clip がある限り active feed poll で status を追う（runAll の finally で stop）。
    const feedPoller = createFeedPoller(tracker);
    let warnedDomFallback = false;

    /** in-flight 数の合成カウント (#948)。bridge 観測があれば status ベース、無ければ DOM プロキシへ縮退。 */
    function currentInFlightCount(): number {
      if (tracker.hasObservedAnyTraffic()) {
        return tracker.getInFlightCount();
      }
      if (!warnedDomFallback) {
        warnedDomFallback = true;
        console.warn(
          "[suno-helper] bridge 未観測のため DOM プロキシで in-flight を数えます（過大カウントの可能性あり）"
        );
      }
      return getInFlightClipCount();
    }

    /** inject ACK のハイブリッド判定 (#948)。bridge の generate レスポンス観測 OR DOM 増分。 */
    const waitForAck = createAckWaiter({
      getSubmissionCount: () => tracker.submissionCount(),
      getDomInFlightCount: getInFlightClipCount,
      sleep,
    });

    function emitProgress(payload: ProgressPayload): void {
      if (!currentSnapshot) {
        // run ハンドラで initSnapshot 済みのため到達しない。万一来たら不変条件違反として fail-loud。
        throw new Error("progress emit before run initialization");
      }
      currentSnapshot = applyProgress(currentSnapshot, payload);
      if (activeUnattended) {
        const state = nextUnattendedRunState({
          request: activeUnattended.request,
          progress: payload,
          deferredIndices: activeUnattended.deferredIndices,
          now: Date.now(),
          verifiedComplete: verifiedUnattendedRequests.has(
            activeUnattended.request.requestId
          ),
        });
        unattendedStateWrite = Promise.all([
          unattendedStateWrite,
          resumeStateWrite,
        ])
          .then(() => writeUnattendedRunState(state))
          .catch((error: unknown) => {
            console.warn(
              "[suno-helper] 定期実行 state の永続化に失敗しました:",
              error
            );
          });
      }
      void sendMessage("progress", payload);
    }

    async function releaseExecutionLease(
      unattended: RunPayload["unattended"] | undefined
    ): Promise<void> {
      if (!unattended) return;
      await sendMessage("releaseUnattendedLease", {
        collectionId: unattended.request.collectionId,
        token: unattended.leaseToken,
      }).catch((error: unknown) => {
        console.warn("[suno-helper] 定期実行 lease を解放できません:", error);
      });
    }

    function assertUnattendedUiIsSafe(): void {
      if (!activeUnattended) return;
      const blocker = detectUnattendedPreflightBlocker();
      if (blocker) throw new FatalRunError(blocker.message);
    }

    async function verifyUnattendedCompletion(
      unattended: RunPayload["unattended"]
    ): Promise<void> {
      if (!unattended) return;
      const collections = await sendMessage("fetchCollections", {
        baseUrl: unattended.request.baseUrl,
      });
      const collection = collections.find(
        (candidate) => candidate.id === unattended.request.collectionId
      );
      const promptResponse = await sendMessage(
        "fetchCollectionPromptResponse",
        {
          baseUrl: unattended.request.baseUrl,
          collectionId: unattended.request.collectionId,
        }
      );
      if (
        !collection ||
        !hasCompleteUnattendedArtifacts(
          collection,
          promptResponse.entries.length * CLIPS_PER_REQUEST
        )
      ) {
        throw new Error(
          "server readback で音源ファイル・playlist URL・downloaded 状態を確認できません。"
        );
      }
      verifiedUnattendedRequests.add(unattended.request.requestId);
    }

    /**
     * 完了時リロード (#1411) の直前に FINISHED snapshot を chrome.storage.local へ退避する。
     * リロードは in-memory の currentSnapshot（queryProgress の復元 SSOT, #852）を破棄するため、
     * run 中に popup を閉じていた運用者が再 open しても完了結果を確認できるよう引き継ぐ。
     * 退避に失敗したら false を返し、呼び出し側はリロードを見送る（in-memory snapshot が
     * 生き残るため復元性は保たれる。残る stale selection は次 run の Cmd+P 前ガードが検知する —
     * resume state 消去失敗時と同じ扱い）。
     */
    async function persistFinishedSnapshotForReload(): Promise<boolean> {
      if (!currentSnapshot) {
        // FINISHED emit 済みの経路からのみ呼ばれるため到達しない（emitProgress と同じ不変条件）。
        return false;
      }
      try {
        await writeFinishedSnapshot({
          snapshot: currentSnapshot,
          timestamp: Date.now(),
        });
        return true;
      } catch (err) {
        console.warn(
          "[suno-helper] 完了 snapshot の退避に失敗しました。完了時リロードを見送ります:",
          err
        );
        return false;
      }
    }

    const downloadFlow = createDownloadFlow({
      emitProgress,
      isAborted: () => aborted,
      onDownloadComplete: async (filename) => {
        if (!activeUnattended) return;
        const collectionId = activeUnattended.request.collectionId;
        resumeStateWrite = resumeStateWrite.then(async () => {
          const state = await readResumeState();
          if (state?.collectionId !== collectionId) {
            throw new Error(
              "download checkpoint に対応する resume state がありません"
            );
          }
          await writeResumeState({
            ...state,
            timestamp: Date.now(),
            downloadCompletedFilename: filename,
          });
        });
        await resumeStateWrite;
      },
    });
    downloadFlow.installMessageHandlers();

    async function injectEntryAndClickGenerate(
      entry: PromptEntry,
      index: number,
      total: number
    ): Promise<HTMLButtonElement | null> {
      // attempt ごとに lastSubmittedEntryIndex を -1 にリセットする。
      // injectWithVerification が silent drop を検知して同一 entry を retry するとき、
      // 前 attempt の click が lastSubmittedEntryIndex に残っていると「投入済み」と誤判定し、
      // retry 中に captcha throw が来た場合に当該 entry を skip するバグ（欠落）を防ぐ (#924)。
      lastSubmittedEntryIndex = -1;
      const { style, lyrics, title } = resolveFields();
      setNativeValue(style, entry.style);
      if (lyrics) {
        // 空文字でも上書きする。instrumental パターン (entry.lyrics === "") のとき前パターンの歌詞を残さない。
        await retryInjectStepWithFallback({
          run: () => setLyricsValue(lyrics, entry.lyrics),
          fallback: async (lastError) => {
            try {
              await setLyricsValueViaBeforeInput(lyrics, entry.lyrics);
            } catch (fallbackError) {
              const message =
                fallbackError instanceof Error
                  ? fallbackError.message
                  : String(fallbackError);
              const actualLyrics =
                lyrics instanceof HTMLTextAreaElement ||
                lyrics instanceof HTMLInputElement
                  ? lyrics.value
                  : (lyrics.textContent ?? "");
              console.error(
                "[suno-helper] Lyrics 欄への全注入方式が失敗しました",
                {
                  entryName: entryDisplayName(entry),
                  lyricsLength: entry.lyrics.length,
                  lyrics: entry.lyrics,
                  actualLength: actualLyrics.length,
                  actualLyrics,
                  diagnosticMessage: message,
                  pasteError: lastError,
                  fallbackError,
                }
              );
              throw new FatalRunError(
                `entry ${index} (${entryDisplayName(entry)}) の Lyrics 注入に失敗しました: ${message}\n${diagnoseLyricsInputState()}`
              );
            }
          },
          isRetryable: (error) => error instanceof LyricsPasteReflectionError,
          maxRetry: BALANCED_RUN_PACING.maxInjectRetry,
          describeStep: () =>
            `entry ${index} (${entryDisplayName(entry)}) Lyrics paste`,
        });
      } else if (entry.lyrics) {
        // 歌詞があるのに Lyrics 欄が見つからないのは設定不整合。silent に飛ばさず停止する。
        // 設定不整合は全 entry で再発するため fatal（entry retry の対象外）。
        throw new FatalRunError(
          `Lyrics 欄が見つかりません。${diagnoseLyricsInputState()}`
        );
      }
      if (title) {
        // Song Title は entry.title 優先、無ければ entry.name で代替する (#844)。
        setNativeValue(title, entry.title ?? entry.name);
      } else {
        // title 欄不在は Suno 側 UI 改装の可能性。style/lyrics と違い fail-soft（警告のみで続行）。
        console.warn(
          "Song Title 欄が見つかりませんでした。タイトル注入を skip して続行します。"
        );
      }
      // Advanced タブ > More Options の 3 フィールド (#900)。slider 注入は MAIN world bridge 経由
      // （React onKeyDown 直接呼び出しで isTrusted チェックを通過、#973）を優先し、失敗時は従来の
      // 合成 keydown dispatch へ縮退する（e2e mock の plain DOM はこちらで動く）。entry に値があり
      // selector が不在なら input / vocal_gender は injectAdvancedFields が throw する (fail-loud)。
      // slider 2 つは throw せず warn + skip し (#1720)、onSliderSkip 経由で GENERATING の status
      // message に載せてユーザーに観測可能にする（サイレント skip の禁止）。値が無ければ skip する
      // (fail-soft、後方互換)。
      const skippedSliders: string[] = [];
      await injectAdvancedFields(entry, resolveAdvancedFields(), {
        bridgeSetSlider: requestSliderSet,
        onSliderSkip: (name) => skippedSliders.push(name),
      });
      await abortableSleep(SETTLE_MS, () => aborted);

      if (aborted) {
        return null; // 停止押下後は Generate を押さない（未投入のまま STOPPED 経路へ）
      }

      assertUnattendedUiIsSafe();

      // captcha が出ていても即停止しない。多くは passive 検証で数秒以内に自動 verify されて閉じるため、
      // waiting-captcha phase で解消を待って自動続行する。解消されない場合のみ throw（fail-loud は維持）。
      await waitForCaptchaClear({
        isAborted: () => aborted,
        pollIntervalMs: POLL_INTERVAL_MS,
        timeoutMs: CAPTCHA_WAIT_TIMEOUT_MS,
        onWaitStart: () =>
          emitProgress({ phase: PHASE.WAITING_CAPTCHA, index, total }),
      });
      if (aborted) {
        return null; // captcha 解消待ち中の停止。Generate を押さない（未投入のまま STOPPED 経路へ）
      }

      const button = resolveGenerateButton();
      button.click();
      // Generate click 直後に lastSubmittedEntryIndex を更新する。中断時の interruptIndex 計算で
      // 「この entry は click 済み（submitted）」と判定できるようにする (#924)。
      lastSubmittedEntryIndex = index;
      // Generate 押下後は最大 GENERATE_TIMEOUT_MS の生成完了待ちに入る。注入中と区別して表示する。
      // slider を warn + skip した場合は message に載せて overlay / popup の status で観測可能にする (#1720)。
      emitProgress({
        phase: PHASE.GENERATING,
        index,
        total,
        ...(skippedSliders.length > 0
          ? {
              message: `${skippedSliders.join(" / ")} slider を skip しました（値は手動設定できます）`,
            }
          : {}),
      });
      return button;
    }

    async function submitEntryToQueue(
      entry: PromptEntry,
      index: number,
      total: number
    ): Promise<void> {
      await injectEntryAndClickGenerate(entry, index, total);
    }

    async function generateEntrySerially(
      entry: PromptEntry,
      index: number,
      total: number
    ): Promise<void> {
      const button = await injectEntryAndClickGenerate(entry, index, total);
      if (button === null) {
        return;
      }
      await waitForGeneration(button, {
        isAborted: () => aborted,
        timeoutMs: GENERATE_TIMEOUT_MS,
        pollIntervalMs: POLL_INTERVAL_MS,
        settleMs: SETTLE_MS,
        captchaWaitTimeoutMs: activeUnattended ? 0 : CAPTCHA_WAIT_TIMEOUT_MS,
        // 生成完了待ち中に captcha が出たら waiting-captcha 表示へ切り替え、解消後 generating へ戻す。
        onCaptchaWait: (waiting) =>
          emitProgress({
            phase: waiting ? PHASE.WAITING_CAPTCHA : PHASE.GENERATING,
            index,
            total,
          }),
      });
    }

    /**
     * 全 clip を multi-select → Cmd+P で Add to Playlist dialog → 名前注入 → Create Playlist の一連を実行する (#854)。
     * 各ステップ間に abortableSleep を挟み、停止押下に素早く反応する。
     */
    // fallow-ignore-next-line complexity
    async function addClipsToPlaylist(
      progressTotal: number,
      playlistName: string,
      previousSubmittedClipIds: string[],
      expectedClipCount: number,
      entries: PromptEntry[],
      order: number[],
      durationFilter: DurationFilter | undefined,
      previousSubmittedClipIdsAreDurationFiltered = false,
      durationOutlierPolicy: DurationOutlierPolicy = { kind: "regenerate" },
      onResolvedPlaylistClipIds?: (
        info: PlaylistClipPersistInfo
      ) => void | Promise<void>
    ): Promise<number> {
      assertUnattendedUiIsSafe();
      const previousPlaylistUrls = activeUnattended
        ? new Set(findPlaylistUrlsByName(document, playlistName))
        : new Set<string>();
      emitProgress({
        phase: PHASE.ADDING_TO_PLAYLIST,
        total: progressTotal,
        message: playlistName,
      });
      const currentSubmittedIds = tracker.getSubmittedIds();
      const allowUnknownDurationIds =
        previousSubmittedClipIdsAreDurationFiltered
          ? new Set(previousSubmittedClipIds)
          : new Set<string>();
      const allSubmittedIds = [
        ...previousSubmittedClipIds,
        ...currentSubmittedIds,
      ];
      const observedCount = new Set(allSubmittedIds).size;
      if (observedCount !== expectedClipCount) {
        console.warn(
          `[suno-helper] bridge observation gap: expected ${expectedClipCount} clip IDs, observed ${observedCount}`
        );
      }
      const rawSubmittedIds = resolvePlaylistClipIds(
        previousSubmittedClipIds,
        currentSubmittedIds,
        expectedClipCount
      );
      const currentTitleFallbackMap = buildTitleFallbackMap(
        entries,
        order,
        currentSubmittedIds
      );
      const currentOrder = new Set(order);
      const previousOrder = entries
        .map((_, index) => index)
        .filter((index) => !currentOrder.has(index));
      const previousTitleFallbackMap = buildTitleFallbackMap(
        entries,
        previousOrder,
        previousSubmittedClipIds
      );
      const titleFallbackMap = new Map([
        ...previousTitleFallbackMap,
        ...currentTitleFallbackMap,
      ]);
      const plan = buildPlaylistClipPlan(
        rawSubmittedIds,
        titleFallbackMap,
        durationFilter,
        allowUnknownDurationIds,
        durationOutlierPolicy
      );
      await onResolvedPlaylistClipIds?.({
        submittedClipIds: plan.clipIds,
        submittedClipIdsAreDurationFiltered:
          durationOutlierPolicy.kind === "regenerate",
        playlistExpectedClipCount: plan.expectedClipCount,
        ...(activeUnattended
          ? { playlistUrlsBeforeCreate: [...previousPlaylistUrls] }
          : {}),
      });
      const selectedCount = await scrollAndMultiSelectByIds(plan.clipIds, {
        isAborted: () => aborted,
        titleFallbackMap: plan.titleFallbackMap,
      });
      if (aborted) {
        return selectedCount;
      }
      if (selectedCount !== plan.expectedClipCount) {
        throw new Error(
          `playlist 対象の DOM 選択数が一致しません: expected ${plan.expectedClipCount}, selected ${selectedCount}`
        );
      }
      await abortableSleep(SETTLE_MS, () => aborted);
      if (aborted) {
        return selectedCount;
      }

      // Cmd+P 直前の保険ガード (#1411 要件4)。完了時リロードが走らなかった経路（クラッシュ等）で
      // 前回 run の stale selection が残っていると、Cmd+P は選択中 clip 全件を playlist 追加対象に
      // するため累積汚染される。実際の選択中 clip を読み取り、target 件数を超えていたら fail-loud で
      // 中断する。判定は件数比較にする: scrollAndMultiSelectByIds の title fallback で選択した row は
      // DOM 上の ID が target 集合に含まれないため、ID 集合差だと誤検知する。
      // 走査は 1 pass + 超過検知での即打ち切りに絞る（クリーンな happy path で毎 run 全 3 pass の
      // コストを払わない）。ガード自身の走査失敗（scroller 不在・render flake での 0 件等）は、
      // 生成完了済みの run を巻き添えにしないため fail-open（警告して続行）とする。
      let actualSelectedIds: string[] | null = null;
      try {
        actualSelectedIds = await readSelectedClipIds({
          isAborted: () => aborted,
          maxScanPasses: 1,
          stopAboveCount: plan.expectedClipCount,
          skipUnresolvedIds: true,
        });
      } catch (err) {
        if (!aborted) {
          console.warn(
            "[suno-helper] stale selection ガードの走査に失敗したためスキップして続行します:",
            err
          );
        }
      }
      if (aborted) {
        return selectedCount;
      }
      if (
        actualSelectedIds !== null &&
        actualSelectedIds.length > plan.expectedClipCount
      ) {
        const targetIdSet = new Set(plan.clipIds);
        const extraIds = actualSelectedIds.filter((id) => !targetIdSet.has(id));
        throw new Error(
          `選択中 clip が playlist 対象より多く、前回実行の選択が残っている可能性があります` +
            `（expected ${plan.expectedClipCount}, selected ${actualSelectedIds.length}）。` +
            `ページをリロードして選択状態を解除してから再実行してください。` +
            `参考: target 集合外の選択中 ID（title fallback で選択した正当な clip を含む場合があります）: ${extraIds.join(", ")}`
        );
      }

      const isMac = navigator.platform.toLowerCase().includes("mac");
      const dialog = await openAddToPlaylistDialogViaCmdP(async () => {
        await sendMessage("sendTrustedCmdP", { isMac });
      });
      await abortableSleep(SETTLE_MS, () => aborted);

      await fillPlaylistNameAndCreate(dialog, playlistName);
      // Suno の Cmd+P dialog 仕様: Create Playlist は空 playlist を作るだけで、
      // 選択中 clip は追加されない。dialog 内 list に出現した新規 row を改めて click して
      // clip を紐付ける（同名 row が複数並ぶ場合は DOM 順で最後 = 直前作成分を選ぶ）。
      await abortableSleep(SETTLE_MS, () => aborted);
      const clickedPlaylistUrl = await clickPlaylistRowByName(
        dialog,
        playlistName
      );
      await waitForPlaylistDialogClose({
        isAborted: () => aborted,
        pollIntervalMs: POLL_INTERVAL_MS,
        timeoutMs: GENERATE_TIMEOUT_MS,
      });
      if (activeUnattended) {
        const playlistUrl =
          clickedPlaylistUrl ??
          (await waitForNewPlaylistUrlByName(
            playlistName,
            previousPlaylistUrls,
            {
              pollIntervalMs: POLL_INTERVAL_MS,
              timeoutMs: GENERATE_TIMEOUT_MS,
            }
          ));
        if (!playlistUrl) {
          throw new Error(
            "作成した Suno playlist URL を確認できないため、download を開始しません。"
          );
        }
        await sendMessage("postDownloaded", {
          baseUrl: activeUnattended.request.baseUrl,
          collectionId: activeUnattended.request.collectionId,
          body: {
            file_count: 0,
            expected_file_count: expectedClipCount,
            format: activeUnattended.request.downloadFormat,
            suno_playlist_url: playlistUrl,
          },
        });
      }
      return selectedCount;
    }

    function resolveDurationFilter(
      durationFilter: DurationFilter | undefined
    ): { minSec: number; maxSec: number } {
      const minSec = durationFilter?.min_sec;
      const maxSec = durationFilter?.max_sec;
      return {
        minSec:
          typeof minSec === "number" && Number.isFinite(minSec)
            ? minSec
            : DEFAULT_DURATION_FILTER.min_sec,
        maxSec:
          typeof maxSec === "number" && Number.isFinite(maxSec)
            ? maxSec
            : DEFAULT_DURATION_FILTER.max_sec,
      };
    }

    function isDurationAccepted(
      clipId: string,
      durationFilter: DurationFilter | undefined,
      allowUnknownDuration = false
    ): boolean {
      const duration = tracker.getDuration(clipId);
      if (duration === undefined) {
        return allowUnknownDuration;
      }
      const filter = resolveDurationFilter(durationFilter);
      return duration >= filter.minSec && duration <= filter.maxSec;
    }

    function buildPlaylistClipPlan(
      rawSubmittedIds: string[],
      titleFallbackMap: Map<string, string>,
      durationFilter: DurationFilter | undefined,
      allowUnknownDurationIds: Set<string> = new Set(),
      durationOutlierPolicy: DurationOutlierPolicy = { kind: "regenerate" }
    ): PlaylistClipPlan {
      const clipIds =
        durationOutlierPolicy.kind === "regenerate"
          ? rawSubmittedIds.filter((clipId) =>
              isDurationAccepted(
                clipId,
                durationFilter,
                allowUnknownDurationIds.has(clipId)
              )
            )
          : [...rawSubmittedIds];
      if (clipIds.length === 0) {
        throw new Error(
          "playlist 対象の OK clip ID が 0 件です。全 clip が duration filter で除外されました。"
        );
      }
      return {
        clipIds,
        expectedClipCount: clipIds.length,
        titleFallbackMap,
      };
    }

    function resolvePlaylistPersistInfo(
      previousSubmittedClipIds: string[],
      currentSubmittedIds: string[],
      durationFilter: DurationFilter | undefined,
      previousSubmittedClipIdsAreDurationFiltered: boolean
    ): PlaylistClipPersistInfo {
      const previousAcceptedIds = previousSubmittedClipIds.filter((clipId) =>
        isDurationAccepted(
          clipId,
          durationFilter,
          previousSubmittedClipIdsAreDurationFiltered
        )
      );
      const currentAcceptedIds = currentSubmittedIds.filter((clipId) =>
        isDurationAccepted(clipId, durationFilter)
      );
      const submittedClipIds = Array.from(
        new Set([...previousAcceptedIds, ...currentAcceptedIds])
      );
      return {
        submittedClipIds,
        submittedClipIdsAreDurationFiltered: true,
        playlistExpectedClipCount: submittedClipIds.length,
      };
    }

    function resolveRawPlaylistPersistInfo(
      previousSubmittedClipIds: string[],
      currentSubmittedIds: string[]
    ): PlaylistClipPersistInfo {
      const submittedClipIds = Array.from(
        new Set([...previousSubmittedClipIds, ...currentSubmittedIds])
      );
      return {
        submittedClipIds,
        submittedClipIdsAreDurationFiltered: false,
        playlistExpectedClipCount: submittedClipIds.length,
      };
    }

    function countQueuePlaylistClipIds(
      previousSubmittedClipIds: string[],
      clipIdsByEntry: Map<number, string[]>
    ): number {
      return new Set([
        ...previousSubmittedClipIds,
        ...Array.from(clipIdsByEntry.values()).flat(),
      ]).size;
    }

    async function evaluateAttemptYield(
      clipIds: string[],
      durationFilter: DurationFilter,
      isAborted: () => boolean
    ) {
      await waitForAttemptClipsComplete(clipIds, {
        getPendingIdsByIds: (ids) => tracker.getPendingIdsByIds(ids),
        requestFeedPoll,
        abortableSleep,
        isAborted,
        now: Date.now,
      });
      return evaluateClips(
        clipIds.map((id) => ({ id, duration: tracker.getDuration(id) })),
        durationFilter
      );
    }

    interface RunOptions {
      // collection 単位 duration guard 閾値 (#1259)。実フィルタは yield guard 側で消費する。
      durationFilter?: DurationFilter;
      // 0-based inclusive な実行範囲 (#872)。未指定は全 entry。判断A: range 指定でも entries 全体と
      // 絶対 index を保ち、range 内の entry だけを処理する（slice 再採番による index ズレを起こさない）。
      range?: RunRange;
      // ERROR 停止時に resume state を紐付ける collection 識別子 (#872)。
      collectionId: string;
      // collection mode のときの playlist 名 (#854)。全 entry 完了後の clip 一括追加に使う。
      playlistName: string;
      runMode: RunModeId;
      // 任意の部分実行対象の 0-based index 列。チェック選択や失敗分再実行で使う。指定時は range より優先。
      indices?: number[];
      // 再開前の run で観測済みの playlist 対象 clip ID。
      submittedClipIds?: string[];
      // true のとき submittedClipIds は resume 保存時点で OK clip IDs に正規化済み。
      submittedClipIdsAreDurationFiltered?: boolean;
      // duration filter 後に playlist 追加・download へ採用する OK clip 件数。
      playlistExpectedClipCount?: number;
      durationOutlierPolicy: DurationOutlierPolicy;
      unattended?: RunPayload["unattended"];
    }

    async function runAll(
      entries: PromptEntry[],
      options: RunOptions
    ): Promise<void> {
      const {
        range,
        collectionId,
        playlistName,
        submittedClipIds,
        playlistExpectedClipCount,
        unattended,
      } = options;
      const previousSubmittedClipIds = submittedClipIds ?? [];
      const pacing = BALANCED_RUN_PACING;
      try {
        const baseUrl = await serverUrlItem.getValue();
        await sendMessage("fetchCollectionPromptResponse", {
          baseUrl,
          collectionId,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        emitProgress({
          phase: PHASE.ERROR,
          index: 0,
          total: entries.length,
          message: `collection server から実行対象を取得できません。server が起動し、collection が利用可能か確認してください: ${message}`,
        });
        return;
      }
      // Suno 同時生成キューに積める clip 数の上限（Balanced の並列リクエスト数 × 2 clip）。
      const maxGeneratingClips =
        Math.min(
          pacing.maxInflightRequests,
          unattended?.request.limits.maxConcurrentGenerations ??
            pacing.maxInflightRequests
        ) * CLIPS_PER_REQUEST;
      const retryLimit = unattended?.request.limits.maxRetries;
      const injectRetryLimit =
        retryLimit === undefined
          ? pacing.maxInjectRetry
          : Math.min(pacing.maxInjectRetry, retryLimit);
      const yieldRetryLimit = retryLimit ?? MAX_YIELD_RETRY;
      const total = entries.length;
      if (total === 0) {
        emitProgress({ phase: PHASE.FINISHED, total });
        return;
      }
      const startIndex = range ? range.start : 0;
      const endIndex = range ? range.end : total - 1;
      // 実行対象の 0-based index 列。indices（チェック選択/失敗分再実行）が最優先、無ければ range 由来。
      const order =
        options.indices ??
        Array.from(
          { length: endIndex - startIndex + 1 },
          (_, k) => startIndex + k
        );
      const hasExplicitIndices = options.indices !== undefined;
      const expectedRawPlaylistClipCount =
        order.length === 0
          ? (playlistExpectedClipCount ?? total * CLIPS_PER_REQUEST)
          : new Set(previousSubmittedClipIds).size +
            order.length * CLIPS_PER_REQUEST;
      const shouldRunDownloadAfterPlaylist =
        expectedRawPlaylistClipCount >= total * CLIPS_PER_REQUEST;
      // リトライ上限まで失敗しスキップした entry の 0-based index (#948)。終了時に resume state へ
      // 永続化し、popup の「失敗分のみ再実行」導線が消費する。
      const failedIndices: number[] = [];
      // stall タイムアウトで生成停滞と判定した entry の 0-based index (#1994)。failedIndices にも
      // 追加して resume/retry 導線へ渡すが、stall のみの失敗では完了済み clip で playlist 追加・
      // download を続行するため、finishWithFailedEntriesIfNeeded の保留判定からは除外する。
      const stalledEntryIndices: number[] = [];
      let queueClipIdsByEntry: Map<number, string[]> | null = null;
      let keepResumeStateForDownloadRetry = false;
      let playlistPersistInfo: PlaylistClipPersistInfo | null = null;
      // 中断 entry を永続化し、reload 後の ResumeBanner で続きから再開できるようにする。
      // ERROR phase (#872 要件3) と STOPPED phase (#898 要件1/2/3) の共通処理。failedIndex 名は
      // そのまま流用し (要件3)、中断 index を載せる。
      // スキップ済み failedIndices があれば一緒に永続化する (#948)。
      function persistInterruptState(
        interruptedIndex: number,
        orderPosition?: number,
        explicitRemainingIndices?: number[],
        propagateWriteError = false
      ): void {
        const remainingIndices =
          explicitRemainingIndices ??
          (hasExplicitIndices && orderPosition !== undefined
            ? order.slice(
                interruptedIndex === order[orderPosition]
                  ? orderPosition
                  : orderPosition + 1
              )
            : undefined);
        const currentSubmittedIds = tracker.getSubmittedIds();
        const regenerateDurationOutliers =
          options.durationOutlierPolicy.kind === "regenerate";
        const fallbackPlaylistPersistInfo = !regenerateDurationOutliers
          ? resolveRawPlaylistPersistInfo(
              previousSubmittedClipIds,
              currentSubmittedIds
            )
          : options.runMode === "queue"
            ? resolveRawPlaylistPersistInfo(
                previousSubmittedClipIds,
                currentSubmittedIds
              )
            : resolvePlaylistPersistInfo(
                previousSubmittedClipIds,
                currentSubmittedIds,
                options.durationFilter,
                options.submittedClipIdsAreDurationFiltered === true
              );
        const playlistSubmittedClipIds =
          playlistPersistInfo?.submittedClipIds ??
          fallbackPlaylistPersistInfo.submittedClipIds;
        const submittedClipIdsAreDurationFiltered =
          playlistPersistInfo?.submittedClipIdsAreDurationFiltered ??
          fallbackPlaylistPersistInfo.submittedClipIdsAreDurationFiltered;
        const playlistExpectedCount =
          playlistPersistInfo?.playlistExpectedClipCount ??
          fallbackPlaylistPersistInfo.playlistExpectedClipCount;
        currentSnapshot =
          currentSnapshot === null
            ? currentSnapshot
            : {
                ...currentSnapshot,
                failedIndex: interruptedIndex,
                remainingIndices,
                submittedClipIds: playlistSubmittedClipIds,
                durationFilter: options.durationFilter,
                submittedClipIdsAreDurationFiltered,
                playlistExpectedClipCount: playlistExpectedCount,
                regenerateDurationOutliers,
                durationOutlierWarnings:
                  currentSnapshot.durationOutlierWarnings,
              };
        resumeStateWrite = resumeStateWrite.then(() =>
          writeResumeState({
            collectionId,
            failedIndex: interruptedIndex,
            total,
            timestamp: Date.now(),
            failedIndices:
              failedIndices.length > 0 ? [...failedIndices] : undefined,
            remainingIndices,
            submittedClipIds: playlistSubmittedClipIds,
            durationFilter: options.durationFilter,
            submittedClipIdsAreDurationFiltered,
            playlistExpectedClipCount: playlistExpectedCount,
            runMode: options.runMode,
            regenerateDurationOutliers,
            durationOutlierWarnings: currentSnapshot?.durationOutlierWarnings,
            playlistUrlsBeforeCreate:
              playlistPersistInfo?.playlistUrlsBeforeCreate,
          })
        );
        if (!propagateWriteError) {
          resumeStateWrite = resumeStateWrite.catch((error: unknown) => {
            console.warn(
              "[suno-helper] resume checkpoint の永続化に失敗しました:",
              error
            );
          });
        }
      }

      function finishDeferringPlaylistForFailedEntries(): void {
        persistInterruptState(total);
        const list = failedIndices.map((i) => i + 1).join(", ");
        emitProgress({
          phase: PHASE.FINISHED,
          total,
          message: `${failedIndices.length} 件の entry が失敗しました (entry ${list})。「失敗分のみ再実行」で完走後に playlist 追加が実行されます。`,
        });
      }

      function finishWithFailedEntriesIfNeeded(): boolean {
        if (failedIndices.length === 0) return false;
        if (unattended) {
          finishDeferringPlaylistForFailedEntries();
          return true;
        }
        // stall 由来の失敗だけなら playlist 追加を保留しない (#1994)。完了済み clip での
        // graceful degradation（playlist 追加 / download の続行）を優先する。
        const stalledSet = new Set(stalledEntryIndices);
        if (failedIndices.every((i) => stalledSet.has(i))) {
          return false;
        }
        finishDeferringPlaylistForFailedEntries();
        return true;
      }

      async function waitForQueueCapacity(
        index: number,
        yieldRetryCount: number
      ): Promise<void> {
        emitProgress({
          phase: PHASE.WAITING_SLOT,
          index,
          total,
          message: tracker.hasObservedAnyTraffic()
            ? undefined
            : "bridge 未観測: DOM 計数で待機中",
          yieldRetryCount,
        });
        await waitForQueueSlot(maxGeneratingClips, {
          isAborted: () => aborted,
          pollIntervalMs: POLL_INTERVAL_MS,
          timeoutMs: QUEUE_SLOT_WAIT_TIMEOUT_MS,
          queueErrorWaitMs: QUEUE_ERROR_WAIT_MS,
          getCount: currentInFlightCount,
          getLastChangeAt: () => tracker.lastChangeAt(),
          stallTimeoutMs: INFLIGHT_STALL_TIMEOUT_MS,
        });
      }

      if (options.runMode === "queue") {
        const result = await submitQueueEntries({
          entries,
          order,
          total,
          maxGeneratingClips,
          preset: {
            ...pacing,
            maxInjectRetry: injectRetryLimit,
            maxEntryRetry: retryLimit ?? pacing.maxEntryRetry,
          },
          isAborted: () => aborted,
          isEntrySubmitted: (index) => lastSubmittedEntryIndex === index,
          getSubmittedIds: () => tracker.getSubmittedIds(),
          getSubmissionCount: () => tracker.submissionCount(),
          getDomInFlightCount: getInFlightClipCount,
          hasObservedAnyTraffic: () => tracker.hasObservedAnyTraffic(),
          getLastChangeAt: () => tracker.lastChangeAt(),
          currentInFlightCount,
          emitProgress,
          submitEntryToQueue,
          waitForAck,
          waitForQueueSlot,
          persistInterruptState,
          applyJitter,
          abortableSleep,
          sleep,
        });
        queueClipIdsByEntry = result.clipIdsByEntry;
        failedIndices.push(...result.failedIndices);
        if (!result.completed) {
          return;
        }
      }
      if (options.runMode === "serial") {
        for (const [orderPosition, i] of order.entries()) {
          if (aborted) {
            // ループ先頭の中断: この時点でまだ Generate を click していないため i をそのまま使う (#924)。
            persistInterruptState(i, orderPosition);
            emitProgress({ phase: PHASE.STOPPED, index: i, total });
            return;
          }
          let yieldRetryCount = 0;
          for (;;) {
            const submittedStart = tracker.getSubmittedIds().length;
            // 1 entry の実行を失敗分類つきで包む (#948)。一時的な失敗は Balanced の maxEntryRetry 回まで
            // 同一 entry を再試行し、それでも失敗ならスキップして次へ（run 全体は止めない）。
            const result = await runEntryWithRetry({
              attempt: async () => {
                // Suno のキュー上限（20 clip）を超えると後続が silent fail するため、投入前に空きを待つ。
                // bridge 無観測の縮退中は message で明示する (#948 PR4: DOM プロキシは過大カウントしうるため
                // 「待ちが長い」原因をユーザーが切り分けられるようにする)。
                await waitForQueueCapacity(i, yieldRetryCount);
                if (aborted) {
                  return; // 中断は直後の outcome 判定で STOPPED 経路へ
                }
                emitProgress({
                  phase: PHASE.INJECTING,
                  index: i,
                  total,
                  yieldRetryCount,
                });
                // inject 後に受理（ACK）を検証し、silent drop なら同じ entry を retry する (#864 root cause 3)。
                // ACK は bridge の generate レスポンス観測 OR DOM 増分のハイブリッド (#948)。
                await injectWithVerification({
                  inject: () => generateEntrySerially(entries[i], i, total),
                  markBeforeInject: () =>
                    markAck({
                      getSubmissionCount: () => tracker.submissionCount(),
                      getDomInFlightCount: getInFlightClipCount,
                      sleep,
                    }),
                  waitForAck,
                  isAborted: () => aborted,
                  maxRetry: injectRetryLimit,
                  ackTimeoutMs: pacing.injectAckTimeoutMs,
                  pollIntervalMs: POLL_INTERVAL_MS,
                  describeEntry: () =>
                    `entry ${i} (${entryDisplayName(entries[i])})`,
                });
              },
              isAborted: () => aborted,
              // Generate click 済みで受理失敗確定でないエラー（典型: 生成完了待ち timeout）は再実行すると
              // 重複生成になるため presumed-done（resolveInterruptIndex の i+1 判断と同じ）。
              wasSubmitted: (err) =>
                lastSubmittedEntryIndex === i &&
                !(err instanceof InjectNotAcknowledgedError),
              isFatal: (err) => err instanceof FatalRunError,
              maxRetry:
                unattended?.request.limits.maxRetries ?? pacing.maxEntryRetry,
              retryDelayMs: () =>
                applyJitter(pacing.interCreateDelayMs, pacing.jitterMs),
              onRetry: (attempt, max) =>
                emitProgress({
                  phase: PHASE.WAITING_SLOT,
                  index: i,
                  total,
                  yieldRetryCount,
                  log: {
                    kind: "retry",
                    entryName: entryDisplayName(entries[i]),
                    attempt,
                    max,
                  },
                }),
              sleep: abortableSleep,
              describeEntry: () =>
                `entry ${i} (${entryDisplayName(entries[i])})`,
            });
            if (result.outcome === "fatal") {
              const message =
                result.error instanceof Error
                  ? result.error.message
                  : String(result.error);
              // interruptIndex: submitted（Generate click 済み）かつ silent drop 確定でない → i+1（重複しない）。
              // emitProgress の index も interruptIndex にする: snapshot.applyProgress が ERROR payload の
              // index を failedIndex として記録し、popup が chrome.storage 喪失時の冗長ソースに使うため (#924)。
              const interruptIndex = resolveInterruptIndex(
                i,
                lastSubmittedEntryIndex === i,
                result.error instanceof InjectNotAcknowledgedError
              );
              persistInterruptState(interruptIndex, orderPosition);
              await resumeStateWrite;
              emitProgress({
                phase: PHASE.ERROR,
                index: interruptIndex,
                total,
                message,
              });
              return;
            }
            if (result.outcome === "aborted" || aborted) {
              // attempt 中の中断（waitForQueueSlot / injectEntryAndClickGenerate 内の silent return 含む）。
              // Generate click 済みなら i+1 を persist し再開時の重複生成を防ぐ (#924)。
              const interruptIndex = resolveInterruptIndex(
                i,
                lastSubmittedEntryIndex === i,
                false
              );
              persistInterruptState(interruptIndex, orderPosition);
              emitProgress({
                phase: PHASE.STOPPED,
                index: interruptIndex,
                total,
              });
              return;
            }
            if (result.outcome === "failed") {
              const message =
                result.error instanceof Error
                  ? result.error.message
                  : String(result.error);
              failedIndices.push(i);
              console.warn(
                `[suno-helper] entry ${i} をスキップして続行します: ${message}`
              );
              emitProgress({
                phase: PHASE.ENTRY_FAILED,
                index: i,
                total,
                message,
                yieldRetryCount,
                log: { kind: "skip", entryName: entryDisplayName(entries[i]) },
              });
              break; // run 全体は止めない。次 entry へ。
            }
            if (result.outcome === "presumed-done") {
              const message =
                result.error instanceof Error
                  ? result.error.message
                  : String(result.error);
              console.warn(
                `[suno-helper] entry ${i} は投入済みのため生成済み扱いで続行します: ${message}`
              );
              emitProgress({
                phase: PHASE.DONE,
                index: i,
                total,
                yieldRetryCount,
              });
              break;
            }

            const attemptClipIds = tracker
              .getSubmittedIds()
              .slice(submittedStart);
            if (attemptClipIds.length === 0) {
              console.warn(
                `[suno-helper] entry ${i} の clip ID を bridge で観測できなかったため duration guard を skip します。`
              );
              emitProgress({
                phase: PHASE.DONE,
                index: i,
                total,
                yieldRetryCount,
              });
              break;
            }
            const durationFilter =
              options.durationFilter ?? DEFAULT_DURATION_FILTER;
            let attemptResult;
            try {
              const evaluation = await evaluateAttemptYield(
                attemptClipIds,
                durationFilter,
                () => aborted
              );
              if (aborted) {
                const interruptIndex = resolveInterruptIndex(
                  i,
                  lastSubmittedEntryIndex === i,
                  false
                );
                persistInterruptState(interruptIndex, orderPosition);
                emitProgress({
                  phase: PHASE.STOPPED,
                  index: interruptIndex,
                  total,
                });
                return;
              }
              attemptResult = { kind: "evaluated" as const, evaluation };
            } catch (err) {
              attemptResult = {
                kind: "evaluation-failed" as const,
                message: err instanceof Error ? err.message : String(err),
              };
            }

            if (aborted) {
              const interruptIndex = resolveInterruptIndex(
                i,
                lastSubmittedEntryIndex === i,
                false
              );
              persistInterruptState(interruptIndex, orderPosition);
              emitProgress({
                phase: PHASE.STOPPED,
                index: interruptIndex,
                total,
              });
              return;
            }
            const decision = decideDurationAttempt({
              clipIds: attemptClipIds,
              result: attemptResult,
              filter: durationFilter,
              policy: options.durationOutlierPolicy,
              attemptCount: yieldRetryCount,
              maxRetry: yieldRetryLimit,
            });
            if (decision.kind === "accept") {
              tracker.markAccepted(decision.acceptedClipIds);
              if (decision.warning) {
                console.warn(`[suno-helper] entry ${i}: ${decision.warning}`);
              }
              emitProgress({
                phase: PHASE.DONE,
                index: i,
                total,
                ...(decision.warning ? { message: decision.warning } : {}),
                ...(decision.warning
                  ? { durationOutlierWarning: decision.warning }
                  : {}),
                yieldRetryCount,
                acceptedClipIds: decision.acceptedClipIds,
              });
              break;
            }
            if (decision.kind === "retry") {
              tracker.dropSubmittedIds(attemptClipIds);
              yieldRetryCount += 1;
              console.warn(
                `[suno-helper] entry ${i} duration guard NG、同一 prompt で再生成します (${yieldRetryCount}/${yieldRetryLimit}): ${decision.message}`
              );
              emitProgress({
                phase: PHASE.WAITING_SLOT,
                index: i,
                total,
                message: `${decision.message}; retry ${yieldRetryCount}/${yieldRetryLimit}`,
                yieldRetryCount,
                log: {
                  kind: "retry",
                  entryName: entryDisplayName(entries[i]),
                  attempt: yieldRetryCount,
                  max: yieldRetryLimit,
                },
              });
              await abortableSleep(
                applyJitter(pacing.interCreateDelayMs, pacing.jitterMs),
                () => aborted
              );
              continue;
            }
            tracker.dropSubmittedIds(attemptClipIds);
            failedIndices.push(i);
            console.warn(
              `[suno-helper] entry ${i} は duration guard ${decision.reason === "evaluation" ? "評価失敗" : "全滅"}のためスキップします: ${decision.message}`
            );
            emitProgress({
              phase: PHASE.ENTRY_FAILED,
              index: i,
              total,
              message: decision.message,
              yieldRetryCount,
              log: { kind: "skip", entryName: entryDisplayName(entries[i]) },
            });
            break;
          }
          // Create→clip-row DOM 反映ラグによる過剰投入 (race) を避けるため、次の投入前に間隔を空ける (#847)。
          // Balanced の基準間隔に ±jitter を加えて bot 判定の固定間隔シグナルを消す。毎回 fresh 算出する。
          await abortableSleep(
            applyJitter(pacing.interCreateDelayMs, pacing.jitterMs),
            () => aborted
          );
        }
      }
      if (unattended && unattended.deferredIndices.length > 0) {
        persistInterruptState(
          unattended.deferredIndices[0],
          undefined,
          unattended.deferredIndices
        );
        emitProgress({
          phase: PHASE.STOPPED,
          index: unattended.deferredIndices[0],
          total,
          message: `定期実行の entry 上限 ${unattended.request.limits.maxEntries} 件に到達しました`,
        });
        return;
      }
      // スキップした失敗 entry が残っている場合は playlist 追加を保留して終了する (#948)。
      // 失敗分のみ再実行して完走した run が playlist 追加を実行する（同名 playlist の重複作成と
      // 歯抜け playlist を防ぐ）。failedIndex=total で persist し、failedIndices を再実行導線へ渡す。
      if (finishWithFailedEntriesIfNeeded()) {
        return;
      }
      if (
        unattended &&
        expectedRawPlaylistClipCount < total * CLIPS_PER_REQUEST
      ) {
        persistInterruptState(total);
        emitProgress({
          phase: PHASE.STOPPED,
          total,
          message:
            "選択 entry の生成は完了しました。collection 全 entry が揃うまで playlist/download を開始しません。",
        });
        return;
      }
      const expectedPlaylistClipCount =
        options.runMode === "queue" && queueClipIdsByEntry !== null
          ? countQueuePlaylistClipIds(
              previousSubmittedClipIds,
              queueClipIdsByEntry
            )
          : expectedRawPlaylistClipCount;
      let verifiedPlaylistClipCount =
        playlistExpectedClipCount ?? expectedPlaylistClipCount;
      let playlistTargetClipCount = expectedPlaylistClipCount;
      if (aborted) {
        persistInterruptState(total);
        emitProgress({ phase: PHASE.STOPPED, total });
        return;
      }
      try {
        const completion = await waitForSubmittedClipsComplete({
          expectedClipCount: expectedPlaylistClipCount,
          previousSubmittedClipIds,
          isAborted: () => aborted,
          getSubmittedIds: () => tracker.getSubmittedIds(),
          getPendingIdsByIds: (ids) => tracker.getPendingIdsByIds(ids),
          getPendingSubmittedIds: () => tracker.getPendingSubmittedIds(),
          requestFeedPoll,
          abortableSleep,
        });
        if (completion.timedOut) {
          const stallMessage =
            completion.message ?? "生成完了待ちがタイムアウトしました";
          const degraded =
            options.runMode === "queue" && queueClipIdsByEntry !== null
              ? resolveStalledQueueEntries(
                  completion.stalledClipIds,
                  queueClipIdsByEntry
                )
              : null;
          if (
            degraded === null ||
            degraded.unmappedStalledClipIds.length > 0 ||
            queueClipIdsByEntry === null
          ) {
            // serial mode / resume 由来 clip の stall は entry へ対応付けられず「失敗分のみ再実行」で
            // 回収できないため、従来どおりラン全体を中断する (#1994)。
            persistInterruptState(total);
            emitProgress({
              phase: PHASE.ERROR,
              index: total,
              total,
              message: stallMessage,
            });
            return;
          }
          // queue mode の graceful degradation (#1994): stall した entry を失敗として記録し、
          // 完了済み clip で duration yield guard / playlist 追加 / download を続行する。
          // entry は clip 単位でなく丸ごと落とす（片割れだけ残すと「失敗分のみ再実行」の
          // entry 単位再生成で完了済み clip が重複するため）。
          for (const index of degraded.stalledEntryIndices) {
            const entryClipIds = queueClipIdsByEntry.get(index) ?? [];
            tracker.dropSubmittedIds(entryClipIds);
            queueClipIdsByEntry.delete(index);
            stalledEntryIndices.push(index);
            failedIndices.push(index);
            console.warn(
              `[suno-helper] entry ${index} は生成停滞のためスキップします: ${stallMessage}`
            );
            emitProgress({
              phase: PHASE.ENTRY_FAILED,
              index,
              total,
              message: "生成が停滞したためスキップしました (stall timeout)",
              yieldRetryCount: 0,
              log: {
                kind: "skip",
                entryName: entryDisplayName(entries[index]),
              },
            });
          }
          playlistTargetClipCount = countQueuePlaylistClipIds(
            previousSubmittedClipIds,
            queueClipIdsByEntry
          );
          verifiedPlaylistClipCount = playlistTargetClipCount;
          if (playlistTargetClipCount === 0) {
            // 完了済み clip が 1 件も無い（全 entry stall）。playlist 追加対象が無いため
            // 従来の失敗保留と同じく「失敗分のみ再実行」導線へ委ねる。
            finishDeferringPlaylistForFailedEntries();
            return;
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        persistInterruptState(total);
        emitProgress({ phase: PHASE.ERROR, index: total, total, message });
        return;
      }
      // stall でスキップした entry は生成物が無いため、yield finalize と playlist の title fallback
      // （order と clip ID の位置対応）から除外する (#1994)。
      const stalledEntrySet = new Set(stalledEntryIndices);
      const completedOrder =
        stalledEntryIndices.length > 0
          ? order.filter((i) => !stalledEntrySet.has(i))
          : order;
      if (aborted) {
        persistInterruptState(total);
        emitProgress({ phase: PHASE.STOPPED, total });
        return;
      }
      if (options.runMode === "queue") {
        if (queueClipIdsByEntry === null) {
          throw new Error(
            "queue clip ID mapping is required before queue yield finalization"
          );
        }
        const durationOutlierStrategy =
          options.durationOutlierPolicy.kind === "retain"
            ? options.durationOutlierPolicy
            : {
                kind: "regenerate" as const,
                regenerateEntry: async (index: number, attempt: number) => {
                  const submittedBefore = new Set(tracker.getSubmittedIds());
                  await waitForQueueCapacity(index, attempt);
                  if (aborted) {
                    return [];
                  }
                  emitProgress({
                    phase: PHASE.INJECTING,
                    index,
                    total,
                    yieldRetryCount: attempt,
                  });
                  await injectWithVerification({
                    inject: () =>
                      generateEntrySerially(entries[index], index, total),
                    markBeforeInject: () =>
                      markAck({
                        getSubmissionCount: () => tracker.submissionCount(),
                        getDomInFlightCount: getInFlightClipCount,
                        sleep,
                      }),
                    waitForAck,
                    isAborted: () => aborted,
                    maxRetry: injectRetryLimit,
                    ackTimeoutMs: pacing.injectAckTimeoutMs,
                    pollIntervalMs: POLL_INTERVAL_MS,
                    describeEntry: () =>
                      `entry ${index} (${entryDisplayName(entries[index])})`,
                  });
                  return tracker
                    .getSubmittedIds()
                    .filter((id) => !submittedBefore.has(id));
                },
                waitForRegeneratedClips: async (
                  regeneratedClipIds: string[]
                ) => {
                  await waitForAttemptClipsComplete(regeneratedClipIds, {
                    getPendingIdsByIds: (ids) =>
                      tracker.getPendingIdsByIds(ids),
                    requestFeedPoll,
                    abortableSleep,
                    isAborted: () => aborted,
                    now: Date.now,
                  });
                },
              };
        const yieldResult = await finalizeQueueEntriesYield({
          entries,
          order: completedOrder,
          total,
          clipIdsByEntry: queueClipIdsByEntry,
          durationFilter: options.durationFilter,
          durationOutlierStrategy,
          getDuration: (id) => tracker.getDuration(id),
          markAccepted: (ids) => tracker.markAccepted(ids),
          dropSubmittedIds: (ids) => tracker.dropSubmittedIds(ids),
          emitProgress,
          isAborted: () => aborted,
          maxYieldRetries: yieldRetryLimit,
        });
        if (yieldResult.abortedIndex !== undefined) {
          const abortedOrderPosition = order.indexOf(yieldResult.abortedIndex);
          if (abortedOrderPosition < 0) {
            throw new Error(
              `queue yield aborted outside run order: entry ${yieldResult.abortedIndex}`
            );
          }
          const interruptedClipIds = order
            .slice(abortedOrderPosition)
            .flatMap((index) => queueClipIdsByEntry?.get(index) ?? []);
          tracker.dropSubmittedIds(interruptedClipIds);
          persistInterruptState(
            yieldResult.abortedIndex,
            undefined,
            order.slice(abortedOrderPosition)
          );
          emitProgress({
            phase: PHASE.STOPPED,
            index: yieldResult.abortedIndex,
            total,
          });
          return;
        }
        failedIndices.push(...yieldResult.failedIndices);
        if (finishWithFailedEntriesIfNeeded()) {
          return;
        }
      }
      try {
        verifiedPlaylistClipCount = await addClipsToPlaylist(
          total,
          playlistName,
          previousSubmittedClipIds,
          playlistTargetClipCount,
          entries,
          completedOrder,
          options.durationFilter,
          options.submittedClipIdsAreDurationFiltered === true,
          options.durationOutlierPolicy,
          async (info) => {
            playlistPersistInfo = info;
            if (unattended) {
              // playlist create は不可逆。定期実行では clip IDs と作成前 URL baseline の
              // durable checkpoint が成功した場合だけ先へ進む。
              persistInterruptState(total, undefined, undefined, true);
              await resumeStateWrite;
            }
          }
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        if (message.includes("playlist 対象の OK clip ID が 0 件")) {
          playlistPersistInfo = {
            submittedClipIds: [],
            submittedClipIdsAreDurationFiltered: true,
            playlistExpectedClipCount: 0,
          };
        }
        persistInterruptState(total);
        emitProgress({ phase: PHASE.ERROR, index: total, total, message });
        return;
      }
      if (aborted) {
        persistInterruptState(total);
        emitProgress({ phase: PHASE.STOPPED, total });
        return;
      }

      // --- DOWNLOADING phase (#1146) ---
      if (shouldRunDownloadAfterPlaylist) {
        persistInterruptState(total);
        try {
          const downloadContext = await resolveDownloadContext(
            unattended?.request.downloadFormat
          );
          assertUnattendedUiIsSafe();
          const downloadError = await downloadFlow.downloadBestEffort(
            downloadContext,
            collectionId,
            total,
            verifiedPlaylistClipCount
          );
          keepResumeStateForDownloadRetry = downloadError !== null;
          if (downloadError !== null) {
            emitProgress({
              phase: PHASE.ERROR,
              index: total,
              total,
              message: downloadError,
            });
            return;
          }
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          keepResumeStateForDownloadRetry = true;
          emitProgress({ phase: PHASE.ERROR, index: total, total, message });
          return;
        }
      }
      if (aborted) {
        persistInterruptState(total);
        emitProgress({ phase: PHASE.STOPPED, total });
        return;
      }
      // stall でスキップした entry が残る partial complete (#1994)。完了分の playlist 追加・
      // download は実行済み。stalled entry を「失敗分のみ再実行」導線へ渡すため resume state を
      // 保持し、消去も完了時リロードも行わない。
      if (stalledEntryIndices.length > 0) {
        persistInterruptState(total);
        const list = stalledEntryIndices.map((i) => i + 1).join(", ");
        emitProgress({
          phase: PHASE.FINISHED,
          total,
          message: `${stalledEntryIndices.length} 件の entry が生成停滞のため失敗しました (entry ${list})。完了分の playlist 追加とダウンロードは実行済みです。「失敗分のみ再実行」で残りを生成できます。`,
        });
        return;
      }
      // 全 entry 完了。この collection の resume state を消去する (#872 要件5)。
      // リロード前に消去完了を await する (#1411 要件3): 逆順だとリロード後の
      // ResumeBanner が「中断からの再開」と誤判定する。消去に失敗しても FINISHED は
      // 維持し（void 時代からの不変条件: 終端 phase を必ず出す）、誤判定を避けるため
      // リロードのみ見送る。残る stale selection は次 run の Cmd+P 前ガードが検知する。
      try {
        await verifyUnattendedCompletion(unattended);
      } catch (error) {
        persistInterruptState(total);
        emitProgress({
          phase: PHASE.ERROR,
          total,
          message: error instanceof Error ? error.message : String(error),
        });
        return;
      }
      let resumeStateCleared = true;
      if (!keepResumeStateForDownloadRetry) {
        try {
          await clearResumeStateForCollection(collectionId);
        } catch (err) {
          resumeStateCleared = false;
          console.warn(
            "[suno-helper] resume state の消去に失敗しました。完了時リロードを見送ります:",
            err
          );
        }
      }
      emitProgress({ phase: PHASE.FINISHED, total });
      // run 一式完了時リロード (#1411 要件2)。playlist 追加で作った multi-select 状態は
      // Suno 内部 state に残り、同一タブの次 run の Cmd+P に混入するためページごと破棄する。
      // collection mode の run は playlist phase を実行するため対象。
      // リロード前に FINISHED snapshot を退避し、popup 再 open 時の完了結果表示を引き継ぐ。
      if (
        playlistName &&
        resumeStateCleared &&
        (await persistFinishedSnapshotForReload())
      ) {
        scheduleRunCompleteReload();
      }
    }

    onMessage("run", ({ data }) => {
      // 二重実行ガード (#892 要件7)。実行中の run 再着信は no-op で ack のみ返す（再開連打対策）。
      if (running) {
        return { ok: false, busy: true } as const;
      }
      const {
        entries,
        playlistName,
        durationFilter,
        range,
        collectionId,
        runMode,
        regenerateDurationOutliers,
        durationOutlierWarnings,
        indices,
        submittedClipIds,
        submittedClipIdsAreDurationFiltered,
        playlistExpectedClipCount,
        unattended,
      } = assertRunPayload(data);
      // 手動 run では過去の定期実行 state を更新しない。定期実行だけが明示的に
      // active context を設定し、以降の progress を checkpoint へ反映する。
      activeUnattended = unattended;
      const durationOutlierPolicy: DurationOutlierPolicy =
        regenerateDurationOutliers
          ? { kind: "regenerate" }
          : { kind: "retain" };
      // 直前 run の完了時リロードが保留中なら取り消す (#1411)。猶予中に受理した新 run を
      // リロードが巻き添えに殺すと STOPPED/ERROR も resume state も残らない。取り消しで
      // 残る stale selection は Cmd+P 前ガードが検知する。
      cancelScheduledRunCompleteReload();
      currentSnapshot = initSnapshot(entries, {
        collectionId,
        playlistName,
        durationFilter,
        regenerateDurationOutliers,
        durationOutlierWarnings,
      });
      // 新 run 開始で直近完了 run の退避 snapshot を消去する（前 run の完了表示が復元されるのを防ぐ）。
      // in-memory の currentSnapshot が queryProgress で優先されるため fire-and-forget でよい。
      void clearFinishedSnapshot();
      if (detectSunoViewMode() === "unknown") {
        const message =
          "Suno の表示ビューを検出できません。List / Waveform / Grid のいずれかに切り替えてから再実行してください。";
        emitProgress({
          phase: PHASE.ERROR,
          total: entries.length,
          message,
        });
        return (async () => {
          await Promise.all([resumeStateWrite, unattendedStateWrite]);
          await releaseExecutionLease(unattended);
          activeUnattended = undefined;
          return { ok: false, error: message } as const;
        })();
      }
      if (!acquireRunLock()) {
        return { ok: false, busy: true } as const;
      }
      running = true;
      aborted = false;
      lastSubmittedEntryIndex = -1;
      tracker.clearSubmittedIds();
      // run 中のみ active feed poll で clip status を追う (#948)。passive 観測が生きていれば
      // poller は stale 判定で自発的に黙る（intervalMs ごとの no-op tick のみ）。
      feedPoller.start();
      void runAll(entries, {
        durationFilter,
        range,
        collectionId,
        playlistName,
        runMode,
        durationOutlierPolicy,
        indices,
        submittedClipIds,
        submittedClipIdsAreDurationFiltered,
        playlistExpectedClipCount,
        unattended,
      }).finally(async () => {
        running = false;
        await Promise.all([resumeStateWrite, unattendedStateWrite]);
        await releaseExecutionLease(unattended);
        activeUnattended = undefined;
        feedPoller.stop();
        releaseRunLock();
      });
      return { ok: true } as const;
    });

    onMessage("stop", () => {
      aborted = true;
      return { ok: true } as const;
    });

    onMessage("retryPlaylist", ({ data }) => {
      if (running) {
        return { ok: false, busy: true } as const;
      }
      const {
        playlistName,
        submittedClipIds,
        expectedClipCount,
        collectionId,
        durationFilter,
        regenerateDurationOutliers,
        durationOutlierWarnings,
        submittedClipIdsAreDurationFiltered,
        shouldDownload,
        unattended,
      } = assertRetryPlaylistPayload(data);
      const durationOutlierPolicy: DurationOutlierPolicy =
        regenerateDurationOutliers
          ? { kind: "regenerate" }
          : { kind: "retain" };
      if (!acquireRunLock()) {
        return { ok: false, busy: true } as const;
      }
      activeUnattended = unattended;
      currentSnapshot = initSnapshot([], {
        collectionId,
        playlistName,
        durationFilter,
        regenerateDurationOutliers,
        durationOutlierWarnings,
      });
      // 新しい実行の開始なので直近完了 run の退避 snapshot を消去する（run handler と同じ）。
      void clearFinishedSnapshot();
      // 直前 run の完了時リロードが保留中なら取り消す (#1411)。理由は run handler と同じ。
      cancelScheduledRunCompleteReload();
      running = true;
      aborted = false;
      void (async () => {
        try {
          // 完了待ちは feed poll の状況次第で分単位かかりうる。popup 再 open 時に initSnapshot の
          // INJECTING が表示され続けないよう、待機中であることを先に明示する（#1586 review）。
          emitProgress({
            phase: PHASE.GENERATING,
            total: 0,
            message: "保存済み clip の生成完了を確認中",
          });
          const completion = await waitForSubmittedClipsComplete({
            expectedClipCount,
            previousSubmittedClipIds: submittedClipIds,
            isAborted: () => aborted,
            getSubmittedIds: () => tracker.getSubmittedIds(),
            getPendingIdsByIds: (ids) => tracker.getPendingIdsByIds(ids),
            getPendingSubmittedIds: () => tracker.getPendingSubmittedIds(),
            requestFeedPoll,
            abortableSleep,
          });
          if (completion.timedOut) {
            // retryPlaylist は entry 情報を持たず graceful degradation できないため従来どおり中断する (#1994)。
            throw new Error(
              completion.message ?? "生成完了待ちがタイムアウトしました"
            );
          }
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, total: 0 });
            return;
          }
          const verifiedClipCount = await addClipsToPlaylist(
            0,
            playlistName,
            submittedClipIds,
            expectedClipCount,
            [],
            [],
            durationFilter,
            submittedClipIdsAreDurationFiltered === true,
            durationOutlierPolicy
          );
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, total: 0 });
            return;
          }
          if (shouldDownload) {
            const downloadContext = await resolveDownloadContext(
              unattended?.request.downloadFormat
            );
            assertUnattendedUiIsSafe();
            await downloadFlow.performDownload(
              downloadContext,
              collectionId,
              verifiedClipCount,
              verifiedClipCount
            );
          }
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, total: 0 });
            return;
          }
          // 消去 → FINISHED → リロードの順序保証は runAll の完了経路と同じ (#1411 要件3)。
          // 消去失敗はここまでの成功（playlist 追加 + download）を ERROR に変えない:
          // catch へ流すと再試行を誘い、同名 playlist の重複作成につながるため、
          // FINISHED を維持してリロードのみ見送る。
          await verifyUnattendedCompletion(unattended);
          let resumeStateCleared = true;
          try {
            await clearResumeStateForCollection(collectionId);
          } catch (err) {
            resumeStateCleared = false;
            console.warn(
              "[suno-helper] resume state の消去に失敗しました。完了時リロードを見送ります:",
              err
            );
          }
          emitProgress({ phase: PHASE.FINISHED, total: 0 });
          // retryPlaylist も playlist 追加で multi-select 状態を作るため完了時にページごと破棄する (#1411)。
          // リロード前に FINISHED snapshot を退避する（runAll の完了経路と同じ）。
          if (
            resumeStateCleared &&
            (await persistFinishedSnapshotForReload())
          ) {
            scheduleRunCompleteReload();
          }
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          emitProgress({ phase: PHASE.ERROR, total: 0, message });
        }
      })().finally(async () => {
        running = false;
        await Promise.all([resumeStateWrite, unattendedStateWrite]);
        await releaseExecutionLease(unattended);
        activeUnattended = undefined;
        releaseRunLock();
      });
      return { ok: true } as const;
    });

    onMessage("retryDownload", ({ data }) => {
      if (running) {
        return { ok: false, busy: true } as const;
      }
      const { collectionId, submittedClipIds, expectedClipCount, unattended } =
        assertRetryDownloadPayload(data);
      if (!acquireRunLock()) {
        return { ok: false, busy: true } as const;
      }
      activeUnattended = unattended;
      currentSnapshot = initSnapshot([], { collectionId });
      // 新しい実行の開始なので直近完了 run の退避 snapshot を消去する（run handler と同じ）。
      void clearFinishedSnapshot();
      // 直前 run の完了時リロードが保留中なら取り消す (#1411)。理由は run handler と同じ。
      cancelScheduledRunCompleteReload();
      running = true;
      aborted = false;
      void (async () => {
        try {
          const downloadContext = await resolveDownloadContext(
            unattended?.request.downloadFormat
          );
          assertUnattendedUiIsSafe();
          const result = await downloadFlow.retryDownload({
            context: downloadContext,
            collectionId,
            submittedClipIds,
            expectedClipCount,
            selectClipIds: async (clipIds) => {
              await scrollAndMultiSelectByIds(clipIds, {
                isAborted: () => aborted,
              });
            },
            clearResumeState: clearResumeStateForCollection,
          });
          // retryDownload も selectClipIds で multi-select 状態を作るため、完了時に
          // ページごと破棄する (#1411)。この経路だけリロードが無いと、次 run が
          // 確実に Cmd+P 前ガードで止まり手動リロードを強いられる。
          // リロード前に FINISHED snapshot を退避する（runAll の完了経路と同じ）。
          if (result.completedAndCleared) {
            await verifyUnattendedCompletion(unattended);
            emitProgress({ phase: PHASE.FINISHED, total: 0 });
            if (await persistFinishedSnapshotForReload()) {
              scheduleRunCompleteReload();
            }
          }
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          emitProgress({ phase: PHASE.ERROR, total: 0, message });
        }
      })().finally(async () => {
        running = false;
        await Promise.all([resumeStateWrite, unattendedStateWrite]);
        await releaseExecutionLease(unattended);
        activeUnattended = undefined;
        releaseRunLock();
      });
      return { ok: true } as const;
    });

    onMessage("adoptSelectedClips", ({ data }) => {
      if (running) {
        throw new Error(
          "実行中は選択中 clip を採用できません。停止または完了後に再実行してください。"
        );
      }
      return readSelectedClipIds({
        isAborted: () => aborted,
        expectedClipCount: data.expectedClipCount,
      }).then((clipIds) => ({ ok: true as const, clipIds }));
    });

    // fallow-ignore-next-line complexity
    async function startUnattendedFromLaunchHash(): Promise<void> {
      if (typeof location === "undefined" || !location.hash) return;
      let envelope;
      try {
        envelope = parseUnattendedLaunchHash(location.hash);
      } catch (error) {
        console.error(
          "[suno-helper] 定期実行 launch payload を検証できません:",
          error
        );
        return;
      }
      if (!envelope) return;

      // 同じ fragment を SPA reload 後に再消費して二重起動しない。
      try {
        history.replaceState(
          history.state,
          "",
          `${location.pathname}${location.search}`
        );
      } catch (error) {
        console.warn(
          "[suno-helper] 定期実行 fragment を消去できません:",
          error
        );
      }

      let request: UnattendedRunRequest;
      try {
        request = assertUnattendedRunRequest(
          await sendMessage("consumeUnattendedRequest", envelope)
        );
      } catch (error) {
        console.error("[suno-helper] 定期実行 nonce を消費できません:", error);
        return;
      }
      if (request.baseUrl !== envelope.baseUrl) {
        console.error(
          "[suno-helper] 定期実行 request の baseUrl が envelope と一致しません"
        );
        return;
      }
      const lease = await sendMessage("acquireUnattendedLease", {
        collectionId: request.collectionId,
        requestId: request.requestId,
      });
      if (!lease.acquired || !lease.token) {
        exposeUnattendedRunState(
          document.documentElement,
          createUnattendedManualState({
            request,
            reason: "run-error",
            message: "別の定期実行が進行中です。完了後に再起動してください。",
            now: Date.now(),
          })
        );
        return;
      }
      const leaseToken = lease.token;
      const leaseHeartbeat = setInterval(() => {
        if (
          leaseHandedOff &&
          activeUnattended?.request.requestId !== request.requestId
        ) {
          clearInterval(leaseHeartbeat);
          void sendMessage("releaseUnattendedLease", {
            collectionId: request.collectionId,
            token: leaseToken,
          });
          return;
        }
        void sendMessage("heartbeatUnattendedLease", {
          collectionId: request.collectionId,
          token: leaseToken,
        });
      }, 30_000);
      let leaseHandedOff = false;
      const releaseLaunchLease = async (): Promise<void> => {
        clearInterval(leaseHeartbeat);
        await sendMessage("releaseUnattendedLease", {
          collectionId: request.collectionId,
          token: leaseToken,
        });
      };

      const pendingEntryIndices = [...(request.entryIndices ?? [])];
      const writeFailure = async (message: string): Promise<void> => {
        await writeUnattendedRunState(
          nextUnattendedRunState({
            request,
            progress: { phase: PHASE.ERROR, total: 0, message },
            deferredIndices: pendingEntryIndices,
            now: Date.now(),
          })
        );
      };

      try {
        const blocker = detectUnattendedPreflightBlocker();
        if (blocker) {
          await writeUnattendedRunState(
            createUnattendedManualState({
              request,
              reason: blocker.reason,
              message: blocker.message,
              pendingEntryIndices,
              now: Date.now(),
            })
          );
          return;
        }

        await serverUrlItem.setValue(request.baseUrl);
        await downloadFormatItem.setValue(request.downloadFormat);
        const collections = await sendMessage("fetchCollections", {
          baseUrl: request.baseUrl,
        });
        const collection = collections.find(
          (candidate) => candidate.id === request.collectionId
        );
        if (!collection) {
          throw new Error(
            `collection ${request.collectionId} が server にありません`
          );
        }
        const promptResponse = (await sendMessage(
          "fetchCollectionPromptResponse",
          {
            baseUrl: request.baseUrl,
            collectionId: request.collectionId,
          }
        )) as PromptResponse;
        if (promptResponse.entries.length === 0) {
          throw new Error("collection の Suno entry が 0 件です");
        }
        const resumeState = await readResumeState();
        const playlistName = playlistNameForCollection(collection);
        const canReconcileCreatedPlaylist =
          resumeState?.collectionId === request.collectionId &&
          resumeState.failedIndex === promptResponse.entries.length &&
          (resumeState.submittedClipIds?.length ?? 0) > 0 &&
          resumeState.playlistExpectedClipCount !== undefined &&
          Array.isArray(resumeState.playlistUrlsBeforeCreate);
        if (!collection.suno_playlist_url && canReconcileCreatedPlaylist) {
          const baselineUrls = new Set(resumeState.playlistUrlsBeforeCreate);
          const existingPlaylistUrls = findPlaylistUrlsByName(
            document,
            playlistName
          ).filter((url) => !baselineUrls.has(url));
          if (existingPlaylistUrls.length === 1) {
            await writeUnattendedRunState(
              createUnattendedManualState({
                request,
                reason: "existing-playlist",
                message:
                  `作成途中の playlist ${existingPlaylistUrls[0]} を検出しました。` +
                  "clip 追加済みか確認できないため自動 download は開始しません。",
                checkpoint: "playlist",
                now: Date.now(),
              })
            );
            return;
          } else if (existingPlaylistUrls.length > 1) {
            await writeUnattendedRunState(
              createUnattendedManualState({
                request,
                reason: "existing-playlist",
                message: "同名 playlist が複数あるため自動再開できません。",
                checkpoint: "playlist",
                now: Date.now(),
              })
            );
            return;
          }
        }
        const plan = planUnattendedRun({
          request,
          collection,
          entryCount: promptResponse.entries.length,
          resumeState,
        });
        if (plan.kind === "complete") {
          await writeUnattendedRunState(
            nextUnattendedRunState({
              request,
              progress: {
                phase: PHASE.FINISHED,
                total: promptResponse.entries.length,
                message: "音源は既に download 済みです。",
              },
              deferredIndices: [],
              now: Date.now(),
              verifiedComplete: true,
            })
          );
          return;
        }
        if (plan.kind === "manual-intervention") {
          await writeUnattendedRunState({
            ...createUnattendedManualState({
              request,
              reason: plan.reason,
              message: plan.requiredAction,
              checkpoint:
                plan.reason === "existing-playlist" ? "download" : "entries",
              pendingEntryIndices,
              now: Date.now(),
            }),
            requiredAction: plan.requiredAction,
          });
          return;
        }

        if (plan.kind === "retry-playlist") {
          const result = await sendMessage("retryPlaylist", {
            playlistName,
            submittedClipIds: plan.submittedClipIds,
            expectedClipCount: plan.expectedClipCount,
            collectionId: request.collectionId,
            durationFilter:
              resumeState?.durationFilter ?? promptResponse.duration_filter,
            regenerateDurationOutliers:
              resumeState?.regenerateDurationOutliers ?? true,
            durationOutlierWarnings: resumeState?.durationOutlierWarnings,
            submittedClipIdsAreDurationFiltered:
              resumeState?.submittedClipIdsAreDurationFiltered,
            shouldDownload: true,
            unattended: { request, deferredIndices: [], leaseToken },
          });
          if (!result.ok) throw new Error("suno-helper runner is busy");
          leaseHandedOff = true;
          return;
        }
        if (plan.kind === "retry-download") {
          if (resumeState?.downloadCompletedFilename) {
            await sendMessage("postDownloaded", {
              baseUrl: request.baseUrl,
              collectionId: request.collectionId,
              body: {
                file_count: plan.expectedClipCount,
                expected_file_count: plan.expectedClipCount,
                format: request.downloadFormat,
                download_path: resumeState.downloadCompletedFilename,
                ...(collection.suno_playlist_url
                  ? { suno_playlist_url: collection.suno_playlist_url }
                  : {}),
              },
            });
            const refreshed = await sendMessage("fetchCollections", {
              baseUrl: request.baseUrl,
            });
            const completed = refreshed.find(
              (candidate) => candidate.id === request.collectionId
            );
            if (
              !completed ||
              !hasCompleteUnattendedArtifacts(
                completed,
                promptResponse.entries.length * CLIPS_PER_REQUEST
              )
            ) {
              throw new Error(
                "download checkpoint の server readback に失敗しました"
              );
            }
            await clearResumeStateForCollection(request.collectionId);
            await writeUnattendedRunState(
              nextUnattendedRunState({
                request,
                progress: {
                  phase: PHASE.FINISHED,
                  total: plan.expectedClipCount,
                },
                deferredIndices: [],
                now: Date.now(),
                verifiedComplete: true,
              })
            );
            return;
          }
          const result = await sendMessage("retryDownload", {
            collectionId: request.collectionId,
            submittedClipIds: plan.submittedClipIds,
            expectedClipCount: plan.expectedClipCount,
            unattended: { request, deferredIndices: [], leaseToken },
          });
          if (!result.ok) throw new Error("suno-helper runner is busy");
          leaseHandedOff = true;
          return;
        }

        await writeUnattendedRunState({
          requestId: request.requestId,
          collectionId: request.collectionId,
          status: "running",
          checkpoint: "entries",
          pendingEntryIndices: [...plan.deferredIndices],
          updatedAt: Date.now(),
        });
        const result = await sendMessage("run", {
          entries: promptResponse.entries,
          playlistName,
          durationFilter:
            resumeState?.durationFilter ?? promptResponse.duration_filter,
          collectionId: request.collectionId,
          runMode: resumeState?.runMode ?? "queue",
          regenerateDurationOutliers:
            resumeState?.regenerateDurationOutliers ?? true,
          durationOutlierWarnings: resumeState?.durationOutlierWarnings,
          indices: plan.indices,
          submittedClipIds: plan.previousSubmittedClipIds,
          submittedClipIdsAreDurationFiltered:
            resumeState?.submittedClipIdsAreDurationFiltered,
          playlistExpectedClipCount: plan.playlistExpectedClipCount,
          unattended: {
            request,
            deferredIndices: plan.deferredIndices,
            leaseToken,
          },
        });
        if (!result.ok) {
          throw new Error(
            "error" in result ? result.error : "suno-helper runner is busy"
          );
        }
        leaseHandedOff = true;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error("[suno-helper] 定期実行を開始できません:", error);
        await writeFailure(message);
      } finally {
        if (!leaseHandedOff) await releaseLaunchLease();
      }
    }

    // popup 再 open 時の進捗復元 (#852)。in-memory snapshot が SSOT。完了時リロード (#1411) で
    // in-memory が破棄された後は、リロード直前に退避した直近完了 run の snapshot を fallback で返す
    // （stale 判定込み、次 run 開始で消去）。どちらも無ければ null（buildRestoreState が従来表示へ）。
    onMessage(
      "queryProgress",
      async () =>
        currentSnapshot ?? (await readFreshFinishedSnapshot(Date.now()))
    );
    onMessage("queryUnattendedState", async () => {
      await unattendedStateWrite;
      return readUnattendedRunState();
    });
    const restoreAndLaunch = async (): Promise<void> => {
      // Unit-test harnesses intentionally have no extension runtime/storage.
      // Launch parsing remains testable, while storage restore is browser-only.
      if (typeof browser !== "undefined" && browser.runtime) {
        const state = await readUnattendedRunState();
        if (state) exposeUnattendedRunState(document.documentElement, state);
      }
      await startUnattendedFromLaunchHash();
    };
    void restoreAndLaunch().catch((error: unknown) => {
      console.warn(
        "[suno-helper] 定期実行 state の復元または起動に失敗しました:",
        error
      );
    });
  },
});
