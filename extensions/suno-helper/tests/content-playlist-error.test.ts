import { beforeEach, describe, expect, it, vi } from "vitest";

import { CLIPS_PER_REQUEST, PHASE } from "../../shared/constants";
import type { PromptEntry } from "../../shared/api";
import type { ResumeState, RunRange } from "../lib/resume-state";

interface RunPayload {
  entries: PromptEntry[];
  playlistName?: string;
  range?: RunRange;
  collectionId?: string;
  indices?: number[];
  submittedClipIds?: string[];
  playlistExpectedClipCount?: number;
}

type RunHandler = (message: { data: RunPayload }) => { ok: true };

const writeResumeStateMock = vi.fn<(state: ResumeState) => Promise<void>>();

interface ProgressMessage {
  phase: string;
  index?: number;
  message?: string;
}

async function loadContentScriptWithPlaylistRows(
  submittedIdsFromTracker: string[],
  playlistRowsResult: HTMLElement[] | Error,
) {
  vi.resetModules();
  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => definition);

  const handlers = new Map<string, RunHandler>();
  const progressMessages: ProgressMessage[] = [];
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const ensureClipRowsLoadedByIdsMock = vi.fn((_ids: string[], _options: unknown) => {
    if (playlistRowsResult instanceof Error) {
      return Promise.reject(playlistRowsResult);
    }
    return Promise.resolve(playlistRowsResult);
  });

  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((type: string, handler: RunHandler) => {
      handlers.set(type, handler);
    }),
    sendMessage: vi.fn((type: string, payload?: ProgressMessage) => {
      if (type === "progress") {
        progressMessages.push(payload as ProgressMessage);
      }
      return Promise.resolve();
    }),
  }));

  vi.doMock("../lib/resume-state", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../lib/resume-state")>();
    return {
      ...actual,
      writeResumeState: writeResumeStateMock,
      clearResumeStateForCollection: vi.fn(() => Promise.resolve()),
    };
  });

  vi.doMock("../lib/preset-state", () => ({
    applyJitter: (baseMs: number) => baseMs,
    readSpeedPresetId: vi.fn(() => Promise.resolve("balanced")),
    resolveSpeedPreset: vi.fn(() => ({
      maxInflightRequests: 10,
      maxInjectRetry: 0,
      maxEntryRetry: 0,
      injectAckTimeoutMs: 1,
      interCreateDelayMs: 0,
      jitterMs: 0,
    })),
  }));

  vi.doMock("../lib/snapshot", () => ({
    initSnapshot: vi.fn((entries: PromptEntry[], playlistName?: string) => ({
      entries,
      playlistName,
      itemStates: entries.map(() => "pending"),
      isRunning: true,
      submittedClipIds: [],
    })),
    applyProgress: vi.fn((snapshot: object, payload: object) => ({ ...snapshot, progress: payload })),
  }));

  vi.doMock("../lib/bridge-listener", () => ({
    attachBridgeListener: vi.fn(),
    createFeedPoller: vi.fn(() => ({ start: vi.fn(), stop: vi.fn() })),
    requestSliderSet: vi.fn(),
  }));

  vi.doMock("../lib/clip-tracker", () => ({
    createClipTracker: vi.fn(() => ({
      clearSubmittedIds: vi.fn(),
      getSubmittedIds: vi.fn(() => submittedIdsFromTracker),
      getInFlightCount: vi.fn(() => 0),
      hasObservedAnyTraffic: vi.fn(() => true),
      lastChangeAt: vi.fn(() => Date.now()),
      submissionCount: vi.fn(() => 0),
    })),
  }));

  vi.doMock("../../shared/dom", () => ({
    abortableSleep: vi.fn(() => Promise.resolve()),
    CAPTCHA_WAIT_TIMEOUT_MS: 1,
    FatalRunError: class FatalRunError extends Error {},
    GENERATE_TIMEOUT_MS: 1,
    POLL_INTERVAL_MS: 1,
    SETTLE_MS: 0,
    getInFlightClipCount: vi.fn(() => 0),
    injectAdvancedFields: vi.fn(() => Promise.resolve()),
    resolveAdvancedFields: vi.fn(() => ({})),
    resolveFields: vi.fn(() => ({ style: {} as HTMLTextAreaElement, lyrics: null, title: null })),
    resolveGenerateButton: vi.fn(() => ({ click: vi.fn() }) as unknown as HTMLButtonElement),
    setNativeValue: vi.fn(),
    sleep: vi.fn(() => Promise.resolve()),
    waitForCaptchaClear: vi.fn(() => Promise.resolve()),
    waitForGeneration: vi.fn(() => Promise.resolve()),
    waitForQueueSlot: vi.fn(() => Promise.resolve()),
    detectSunoViewMode: vi.fn(() => "list"),
  }));

  vi.doMock("../../shared/playlist-dom", () => ({
    clickPlaylistRowByName: vi.fn(() => Promise.resolve()),
    ensureClipRowsLoadedByIds: ensureClipRowsLoadedByIdsMock,
    fillPlaylistNameAndCreate: vi.fn(() => Promise.resolve()),
    multiSelectClips: vi.fn(() => Promise.resolve()),
    openAddToPlaylistDialogViaCmdP: vi.fn(() => Promise.resolve({} as HTMLElement)),
    waitForPlaylistDialogClose: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../../shared/playlist-scrape", () => ({
    scrapePlaylistsFromMe: vi.fn(() => []),
  }));

  vi.doMock("../lib/auto-capture", () => ({
    triggerPlaylistCaptureFailSoft: vi.fn(() => Promise.resolve()),
  }));

  vi.doMock("../lib/ack-probe", () => ({
    createAckWaiter: vi.fn(() => vi.fn(() => Promise.resolve())),
    markAck: vi.fn(() => Promise.resolve({ submissions: 0, domInFlight: 0 })),
  }));

  vi.doMock("../lib/entry-retry", () => ({
    runEntryWithRetry: vi.fn(() => Promise.resolve({ outcome: "success" })),
  }));

  vi.doMock("../lib/inject-retry", () => ({
    InjectNotAcknowledgedError: class InjectNotAcknowledgedError extends Error {},
    injectWithVerification: vi.fn(() => Promise.resolve()),
  }));

  const content = await import("../entrypoints/content");
  content.default.main({} as NonNullable<Parameters<typeof content.default.main>[0]>);

  const runHandler = handlers.get("run");
  if (!runHandler) {
    throw new Error("run message handler was not registered");
  }
  return { ensureClipRowsLoadedByIdsMock, progressMessages, runHandler };
}

