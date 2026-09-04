import type { DownloadSummary } from "../../shared/api";
import type { ProgressPayload } from "../../shared/constants";
import { PHASE } from "../../shared/constants";
import { onMessage, sendMessage } from "./messaging";
import {
  closeStudioExportTab,
  requestStudioMultitrackExport,
} from "./studio-export";

type DownloadResult =
  | { ok: true; filename: string }
  | { ok: false; message: string };

export interface DownloadFlow {
  installMessageHandlers: () => void;
  performDownload: (
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
    clipIds: string[]
  ) => Promise<DownloadSummary | undefined>;
  downloadBestEffortResult: (
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
    clipIds: string[]
  ) => Promise<DownloadBestEffortResult>;
  downloadBestEffort: (
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
    clipIds: string[]
  ) => Promise<string | null>;
  retryDownload: (
    options: RetryDownloadOptions
  ) => Promise<RetryDownloadResult>;
}

export interface RetryDownloadResult {
  /** FINISHED まで到達し resume state 消去も成功したか。呼び出し側の完了時リロード発火判定に使う (#1411)。
   * false は中断（STOPPED）または resume state 消去失敗（リロードすると再開バナーが誤判定するため見送る）。 */
  completedAndCleared: boolean;
  summary?: DownloadSummary;
}

export interface DownloadBestEffortResult {
  error: string | null;
  summary?: DownloadSummary;
}

export interface DownloadFlowDeps {
  emitProgress: (payload: ProgressPayload) => void;
  isAborted: () => boolean;
  /** Persist the irreversible browser-download result before localhost POST. */
  onDownloadComplete?: (filename: string) => Promise<void>;
}

export interface RetryDownloadOptions {
  context: DownloadContext;
  collectionId: string;
  submittedClipIds: string[];
  expectedClipCount?: number;
  clearResumeState: (collectionId: string) => Promise<void>;
}

export interface DownloadContext {
  baseUrl: string;
}

const DOWNLOAD_COMPLETE_TIMEOUT_MS = 660000;
const DOWNLOADING_PHASE_SUFFIX = "(phase=downloading)";

function withDownloadingPhase(error: unknown): Error {
  const message = error instanceof Error ? error.message : String(error);
  if (message.endsWith(DOWNLOADING_PHASE_SUFFIX)) {
    return error instanceof Error ? error : new Error(message);
  }
  return new Error(`${message} ${DOWNLOADING_PHASE_SUFFIX}`);
}

