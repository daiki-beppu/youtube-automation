// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BALANCED_RUN_PACING, CLIPS_PER_REQUEST, PHASE } from "../../shared/constants";
import type { EntryRunResult, RunEntryWithRetryOptions } from "../lib/entry-retry";
import { writeResumeState } from "../lib/resume-state";
import { makePromptEntries, markBbox } from "./_helpers";

const harness = vi.hoisted(() => {
  const handlers = new Map<string, (message: { data: unknown }) => unknown>();
  const feedPollerStart = vi.fn();
  const feedPollerStop = vi.fn();
  const runEntryWithRetry = vi.fn(async (options: RunEntryWithRetryOptions): Promise<EntryRunResult> => {
    await options.attempt();
    return { outcome: "ok" };
  });
  const legacyReadSpeedPresetId = vi.fn(async () => "fast");
  const legacyResolveSpeedPreset = vi.fn(() => ({
    interCreateDelayMs: 1234,
    jitterMs: 0,
    maxInflightRequests: 1,
    maxInjectRetry: 9,
    injectAckTimeoutMs: 12345,
    maxEntryRetry: 9,
  }));

  return {
    handlers,
    sendMessage: vi.fn(),
    onMessage: vi.fn((type: string, handler: (message: { data: unknown }) => unknown) => {
      handlers.set(type, handler);
      return vi.fn();
    }),
    attachBridgeListener: vi.fn(),
    createFeedPoller: vi.fn(() => ({
      start: feedPollerStart,
      stop: feedPollerStop,
    })),
    feedPollerStart,
    feedPollerStop,
    runEntryWithRetry,
    legacyReadSpeedPresetId,
    legacyResolveSpeedPreset,
    requestSliderSet: vi.fn(),
    submittedClipIds: [] as string[],
  };
});

vi.mock("../lib/preset-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/preset-state")>("../lib/preset-state");
  return {
    ...actual,
    readSpeedPresetId: harness.legacyReadSpeedPresetId,
    resolveSpeedPreset: harness.legacyResolveSpeedPreset,
    applyJitter: vi.fn((baseMs: number) => baseMs),
  };
});

vi.mock("../lib/inject-retry", async () => {
  const actual = await vi.importActual<typeof import("../lib/inject-retry")>("../lib/inject-retry");
  return {
    ...actual,
    injectWithVerification: vi.fn(actual.injectWithVerification),
  };
});

vi.mock("../../shared/dom", async () => {
  const actual = await vi.importActual<typeof import("../../shared/dom")>("../../shared/dom");
  return {
    ...actual,
    abortableSleep: vi.fn(async () => undefined),
    injectAdvancedFields: vi.fn(async () => undefined),
    waitForQueueSlot: vi.fn(actual.waitForQueueSlot),
    waitForCaptchaClear: vi.fn(async () => undefined),
    waitForGeneration: vi.fn(async () => undefined),
  };
});

vi.mock("../lib/messaging", () => ({
  onMessage: harness.onMessage,
  sendMessage: harness.sendMessage,
}));

vi.mock("../lib/bridge-listener", () => ({
  attachBridgeListener: harness.attachBridgeListener,
  createFeedPoller: harness.createFeedPoller,
  requestFeedPoll: vi.fn(() => Promise.resolve([])),
  requestSliderSet: harness.requestSliderSet,
}));

vi.mock("../lib/entry-retry", () => ({
  runEntryWithRetry: harness.runEntryWithRetry,
}));

vi.mock("../lib/clip-tracker", () => ({
  createClipTracker: vi.fn(() => ({
    clearSubmittedIds: vi.fn(),
    getSubmittedIds: vi.fn(() => harness.submittedClipIds),
    getPendingSubmittedIds: vi.fn(() => []),
    getDuration: vi.fn(() => 120),
    getInFlightCount: vi.fn(() => 0),
    hasObservedAnyTraffic: vi.fn(() => true),
    lastChangeAt: vi.fn(() => Date.now()),
    submissionCount: vi.fn(() => harness.submittedClipIds.length),
  })),
}));

