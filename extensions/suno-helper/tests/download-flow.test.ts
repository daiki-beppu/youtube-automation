import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PHASE } from "../../shared/constants";
import { createDownloadFlow } from "../lib/download-flow";

// REQ-2915-01: every watcher-side failure cancels once and clears its resolver.
const messagingMocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => unknown>(),
  sendMessage: vi.fn(),
}));

const studioExportMocks = vi.hoisted(() => ({
  requestStudioMultitrackExport: vi.fn(async () => undefined),
}));

vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn((type: string, handler: (...args: unknown[]) => unknown) => {
    messagingMocks.handlers.set(type, handler);
    return () => undefined;
  }),
  sendMessage: messagingMocks.sendMessage,
}));

vi.mock("../lib/studio-export", () => ({
  requestStudioMultitrackExport:
    studioExportMocks.requestStudioMultitrackExport,
}));

const CONTEXT = {
  baseUrl: "http://localhost:7873",
};
const CLIP_IDS = ["clip-1", "clip-2"];

const PARTIAL_SUMMARY = {
  expected: 56,
  placed: 47,
  missing: 9,
  reasons: { sunoUnfulfilled: 3, applySkipped: 6 },
};

function dispatchDownloadComplete(filename = "collection.zip"): void {
  messagingMocks.handlers.get("downloadComplete")?.({
    data: { filename },
  });
}

function createSubject(isAborted: () => boolean, emitProgress = vi.fn()) {
  const flow = createDownloadFlow({
    emitProgress,
    isAborted,
  });
  flow.installMessageHandlers();
  return flow;
}

function expectOnlyStartAndCancelMessages(): void {
  expect(
    messagingMocks.sendMessage.mock.calls.filter(
      ([message]) => message === "cancelDownload"
    )
  ).toHaveLength(1);
  expect(
    messagingMocks.sendMessage.mock.calls.some(
      ([message]) => message === "postDownloaded"
    )
  ).toBe(false);
}

function arrangePartialDownloadSuccess(): void {
  messagingMocks.sendMessage.mockImplementation(async (message: string) => {
    if (message === "startDownload") {
      return { ok: true };
    }
    if (message === "postDownloaded") {
      return {
        summary: PARTIAL_SUMMARY,
        warning: "placed 47 files, expected 56 (9 missing)",
      };
    }
    return { ok: true };
  });
  studioExportMocks.requestStudioMultitrackExport.mockImplementationOnce(
    async () => {
      dispatchDownloadComplete();
    }
  );
}

