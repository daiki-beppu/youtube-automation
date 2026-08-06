import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createDownloadFlow } from "../lib/download-flow";

// REQ-2915-01: every watcher-side failure cancels once and clears its resolver.
const messagingMocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => unknown>(),
  sendMessage: vi.fn(),
}));

const downloadMocks = vi.hoisted(() => ({
  triggerDownloadAll: vi.fn(async () => undefined),
}));

vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn((type: string, handler: (...args: unknown[]) => unknown) => {
    messagingMocks.handlers.set(type, handler);
    return () => undefined;
  }),
  sendMessage: messagingMocks.sendMessage,
}));

vi.mock("../lib/download", () => ({
  triggerDownloadAll: downloadMocks.triggerDownloadAll,
}));

const CONTEXT = {
  baseUrl: "http://localhost:7873",
  format: "mp3" as const,
};

function dispatchDownloadComplete(filename = "collection.zip"): void {
  messagingMocks.handlers.get("downloadComplete")?.({
    data: { filename },
  });
}

function createSubject(isAborted: () => boolean) {
  const flow = createDownloadFlow({
    emitProgress: vi.fn(),
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
    downloadMocks.triggerDownloadAll.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("DOM 操作が throw すると watcher を一回 cancel し resolver を破棄する", async () => {
    downloadMocks.triggerDownloadAll.mockRejectedValueOnce(
      new Error("download button missing")
    );
    const flow = createSubject(() => false);

    await expect(
      flow.performDownload(CONTEXT, "collection", 2, 2)
    ).rejects.toThrow("download button missing");

    expectOnlyStartAndCancelMessages();
    dispatchDownloadComplete();
    await Promise.resolve();
    expectOnlyStartAndCancelMessages();
  });

  it("timeout すると watcher を一回 cancel し late completion を無視する", async () => {
    const flow = createSubject(() => false);
    const result = flow.performDownload(CONTEXT, "collection", 2, 2);
    const rejection = expect(result).rejects.toThrow(
      "Download all がタイムアウトしました"
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
    downloadMocks.triggerDownloadAll.mockImplementationOnce(async () => {
      aborted = true;
    });
    const flow = createSubject(() => aborted);
    const result = flow.performDownload(CONTEXT, "collection", 2, 2);

    await vi.advanceTimersByTimeAsync(1_000);
    await result;

    expectOnlyStartAndCancelMessages();
    dispatchDownloadComplete();
    await Promise.resolve();
    expectOnlyStartAndCancelMessages();
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
    downloadMocks.triggerDownloadAll.mockImplementationOnce(async () => {
      dispatchDownloadComplete();
    });
    const flow = createSubject(() => false);

    await expect(
      flow.downloadBestEffort(CONTEXT, "collection", 2, 2)
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
        selectClipIds: vi.fn(async () => undefined),
        clearResumeState: vi.fn(async () => undefined),
      })
    ).rejects.toThrow("watcher unavailable (phase=downloading)");
  });

  it("既に downloading phase がある失敗理由を重複して付与しない", async () => {
    messagingMocks.sendMessage.mockResolvedValueOnce({
      ok: false,
      message: "watcher unavailable (phase=downloading)",
    });
    const flow = createSubject(() => false);

    await expect(
      flow.performDownload(CONTEXT, "collection", 2, 2)
    ).rejects.toThrow(/^watcher unavailable \(phase=downloading\)$/);
  });
});