vi.mock("../lib/storage", () => ({
  serverUrlItem: { getValue: vi.fn(() => Promise.resolve("http://localhost:8787")) },
  downloadFormatItem: { getValue: vi.fn(() => Promise.resolve("mp3")) },
  readDownloadFormat: vi.fn(() => Promise.resolve("mp3")),
}));

vi.mock("../lib/resume-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/resume-state")>("../lib/resume-state");
  return {
    ...actual,
    clearResumeStateForCollection: vi.fn(() => Promise.resolve()),
    writeResumeState: vi.fn(() => Promise.resolve()),
  };
});

vi.mock("../lib/download", () => ({
  triggerDownloadAll: vi.fn(() => Promise.resolve()),
}));

vi.mock("../lib/download-flow", () => ({
  createDownloadFlow: vi.fn(() => ({
    installMessageHandlers: vi.fn(),
    downloadBestEffort: vi.fn(() => Promise.resolve(null)),
    performDownload: vi.fn(() => Promise.resolve()),
    retryDownload: vi.fn(() => Promise.resolve({ completedAndCleared: true })),
  })),
}));

// 完了時リロード前の snapshot 退避。実物は chrome.storage へアクセスするため node/jsdom 環境では mock 必須。
// 退避契約そのものの検証は content-finished-snapshot.test.ts が担う。
vi.mock("../lib/finished-snapshot", () => ({
  writeFinishedSnapshot: vi.fn(() => Promise.resolve()),
  readFreshFinishedSnapshot: vi.fn(() => Promise.resolve(null)),
  clearFinishedSnapshot: vi.fn(() => Promise.resolve()),
}));

vi.mock("../../shared/api", async () => ({
  ...(await vi.importActual<typeof import("../../shared/api")>("../../shared/api")),
  postDownloaded: vi.fn(() => Promise.resolve()),
}));

vi.mock("../../shared/playlist-dom", () => ({
  clickPlaylistRowByName: vi.fn(() => Promise.resolve()),
  fillPlaylistNameAndCreate: vi.fn(() => Promise.resolve()),
  openAddToPlaylistDialogViaCmdP: vi.fn(() => Promise.resolve(document.createElement("div"))),
  readSelectedClipIds: vi.fn(() => Promise.resolve([])),
  scrollAndMultiSelectByIds: vi.fn((clipIds: string[]) => Promise.resolve(clipIds.length)),
  waitForPlaylistDialogClose: vi.fn(() => Promise.resolve()),
}));

async function loadContentScript(): Promise<void> {
  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => definition);
  const content = await import("../entrypoints/content");
  content.default.main({} as NonNullable<Parameters<typeof content.default.main>[0]>);
}

function getRunHandler(): (message: { data: unknown }) => unknown {
  const runHandler = harness.handlers.get("run");
  if (!runHandler) {
    throw new Error('test fixture 不整合: "run" handler が登録されていません。');
  }
  return runHandler;
}

function makeViewButton(label: string): void {
  const button = document.createElement("button");
  button.textContent = label;
  button.setAttribute("aria-haspopup", "listbox");
  markBbox(button, 120, 32);
  document.body.appendChild(button);
}

function makeGenericButton(label: string): void {
  const button = document.createElement("button");
  button.textContent = label;
  markBbox(button, 120, 32);
  document.body.appendChild(button);
}

function makeTextarea(testId: string | null): HTMLTextAreaElement {
  const textarea = document.createElement("textarea");
  if (testId) {
    textarea.dataset.testid = testId;
  }
  markBbox(textarea, 320, 96);
  document.body.appendChild(textarea);
  return textarea;
}

function makeGenerateButton(): HTMLButtonElement {
  const button = document.createElement("button");
  button.textContent = "Create";
  button.addEventListener("click", () => {
    addStatusOnlyCard();
    addStatusOnlyCard();
  });
  markBbox(button, 120, 40);
  document.body.appendChild(button);
  return button;
}

function makeGenerateButtonWithClickObserver(onClick: () => void): HTMLButtonElement {
  const button = document.createElement("button");
  button.textContent = "Create";
  button.addEventListener("click", () => {
    onClick();
    addStatusOnlyCard();
    addStatusOnlyCard();
  });
  markBbox(button, 120, 40);
  document.body.appendChild(button);
  return button;
}