describe("download flow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    messagingMocks.handlers.clear();
    messagingMocks.sendMessage.mockImplementation(async (message: string) => {
      if (message === "startDownload") {
        return { ok: true };
      }
      return { ok: true };
    });
    studioExportMocks.requestStudioMultitrackExport.mockResolvedValue(
      undefined
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("DOM 操作が throw すると watcher を一回 cancel し resolver を破棄する", async () => {
    studioExportMocks.requestStudioMultitrackExport.mockRejectedValueOnce(
      new Error("download button missing")
    );
    const flow = createSubject(() => false);

    await expect(
      flow.performDownload(CONTEXT, "collection", 2, 2, CLIP_IDS)
    ).rejects.toThrow("download button missing");

    expectOnlyStartAndCancelMessages();
    dispatchDownloadComplete();
    await Promise.resolve();
    expectOnlyStartAndCancelMessages();
  });

  it("timeout すると watcher を一回 cancel し late completion を無視する", async () => {
    const flow = createSubject(() => false);
    const result = flow.performDownload(CONTEXT, "collection", 2, 2, CLIP_IDS);
    const rejection = expect(result).rejects.toThrow(
      "Studio Multitrack export がタイムアウトしました"
    );

    await vi.advanceTimersByTimeAsync(660_000);
    await rejection;

    expectOnlyStartAndCancelMessages();
    dispatchDownloadComplete();
    await Promise.resolve();
    expectOnlyStartAndCancelMessages();
  });

  it("abort すると watcher を一回 cancel し post も resolver も残さない", async () => {
    let aborted = false;
    studioExportMocks.requestStudioMultitrackExport.mockImplementationOnce(
      async () => {
        aborted = true;
      }
    );
    const flow = createSubject(() => aborted);
    const result = flow.performDownload(CONTEXT, "collection", 2, 2, CLIP_IDS);

    await vi.advanceTimersByTimeAsync(1_000);
    await result;

    expectOnlyStartAndCancelMessages();
    dispatchDownloadComplete();
    await Promise.resolve();
    expectOnlyStartAndCancelMessages();
  });

  it("通常 download の部分成功は server summary を同一objectで返す", async () => {
    arrangePartialDownloadSuccess();
    const flow = createSubject(() => false);

    const summary = await flow.performDownload(
      CONTEXT,
      "collection",
      28,
      56,
      CLIP_IDS
    );

    expect(summary).toBe(PARTIAL_SUMMARY);
    expect(
      studioExportMocks.requestStudioMultitrackExport
    ).toHaveBeenCalledWith({ collectionId: "collection", clipIds: CLIP_IDS });
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("postDownloaded", {
      baseUrl: CONTEXT.baseUrl,
      collectionId: "collection",
      body: {
        file_count: 56,
        expected_file_count: 56,
        format: "wav",
        download_path: "collection.zip",
      },
    });
  });

  it("best-effort download の部分成功は error なしで同じ server summary を返す", async () => {
    arrangePartialDownloadSuccess();
    const flow = createSubject(() => false);

    const result = await flow.downloadBestEffortResult(
      CONTEXT,
      "collection",
      28,
      56,
      CLIP_IDS
    );

    expect(result).toEqual({ error: null, summary: PARTIAL_SUMMARY });
    expect(result.summary).toBe(PARTIAL_SUMMARY);
  });

  it("retry download の部分成功は同じ server summary を返す", async () => {
    arrangePartialDownloadSuccess();
    const emitProgress = vi.fn();
    const flow = createSubject(() => false, emitProgress);

    const result = await flow.retryDownload({
      context: CONTEXT,
      collectionId: "collection",
      submittedClipIds: ["clip-id"],
      expectedClipCount: 56,
      clearResumeState: vi.fn(async () => undefined),
    });

    expect(result).toEqual({
      completedAndCleared: true,
      summary: PARTIAL_SUMMARY,
    });
    expect(result.summary).toBe(PARTIAL_SUMMARY);
    const finishedProgress = emitProgress.mock.calls
      .map(([payload]) => payload)
      .filter((payload) => payload.phase === PHASE.FINISHED);
    expect(finishedProgress).toEqual([
      {
        phase: PHASE.FINISHED,
        total: 0,
        downloadSummary: PARTIAL_SUMMARY,
      },
    ]);
  });

  it("通常 download の API 失敗理由へ downloading phase を付与して返す", async () => {
    const apiError =
      "POST /collections/collection/downloaded failed: 403 Forbidden";
    messagingMocks.sendMessage.mockImplementation(async (message: string) => {
      if (message === "startDownload") {
        return { ok: true };
      }
      if (message === "postDownloaded") {
        throw new Error(apiError);
      }
      return { ok: true };
    });
    studioExportMocks.requestStudioMultitrackExport.mockImplementationOnce(
      async () => {
        dispatchDownloadComplete();
      }
    );
    const flow = createSubject(() => false);

    await expect(
      flow.downloadBestEffort(CONTEXT, "collection", 2, 2, CLIP_IDS)
    ).resolves.toBe(`${apiError} (phase=downloading)`);
  });

  it("retry download の失敗理由へ downloading phase を付与して throw する", async () => {
    messagingMocks.sendMessage.mockResolvedValueOnce({
      ok: false,
      message: "watcher unavailable",
    });
    const flow = createSubject(() => false);

    await expect(
      flow.retryDownload({
        context: CONTEXT,
        collectionId: "collection",
        submittedClipIds: ["clip-id"],
        clearResumeState: vi.fn(async () => undefined),
      })
    ).rejects.toThrow("watcher unavailable (phase=downloading)");
  });

  it("配置数 0 の server error を通常 download で握りつぶさない", async () => {
    const serverError = "placed_count must be positive";
    messagingMocks.sendMessage.mockImplementation(async (message: string) => {
      if (message === "startDownload") {
        return { ok: true };
      }
      if (message === "postDownloaded") {
        throw new Error(serverError);
      }
      return { ok: true };
    });
    studioExportMocks.requestStudioMultitrackExport.mockImplementationOnce(
      async () => {
        dispatchDownloadComplete();
      }
    );
    const flow = createSubject(() => false);

    await expect(
      flow.performDownload(CONTEXT, "collection", 2, 2, CLIP_IDS)
    ).rejects.toThrow(`${serverError} (phase=downloading)`);
  });

  it("既に downloading phase がある失敗理由を重複して付与しない", async () => {
    messagingMocks.sendMessage.mockResolvedValueOnce({
      ok: false,
      message: "watcher unavailable (phase=downloading)",
    });
    const flow = createSubject(() => false);

    await expect(
      flow.performDownload(CONTEXT, "collection", 2, 2, CLIP_IDS)
    ).rejects.toThrow(/^watcher unavailable \(phase=downloading\)$/);
  });
});
