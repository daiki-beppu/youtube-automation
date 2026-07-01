import type { DownloadedPayload } from "../../shared/api";
import type { ProgressPayload } from "../../shared/constants";
import { PHASE } from "../../shared/constants";
import { triggerDownloadAll } from "./download";
import { onMessage, sendMessage } from "./messaging";

type DownloadResult = { ok: true; filename: string } | { ok: false; message: string };

export interface DownloadFlow {
  installMessageHandlers: () => void;
  performDownload: (
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
  ) => Promise<void>;
  downloadBestEffort: (
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
  ) => Promise<string | null>;
  retryDownload: (options: RetryDownloadOptions) => Promise<void>;
}

export interface DownloadFlowDeps {
  emitProgress: (payload: ProgressPayload) => void;
  isAborted: () => boolean;
}

export interface RetryDownloadOptions {
  context: DownloadContext;
  collectionId: string;
  submittedClipIds: string[];
  expectedClipCount?: number;
  selectClipIds: (submittedClipIds: string[]) => Promise<void>;
  clearResumeState: (collectionId: string) => Promise<void>;
}

export interface DownloadContext {
  baseUrl: string;
  format: DownloadedPayload["format"];
}

const DOWNLOAD_COMPLETE_TIMEOUT_MS = 660000;

export function createDownloadFlow(deps: DownloadFlowDeps): DownloadFlow {
  let downloadCompleteResolver: ((value: DownloadResult | null) => void) | null = null;
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

  async function performDownload(
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
  ): Promise<void> {
    if (deps.isAborted()) return;

    deps.emitProgress({
      phase: PHASE.DOWNLOADING,
      total: progressTotal,
      message: `${context.format.toUpperCase()} 形式`,
    });
    const startResult = await sendMessage("startDownload", { format: context.format });
    if (!startResult?.ok) {
      throw new Error(startResult?.message ?? "Download all 監視を開始できませんでした");
    }
    const downloadPromise = waitForDownloadComplete();
    let watcherActive = true;
    try {
      await triggerDownloadAll(context.format);

      const downloadResult = await downloadPromise;

      if (deps.isAborted()) return;

      if (!downloadResult) {
        throw new Error("Download all がタイムアウトしました");
      }
      watcherActive = false;
      if (!downloadResult.ok) {
        throw new Error(downloadResult.message);
      }

      await sendMessage("postDownloaded", {
        baseUrl: context.baseUrl,
        collectionId,
        body: {
          file_count: expectedFileCount,
          expected_file_count: expectedFileCount,
          format: context.format,
          download_path: downloadResult.filename,
        },
      });
    } finally {
      if (watcherActive) {
        downloadCompleteResolver = null;
        await sendMessage("cancelDownload", undefined).catch((cancelErr: unknown) => {
          console.warn("[suno-helper] cancelDownload 中継失敗:", cancelErr);
        });
      }
    }
  }

  async function downloadBestEffort(
    context: DownloadContext,
    collectionId: string,
    progressTotal: number,
    expectedFileCount: number,
  ): Promise<string | null> {
    try {
      await performDownload(context, collectionId, progressTotal, expectedFileCount);
      return null;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn(`[suno-helper] Download all failed: ${message}`);
      deps.emitProgress({
        phase: PHASE.DOWNLOADING,
        total: progressTotal,
        message: `ダウンロード失敗（手動でダウンロードしてください）: ${message}`,
      });
      return message;
    }
  }

  async function retryDownload(options: RetryDownloadOptions): Promise<void> {
    const total = options.submittedClipIds.length;
    if (options.submittedClipIds.length === 0) {
      throw new Error("retryDownload に必要な clip ID がありません");
    }
    deps.emitProgress({ phase: PHASE.ADDING_TO_PLAYLIST, total, message: "clip を選択中…" });
    await options.selectClipIds(options.submittedClipIds);
    if (deps.isAborted()) {
      deps.emitProgress({ phase: PHASE.STOPPED, total: 0 });
      return;
    }
    await performDownload(options.context, options.collectionId, total, options.expectedClipCount ?? total);
    if (deps.isAborted()) {
      deps.emitProgress({ phase: PHASE.STOPPED, total: 0 });
      return;
    }
    await options.clearResumeState(options.collectionId);
    deps.emitProgress({ phase: PHASE.FINISHED, total: 0 });
  }

  return {
    installMessageHandlers,
    performDownload,
    downloadBestEffort,
    retryDownload,
  };
}