class DataTransferStub {
  private store = new Map<string, string>();
  setData(type: string, value: string): void {
    this.store.set(type, value);
  }
  getData(type: string): string {
    return this.store.get(type) ?? "";
  }
}

class ClipboardEventStub extends Event {
  readonly clipboardData: DataTransferStub | null;
  constructor(type: string, init: EventInit & { clipboardData?: DataTransferStub } = {}) {
    super(type, init);
    this.clipboardData = init.clipboardData ?? null;
  }
}

function makeLexicalLyrics(initialText: string): HTMLElement {
  const lexical = document.createElement("div");
  lexical.className = "lyrics-editor-content";
  lexical.setAttribute("data-lexical-editor", "true");
  lexical.setAttribute("contenteditable", "true");
  lexical.textContent = initialText;
  lexical.addEventListener("paste", (e) => {
    const ev = e as unknown as ClipboardEventStub;
    lexical.textContent = ev.clipboardData?.getData("text/plain") ?? "";
    e.preventDefault();
  });
  markBbox(lexical, 320, 96);
  document.body.appendChild(lexical);
  return lexical;
}

function makeUnresponsiveLexicalLyrics(initialText: string): HTMLElement {
  const lexical = document.createElement("div");
  lexical.className = "lyrics-editor-content";
  lexical.setAttribute("data-lexical-editor", "true");
  lexical.setAttribute("contenteditable", "true");
  lexical.textContent = initialText;
  markBbox(lexical, 320, 96);
  document.body.appendChild(lexical);
  return lexical;
}

function addCompletedRemixCard(): void {
  const card = document.createElement("div");
  for (const label of ["Select clip", "Remix clip", "Edit title"]) {
    const button = document.createElement("button");
    button.setAttribute("aria-label", label);
    card.appendChild(button);
    markBbox(button, 24, 24);
  }
  markBbox(card, 240, 80);
  document.body.appendChild(card);
}

function addStatusOnlyCard(): void {
  const card = document.createElement("article");
  card.setAttribute("aria-busy", "true");
  const button = document.createElement("button");
  button.setAttribute("aria-label", "Select clip");
  markBbox(button, 24, 24);
  card.appendChild(button);
  markBbox(card, 240, 80);
  document.body.appendChild(card);
}

function makeRunnableSunoDom(viewLabel: "List ▼" | "Waveform" | "Grid"): void {
  makeViewButton("Newest ▼");
  makeViewButton(viewLabel);
  makeTextarea(null);
  makeTextarea("lyrics-textarea");
  makeGenerateButton();
  addCompletedRemixCard();
}

function makeRunnableEmptyQueueSunoDom(viewLabel: "Waveform" | "Grid"): void {
  makeViewButton(`${viewLabel} ▼`);
  makeTextarea(null);
  makeTextarea("lyrics-textarea");
  makeGenerateButton();
}

function progressPayloads(): unknown[] {
  return harness.sendMessage.mock.calls.filter(([type]) => type === "progress").map(([, payload]) => payload);
}