describe("content.ts playlist 追加失敗時の resume state", () => {
  beforeEach(() => {
    writeResumeStateMock.mockReset();
  });

  it("Given 通常 run で playlist row 解決が失敗 When run Then tracker が観測した submittedClipIds を保存する", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", style: "style 1", lyrics: "" },
      { name: "track-2", style: "style 2", lyrics: "" },
    ];
    const currentSubmittedClipIds = Array.from(
      { length: entries.length * CLIPS_PER_REQUEST },
      (_, index) => `current-clip-${index + 1}`,
    );
    const { progressMessages, runHandler } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      new Error("playlist rows missing"),
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
      },
    });
    await vi.waitFor(() => expect(writeResumeStateMock).toHaveBeenCalledTimes(1));

    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "collection-a",
        failedIndex: entries.length,
        total: entries.length,
        submittedClipIds: currentSubmittedClipIds,
        playlistExpectedClipCount: entries.length * CLIPS_PER_REQUEST,
      }),
    );
    expect(progressMessages).toContainEqual(
      expect.objectContaining({
        phase: PHASE.ERROR,
        index: entries.length,
      }),
    );
  });

  it("Given 全 entry 生成済みで playlist row 解決が失敗 When resume run Then 保存済み submittedClipIds と期待件数を保持する", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", style: "style 1", lyrics: "" },
      { name: "track-2", style: "style 2", lyrics: "" },
    ];
    const submittedClipIds = Array.from(
      { length: entries.length * CLIPS_PER_REQUEST },
      (_, index) => `clip-${index + 1}`,
    );
    const { runHandler } = await loadContentScriptWithPlaylistRows([], new Error("playlist rows missing"));

    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
        range: { start: entries.length, end: entries.length - 1 },
        submittedClipIds,
      },
    });
    await vi.waitFor(() => expect(writeResumeStateMock).toHaveBeenCalledTimes(1));

    expect(writeResumeStateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "collection-a",
        failedIndex: entries.length,
        total: entries.length,
        submittedClipIds,
        playlistExpectedClipCount: entries.length * CLIPS_PER_REQUEST,
      }),
    );
  });

  it("Given 2 entries で 3 ID しか保存されていない When playlist-only resume Then warn して ensureClipRows へ進む", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", style: "style 1", lyrics: "" },
      { name: "track-2", style: "style 2", lyrics: "" },
    ];
    const submittedClipIds = ["clip-1", "clip-2", "clip-3"];
    const { ensureClipRowsLoadedByIdsMock, runHandler } = await loadContentScriptWithPlaylistRows(
      [],
      [],
    );

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
        range: { start: entries.length, end: entries.length - 1 },
        submittedClipIds,
        playlistExpectedClipCount: entries.length * CLIPS_PER_REQUEST,
      },
    });
    await vi.waitFor(() => expect(ensureClipRowsLoadedByIdsMock).toHaveBeenCalledTimes(1));

    expect(ensureClipRowsLoadedByIdsMock).toHaveBeenCalledWith(
      submittedClipIds,
      expect.objectContaining({ titleFallbackMap: expect.any(Map) }),
    );
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("expected 4, got 3"),
    );
    warnSpy.mockRestore();
  });

  it("Given 旧 payload が期待件数なしで playlist-only resume When run Then warn して ensureClipRows へ進む", async () => {
    const entries: PromptEntry[] = [
      { name: "track-1", style: "style 1", lyrics: "" },
      { name: "track-2", style: "style 2", lyrics: "" },
    ];
    const submittedClipIds = ["clip-1", "clip-2", "clip-3"];
    const { ensureClipRowsLoadedByIdsMock, runHandler } = await loadContentScriptWithPlaylistRows(
      [],
      [],
    );

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    runHandler({
      data: {
        entries,
        playlistName: "vj | regression",
        collectionId: "collection-a",
        range: { start: entries.length, end: entries.length - 1 },
        submittedClipIds,
      },
    });
    await vi.waitFor(() => expect(ensureClipRowsLoadedByIdsMock).toHaveBeenCalledTimes(1));

    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("expected 4, got 3"),
    );
    warnSpy.mockRestore();
  });

  it("Given collection の manual range run When playlist 追加 Then range 内で生成した ID 件数だけを要求する", async () => {
    const entries = Array.from(
      { length: 24 },
      (_, index): PromptEntry => ({
        name: `track-${index + 1}`,
        style: `style ${index + 1}`,
        lyrics: "",
      }),
    );
    const range = { start: 4, end: 7 };
    const currentSubmittedClipIds = Array.from(
      { length: (range.end - range.start + 1) * CLIPS_PER_REQUEST },
      (_, index) => `range-clip-${index + 1}`,
    );
    const rows = currentSubmittedClipIds.map(() => ({}) as HTMLElement);
    const { ensureClipRowsLoadedByIdsMock, runHandler } = await loadContentScriptWithPlaylistRows(
      currentSubmittedClipIds,
      rows,
    );

    runHandler({
      data: {
        entries,
        playlistName: "vj | manual range",
        collectionId: "collection-a",
        range,
      },
    });
    await vi.waitFor(() => expect(ensureClipRowsLoadedByIdsMock).toHaveBeenCalledTimes(1));

    expect(ensureClipRowsLoadedByIdsMock).toHaveBeenCalledWith(
      currentSubmittedClipIds,
      expect.objectContaining({ isAborted: expect.any(Function) }),
    );
    expect(writeResumeStateMock).not.toHaveBeenCalled();
  });
});