export function createDownloadFlow(deps: DownloadFlowDeps): DownloadFlow {
  let downloadCompleteResolver:
    | ((value: DownloadResult | null) => void)
    | null = null;
  let handlersInstalled = false;

  function waitForDownloadComplete(): Promise<DownloadResult | null> {
    return new Promise((resolve) => {
      downloadCompleteResolver = resolve;
      const deadline = Date.now() + DOWNLOAD_COMPLETE_TIMEOUT_MS;
      const tick = (): void => {
        if (downloadCompleteResolver === null) {
          return;
        }
        if (deps.isAborted() || Date.now() >= deadline) {
          downloadCompleteResolver = null;
          resolve(null);
          return;
        }
        setTimeout(tick, 1000);
      };
      tick();
    });
  }

  function installMessageHandlers(): void {
    if (handlersInstalled) return;
    handlersInstalled = true;

    onMessage("downloadComplete", ({ data }) => {
      if (downloadCompleteResolver) {
        const resolver = downloadCompleteResolver;
        downloadCompleteResolver = null;
        resolver({ ok: true, filename: data.filename });
      }
    });

    onMessage("downloadFailed", ({ data }) => {
      if (downloadCompleteResolver) {
        const resolver = downloadCompleteResolver;
        downloadCompleteResolver = null;
        resolver({ ok: false, message: data.message });
      }
    });
  }

  async function startDownloadWatcher(): Promise<void> {
    const startResult = await sendMessage("startDownload", undefined);
    if (!startResult?.ok) {
      throw new Error(
        startResult?.message ?? "Studio export の監視を開始できませんでした"
      );
    }
  }

  async function cancelDownloadWatcher(): Promise<void> {
    downloadCompleteResolver = null;
    await sendMessage("cancelDownload", undefined).catch(
      (cancelErr: unknown) => {
        console.warn("[suno-helper] cancelDownload 中継失敗:", cancelErr);
      }
    );
  }

  async function waitForDownloadedFilename(
    collectionId: string,
    clipIds: string[]
  ): Promise<string | null> {
    const downloadPromise = waitForDownloadComplete();
    let watcherActive = true;
    let studioTabId: number | null = null;
    try {
      studioTabId = await requestStudioMultitrackExport({
        collectionId,
        clipIds,
      });
      const downloadResult = await downloadPromise;
      if (deps.isAborted()) return null;
      if (!downloadResult) {
        throw new Error("Studio Multitrack export がタイムアウトしました");
      }
      watcherActive = false;
      if (!downloadResult.ok) {
        throw new Error(downloadResult.message);
      }
      return downloadResult.filename;
    } finally {
      if (watcherActive) {
        await cancelDownloadWatcher();
      }
      // ZIP は download 完了時点でディスクに書き終わっているため、成功・失敗・中断の
      // いずれでもここで Studio tab を閉じる（Studio project 自体は仕様通り残す）。
      if (typeof studioTabId === "number") {
        await closeStudioExportTab(studioTabId);
      }
    }
  }

  async function postDownloadedArchive(
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
    filename: string
  ): Promise<DownloadSummary | undefined> {
    deps.emitProgress({
      phase: PHASE.PLACING_ARCHIVE,
      total: progressTotal,
    });
    await deps.onDownloadComplete?.(filename);
    const postResult = await sendMessage("postDownloaded", {
      baseUrl: context.baseUrl,
      collectionId,
      body: {
        file_count: expectedFileCount,
        expected_file_count: expectedFileCount,
        format: "wav",
        download_path: filename,
      },
    });
    // 部分完了（Suno の生成数不足）はサーバーが warning 付き 200 で受理する (#1913)。
    // フローは止めず、不足をユーザーへ通知するだけに留める
    if (postResult?.warning) {
      console.warn(`[suno-helper] 部分ダウンロード: ${postResult.warning}`);
      deps.emitProgress({
        phase: PHASE.PLACING_ARCHIVE,
        total: progressTotal,
        message: `部分ダウンロード（不足あり）: ${postResult.warning}`,
      });
    }
    return postResult?.summary;
  }

  async function performDownloadAttempt(
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
    clipIds: string[]
  ): Promise<DownloadSummary | undefined> {
    if (deps.isAborted()) return;

    deps.emitProgress({
      phase: PHASE.DOWNLOADING,
      total: progressTotal,
      message: "Studio Multitrack export（WAV）",
    });
    await startDownloadWatcher();
    const filename = await waitForDownloadedFilename(collectionId, clipIds);
    if (filename === null) return;
    return await postDownloadedArchive(
      context,
      collectionId,
      progressTotal,
      expectedFileCount,
      filename
    );
  }

  async function performDownload(
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
    clipIds: string[]
  ): Promise<DownloadSummary | undefined> {
    try {
      return await performDownloadAttempt(
        context,
        collectionId,
        progressTotal,
        expectedFileCount,
        clipIds
      );
    } catch (error) {
      throw withDownloadingPhase(error);
    }
  }

  async function downloadBestEffortResult(
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
    clipIds: string[]
  ): Promise<DownloadBestEffortResult> {
    try {
      const summary = await performDownload(
        context,
        collectionId,
        progressTotal,
        expectedFileCount,
        clipIds
      );
      return summary === undefined ? { error: null } : { error: null, summary };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn(`[suno-helper] Studio export failed: ${message}`);
      deps.emitProgress({
        phase: PHASE.DOWNLOADING,
        total: progressTotal,
        message: `Studio export 失敗: ${message}`,
      });
      return { error: message };
    }
  }

  async function downloadBestEffort(
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
    clipIds: string[]
  ): Promise<string | null> {
    return (
      await downloadBestEffortResult(
        context,
        collectionId,
        progressTotal,
        expectedFileCount,
        clipIds
      )
    ).error;
  }

  async function retryDownload(
    options: RetryDownloadOptions
  ): Promise<RetryDownloadResult> {
    const total = options.submittedClipIds.length;
    if (options.submittedClipIds.length === 0) {
      throw new Error("retryDownload に必要な clip ID がありません");
    }
    const summary = await performDownload(
      options.context,
      options.collectionId,
      total,
      options.expectedClipCount ?? total,
      options.submittedClipIds
    );
    if (deps.isAborted()) {
      deps.emitProgress({ phase: PHASE.STOPPED, total: 0 });
      return summary === undefined
        ? { completedAndCleared: false }
        : { completedAndCleared: false, summary };
    }
    // 消去失敗でも FINISHED は維持する（download 自体は成功しているため）。
    // その場合はリロードを見送る合図として completedAndCleared=false を返す (#1411)。
    let resumeStateCleared = true;
    try {
      await options.clearResumeState(options.collectionId);
    } catch (err) {
      resumeStateCleared = false;
      console.warn(
        "[suno-helper] resume state の消去に失敗しました。完了時リロードを見送ります:",
        err
      );
    }
    deps.emitProgress({
      phase: PHASE.FINISHED,
      total: 0,
      ...(summary === undefined ? {} : { downloadSummary: summary }),
    });
    return summary === undefined
      ? { completedAndCleared: resumeStateCleared }
      : { completedAndCleared: resumeStateCleared, summary };
  }

  return {
    installMessageHandlers,
    performDownload,
    downloadBestEffortResult,
    downloadBestEffort,
    retryDownload,
  };
}