function makeRunPayload(entries = makePromptEntries(0)): {
  entries: ReturnType<typeof makePromptEntries>;
  playlistName: string;
  collectionId: string;
} {
  harness.submittedClipIds = Array.from({ length: entries.length * 2 }, (_, index) => `generated-clip-${index + 1}`);
  return {
    entries,
    playlistName: "clm | preflight",
    collectionId: "20260601-clm-preflight-collection",
  };
}

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal("DataTransfer", DataTransferStub);
  vi.stubGlobal("ClipboardEvent", ClipboardEventStub);
  (document as unknown as { execCommand: ReturnType<typeof vi.fn> }).execCommand = vi.fn(() => true);
  harness.runEntryWithRetry.mockImplementation(async (options: RunEntryWithRetryOptions) => {
    await options.attempt();
    return { outcome: "ok" };
  });
  harness.submittedClipIds = [];
  harness.handlers.clear();
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('content onMessage("run"): Run 開始前の Suno view preflight', () => {
  it("Given 旧 array payload When run を受ける Then fail-loud し副作用を起こさない", async () => {
    await loadContentScript();
    const runHandler = getRunHandler();

    expect(() => runHandler({ data: makePromptEntries(1) })).toThrow(/run payload/);
    expect(harness.sendMessage).not.toHaveBeenCalled();
    expect(harness.feedPollerStart).not.toHaveBeenCalled();
  });

  it.each([
    ["collectionId 欠落", { collectionId: undefined }, /run\.collectionId/],
    ["playlistName 欠落", { playlistName: undefined }, /run\.playlistName/],
    ["durationFilter が null", { durationFilter: null }, /run\.durationFilter/],
    ["durationFilter が空 object", { durationFilter: {} }, /run\.durationFilter/],
    ["durationFilter が boolean", { durationFilter: false }, /run\.durationFilter/],
    ["durationFilter が min > max", { durationFilter: { min_sec: 301, max_sec: 300 } }, /run\.durationFilter/],
    [
      "submittedClipIdsAreDurationFiltered が非 boolean",
      { submittedClipIdsAreDurationFiltered: "true" },
      /run\.submittedClipIdsAreDurationFiltered/,
    ],
  ] as const)(
    "Given %s payload When run を受ける Then fail-loud し副作用を起こさない",
    async (_label, override, message) => {
      await loadContentScript();
      const runHandler = getRunHandler();

      expect(() => runHandler({ data: { ...makeRunPayload(makePromptEntries(1)), ...override } })).toThrow(message);
      expect(harness.sendMessage).not.toHaveBeenCalled();
      expect(harness.feedPollerStart).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["文字列", "0", /run\.indices/],
    ["null", null, /run\.indices/],
    ["空配列", [], /run\.indices/],
    ["非整数", [1.5], /run\.indices/],
    ["負数", [-1], /run\.indices/],
    ["範囲外", [2], /run\.indices/],
    ["重複", [0, 0], /run\.indices/],
  ] as const)(
    "Given indices が%s When run を受ける Then fail-loud し副作用を起こさない",
    async (_label, indices, message) => {
      await loadContentScript();
      const runHandler = getRunHandler();
      const entries = makePromptEntries(2);

      expect(() => runHandler({ data: { ...makeRunPayload(entries), indices } })).toThrow(message);
      expect(harness.sendMessage).not.toHaveBeenCalled();
      expect(harness.feedPollerStart).not.toHaveBeenCalled();
    },
  );

  it("Given view dropdown が検出不能 When run を受ける Then ERROR progress を emit し feed poller を開始しない", async () => {
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(2);

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    expect(harness.sendMessage).toHaveBeenCalledOnce();
    expect(harness.sendMessage).toHaveBeenCalledWith(
      "progress",
      expect.objectContaining({
        phase: PHASE.ERROR,
        total: entries.length,
        message: expect.stringContaining("表示ビューを検出できません"),
      }),
    );
    expect(harness.feedPollerStart).not.toHaveBeenCalled();
    expect(harness.feedPollerStop).not.toHaveBeenCalled();
  });

  it("Given view mode に一致しない単独 button がある When run を受ける Then ERROR progress を emit し feed poller を開始しない", async () => {
    makeGenericButton("Settings");
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(1);

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    expect(harness.sendMessage).toHaveBeenCalledWith(
      "progress",
      expect.objectContaining({
        phase: PHASE.ERROR,
        total: entries.length,
        message: expect.stringContaining("表示ビューを検出できません"),
      }),
    );
    expect(harness.feedPollerStart).not.toHaveBeenCalled();
  });

  it.each(["List ▼", "Waveform", "Grid"] as const)(
    "Given view dropdown が %s When run を受ける Then ERROR progress を emit せず feed poller を開始する",
    async (viewLabel) => {
      makeViewButton(viewLabel);
      await loadContentScript();
      const runHandler = getRunHandler();

      const result = runHandler({ data: makeRunPayload() });

      expect(result).toEqual({ ok: true });
      expect(harness.feedPollerStart).toHaveBeenCalledOnce();
      await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
      expect(progressPayloads()).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            phase: PHASE.FINISHED,
            total: 0,
          }),
        ]),
      );
      expect(progressPayloads()).not.toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            phase: PHASE.ERROR,
          }),
        ]),
      );
    },
  );

  it("Given view dropdown が装飾付き Waveform 表記 When run を受ける Then ERROR progress を emit せず feed poller を開始する", async () => {
    makeViewButton("Waveform ▼");
    await loadContentScript();
    const runHandler = getRunHandler();

    const result = runHandler({ data: makeRunPayload() });

    expect(result).toEqual({ ok: true });
    expect(harness.feedPollerStart).toHaveBeenCalledOnce();
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(progressPayloads()).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.ERROR,
        }),
      ]),
    );
  });

  it.each(["Waveform", "Grid"] as const)(
    "Given Newest sort dropdown と %s view dropdown がある When run を受ける Then ERROR progress を emit せず feed poller を開始する",
    async (viewLabel) => {
      makeViewButton("Newest ▼");
      makeViewButton(viewLabel);
      await loadContentScript();
      const runHandler = getRunHandler();

      const result = runHandler({ data: makeRunPayload() });

      expect(result).toEqual({ ok: true });
      expect(harness.feedPollerStart).toHaveBeenCalledOnce();
      await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
      expect(progressPayloads()).not.toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            phase: PHASE.ERROR,
          }),
        ]),
      );
    },
  );

  it.each(["List ▼", "Waveform", "Grid"] as const)(
    "Given view dropdown が %s かつ entries がある When run を受ける Then WAITING_SLOT から FINISHED まで進む",
    async (viewLabel) => {
      makeRunnableSunoDom(viewLabel);
      await loadContentScript();
      const runHandler = getRunHandler();
      const entries = makePromptEntries(2);

      const result = runHandler({ data: makeRunPayload(entries) });

      expect(result).toEqual({ ok: true });
      await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
      expect(progressPayloads()).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ phase: PHASE.WAITING_SLOT, index: 0, total: entries.length }),
          expect.objectContaining({ phase: PHASE.INJECTING, index: 0, total: entries.length }),
          expect.objectContaining({ phase: PHASE.GENERATING, index: 0, total: entries.length }),
          expect.objectContaining({ phase: PHASE.DONE, index: 0, total: entries.length }),
          expect.objectContaining({ phase: PHASE.WAITING_SLOT, index: 1, total: entries.length }),
          expect.objectContaining({ phase: PHASE.INJECTING, index: 1, total: entries.length }),
          expect.objectContaining({ phase: PHASE.GENERATING, index: 1, total: entries.length }),
          expect.objectContaining({ phase: PHASE.DONE, index: 1, total: entries.length }),
          expect.objectContaining({ phase: PHASE.FINISHED, total: entries.length }),
        ]),
      );
      expect(progressPayloads()).not.toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            phase: PHASE.ERROR,
          }),
        ]),
      );
    },
  );

  it("Given Lexical lyrics editor When run を受ける Then actual run handler が paste 完了後に Generate する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    const lyrics = makeLexicalLyrics("old lyrics");
    let lyricsAtGenerate = "";
    makeGenerateButtonWithClickObserver(() => {
      lyricsAtGenerate = lyrics.textContent ?? "";
    });
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = [{ name: "lexical", style: "neo soul", lyrics: "new lexical lyrics" }];

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(lyrics.textContent).toBe("new lexical lyrics");
    expect(lyricsAtGenerate).toBe("new lexical lyrics");
  });

  it("Given Lexical lyrics editor と空 lyrics When run を受ける Then actual run handler がクリア完了後に Generate する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    const lyrics = makeLexicalLyrics("old lyrics");
    (document as unknown as { execCommand: ReturnType<typeof vi.fn> }).execCommand = vi.fn((command) => {
      if (command === "delete") {
        lyrics.textContent = "";
      }
      return true;
    });
    let lyricsAtGenerate = "not clicked";
    makeGenerateButtonWithClickObserver(() => {
      lyricsAtGenerate = lyrics.textContent ?? "";
    });
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = [{ name: "instrumental", style: "cinematic instrumental", lyrics: "" }];

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(lyrics.textContent).toBe("");
    expect(lyricsAtGenerate).toBe("");
  });

  it("Given Lexical lyrics editor が paste を反映しない When run を受ける Then Generate へ進まず ERROR を emit する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    const lyrics = makeUnresponsiveLexicalLyrics("old lyrics");
    const onGenerate = vi.fn();
    makeGenerateButtonWithClickObserver(onGenerate);
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = [{ name: "lexical", style: "neo soul", lyrics: "new lexical lyrics" }];
    harness.runEntryWithRetry.mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
      try {
        await options.attempt();
        return { outcome: "ok" };
      } catch (error) {
        return options.isFatal(error) ? { outcome: "fatal", error } : { outcome: "failed", error };
      }
    });

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(
      () =>
        expect(progressPayloads()).toEqual(
          expect.arrayContaining([
            expect.objectContaining({
              phase: PHASE.ERROR,
              message: expect.stringContaining("Lyrics 欄への paste 反映に失敗しました"),
            }),
          ]),
        ),
      { timeout: 3000 },
    );
    expect(onGenerate).not.toHaveBeenCalled();
    expect(lyrics.textContent).toBe("old lyrics");
  });

  it("Given indices 指定で supported view かつ entries がある When run を受ける Then 指定 index だけを絶対 index で処理する", async () => {
    makeRunnableSunoDom("Grid");
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(3);

    const payload = { ...makeRunPayload(entries), indices: [0, 2] };
    harness.submittedClipIds = ["generated-clip-1", "generated-clip-2", "generated-clip-3", "generated-clip-4"];

    const result = runHandler({ data: payload });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ phase: PHASE.WAITING_SLOT, index: 0, total: entries.length }),
        expect.objectContaining({ phase: PHASE.INJECTING, index: 0, total: entries.length }),
        expect.objectContaining({ phase: PHASE.GENERATING, index: 0, total: entries.length }),
        expect.objectContaining({ phase: PHASE.DONE, index: 0, total: entries.length }),
        expect.objectContaining({ phase: PHASE.WAITING_SLOT, index: 2, total: entries.length }),
        expect.objectContaining({ phase: PHASE.INJECTING, index: 2, total: entries.length }),
        expect.objectContaining({ phase: PHASE.GENERATING, index: 2, total: entries.length }),
        expect.objectContaining({ phase: PHASE.DONE, index: 2, total: entries.length }),
        expect.objectContaining({ phase: PHASE.FINISHED, total: entries.length }),
      ]),
    );
    expect(progressPayloads()).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ index: 1 }), expect.objectContaining({ phase: PHASE.ERROR })]),
    );
  });

  it("Given indices 部分実行の途中で停止 When resume state を保存する Then 未選択 index を含まない残り indices を保持する", async () => {
    makeRunnableSunoDom("Grid");
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(5);
    harness.runEntryWithRetry
      .mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
        await options.attempt();
        return { outcome: "ok" };
      })
      .mockResolvedValueOnce({ outcome: "aborted" as const });

    const result = runHandler({ data: { ...makeRunPayload(entries), indices: [0, 2, 4] } });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(writeResumeState).toHaveBeenCalledOnce(), { timeout: 3000 });
    expect(writeResumeState).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "20260601-clm-preflight-collection",
        failedIndex: 2,
        total: entries.length,
        remainingIndices: [2, 4],
      }),
    );
  });

  it.each(["Waveform", "Grid"] as const)(
    "Given %s view で Remix 0 かつ空 queue When run を受ける Then 初回 WAITING_SLOT で失敗せず FINISHED まで進む",
    async (viewLabel) => {
      makeRunnableEmptyQueueSunoDom(viewLabel);
      await loadContentScript();
      const runHandler = getRunHandler();
      const entries = makePromptEntries(2);

      const result = runHandler({ data: makeRunPayload(entries) });

      expect(result).toEqual({ ok: true });
      await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
      expect(progressPayloads()).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ phase: PHASE.WAITING_SLOT, index: 0, total: entries.length }),
          expect.objectContaining({ phase: PHASE.INJECTING, index: 0, total: entries.length }),
          expect.objectContaining({ phase: PHASE.GENERATING, index: 0, total: entries.length }),
          expect.objectContaining({ phase: PHASE.DONE, index: 0, total: entries.length }),
          expect.objectContaining({ phase: PHASE.WAITING_SLOT, index: 1, total: entries.length }),
          expect.objectContaining({ phase: PHASE.INJECTING, index: 1, total: entries.length }),
          expect.objectContaining({ phase: PHASE.GENERATING, index: 1, total: entries.length }),
          expect.objectContaining({ phase: PHASE.DONE, index: 1, total: entries.length }),
          expect.objectContaining({ phase: PHASE.FINISHED, total: entries.length }),
        ]),
      );
      expect(progressPayloads()).not.toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            phase: PHASE.ERROR,
          }),
        ]),
      );
    },
  );

  it("Given legacy sunoSpeedPreset が残っていても When run を受ける Then Balanced 固定の pacing 値で実行する", async () => {
    makeRunnableEmptyQueueSunoDom("Grid");
    await loadContentScript();
    const { waitForQueueSlot, abortableSleep } = await import("../../shared/dom");
    const { injectWithVerification } = await import("../lib/inject-retry");
    const { applyJitter } = await import("../lib/preset-state");
    const runHandler = getRunHandler();
    const entries = makePromptEntries(1);

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(waitForQueueSlot).toHaveBeenCalledWith(
      BALANCED_RUN_PACING.maxInflightRequests * CLIPS_PER_REQUEST,
      expect.objectContaining({ stallTimeoutMs: expect.any(Number) }),
    );
    expect(harness.runEntryWithRetry).toHaveBeenCalledWith(
      expect.objectContaining({
        maxRetry: BALANCED_RUN_PACING.maxEntryRetry,
        retryDelayMs: expect.any(Function),
      }),
    );
    const retryDelayMs = harness.runEntryWithRetry.mock.calls[0][0].retryDelayMs;
    expect(injectWithVerification).toHaveBeenCalledWith(
      expect.objectContaining({
        maxRetry: BALANCED_RUN_PACING.maxInjectRetry,
        ackTimeoutMs: BALANCED_RUN_PACING.injectAckTimeoutMs,
      }),
    );
    expect(applyJitter).toHaveBeenCalledWith(BALANCED_RUN_PACING.interCreateDelayMs, BALANCED_RUN_PACING.jitterMs);
    vi.mocked(applyJitter).mockClear();
    expect(retryDelayMs()).toBe(BALANCED_RUN_PACING.interCreateDelayMs);
    expect(applyJitter).toHaveBeenCalledWith(BALANCED_RUN_PACING.interCreateDelayMs, BALANCED_RUN_PACING.jitterMs);
    expect(abortableSleep).toHaveBeenCalledWith(BALANCED_RUN_PACING.interCreateDelayMs, expect.any(Function));
    expect(harness.legacyReadSpeedPresetId).not.toHaveBeenCalled();
    expect(harness.legacyResolveSpeedPreset).not.toHaveBeenCalled();
  });

  it("Given entry retry が発生する When run を受ける Then retry progress log を content 経由で emit する", async () => {
    makeRunnableSunoDom("List ▼");
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(1);
    harness.runEntryWithRetry.mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
      await options.attempt();
      options.onRetry?.(1, 2, new Error("temporary"));
      return { outcome: "ok" };
    });

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.WAITING_SLOT,
          index: 0,
          total: entries.length,
          log: { kind: "retry", entryName: "pattern-1", attempt: 1, max: 2 },
        }),
      ]),
    );
  });

  it("Given entry が retry 上限後に failed outcome になる When run を受ける Then skip progress log を content 経由で emit する", async () => {
    makeRunnableSunoDom("List ▼");
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(1);
    harness.runEntryWithRetry.mockResolvedValueOnce({ outcome: "failed" as const, error: new Error("queue timeout") });

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.ENTRY_FAILED,
          index: 0,
          total: entries.length,
          message: "queue timeout",
          log: { kind: "skip", entryName: "pattern-1" },
        }),
      ]),
    );
  });
});
