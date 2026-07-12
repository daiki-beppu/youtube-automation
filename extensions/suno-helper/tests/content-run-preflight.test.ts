// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BALANCED_RUN_PACING, CLIPS_PER_REQUEST, INFLIGHT_STALL_TIMEOUT_MS, PHASE } from "../../shared/constants";
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
    acceptedClipIds: [] as string[],
    droppedClipIds: [] as string[],
    durationsById: {} as Record<string, number | undefined>,
    waitForGeneration: vi.fn<() => Promise<void>>(async () => undefined),
    waitForQueueSlot: vi.fn<(maxGeneratingClips: number, options?: unknown) => Promise<void>>(async () => undefined),
    // 既定は実装呼び出し（下の shared/dom mock factory で束縛）。空 queue で WAITING_SLOT が
    // 失敗しない回帰テストを実装ごと通すため、テスト個別の stall 注入だけ mockImplementation で上書きする。
    actualWaitForQueueSlot: null as null | ((maxGeneratingClips: number, options?: unknown) => Promise<void>),
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
  harness.actualWaitForQueueSlot = actual.waitForQueueSlot as unknown as (
    maxGeneratingClips: number,
    options?: unknown,
  ) => Promise<void>;
  return {
    ...actual,
    abortableSleep: vi.fn(async () => undefined),
    injectAdvancedFields: vi.fn(async () => undefined),
    waitForCaptchaClear: vi.fn(async () => undefined),
    waitForGeneration: harness.waitForGeneration,
    waitForQueueSlot: harness.waitForQueueSlot,
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
    getPendingIdsByIds: vi.fn(() => []),
    getDuration: vi.fn((id: string) =>
      Object.prototype.hasOwnProperty.call(harness.durationsById, id) ? harness.durationsById[id] : 120,
    ),
    markAccepted: vi.fn((ids: string[]) => {
      const submitted = new Set(harness.submittedClipIds);
      for (const id of ids) {
        if (submitted.has(id) && !harness.acceptedClipIds.includes(id)) {
          harness.acceptedClipIds.push(id);
        }
      }
    }),
    getAcceptedSubmittedIds: vi.fn(() => harness.acceptedClipIds),
    dropSubmittedIds: vi.fn((ids: string[]) => {
      const dropped = new Set(ids);
      harness.droppedClipIds.push(...ids);
      harness.submittedClipIds = harness.submittedClipIds.filter((id) => !dropped.has(id));
      harness.acceptedClipIds = harness.acceptedClipIds.filter((id) => !dropped.has(id));
    }),
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

function makeBeforeInputOnlyLexicalLyrics(initialText: string): HTMLElement {
  const lexical = document.createElement("div");
  lexical.className = "lyrics-editor-content";
  lexical.setAttribute("data-lexical-editor", "true");
  lexical.setAttribute("contenteditable", "true");
  lexical.textContent = initialText;
  lexical.addEventListener("beforeinput", (e) => {
    const ev = e as InputEvent;
    lexical.textContent = ev.data ?? "";
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

function appendSubmittedClipIdsForRequest(prefix: string): void {
  const next = harness.submittedClipIds.length + 1;
  harness.submittedClipIds.push(`${prefix}-${next}`, `${prefix}-${next + 1}`);
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
  runMode: "serial";
} {
  harness.submittedClipIds = Array.from({ length: entries.length * 2 }, (_, index) => `generated-clip-${index + 1}`);
  return {
    entries,
    playlistName: "clm | preflight",
    collectionId: "20260601-clm-preflight-collection",
    runMode: "serial",
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
  harness.acceptedClipIds = [];
  harness.droppedClipIds = [];
  harness.durationsById = {};
  harness.waitForGeneration.mockReset();
  harness.waitForGeneration.mockResolvedValue(undefined);
  harness.waitForQueueSlot.mockReset();
  // 既定は実装呼び出し（vi.fn(actual.waitForQueueSlot) 相当）。no-op 既定にすると
  // 「Remix 0 かつ空 queue で初回 WAITING_SLOT で失敗しない」回帰テストが空虚に通る。
  harness.waitForQueueSlot.mockImplementation((maxGeneratingClips, options) =>
    harness.actualWaitForQueueSlot!(maxGeneratingClips, options),
  );
  harness.handlers.clear();
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('content onMessage("run"): Run 開始前の Suno view preflight', () => {
  it("duration guard の pending 減少後は新しい stall deadline まで待機し、停滞時だけ timeout する", async () => {
    await loadContentScript();
    const { waitForAttemptClipsComplete } = await import("../entrypoints/content");
    let currentTime = 0;
    let pollCount = 0;
    const pendingClipIds = new Set(["clip-a", "clip-b"]);

    await expect(
      waitForAttemptClipsComplete(["clip-a", "clip-b"], {
        getPendingIdsByIds: (ids) => ids.filter((id) => pendingClipIds.has(id)),
        requestFeedPoll: async () => {
          pollCount += 1;
          if (pollCount === 1) {
            pendingClipIds.delete("clip-a");
          }
        },
        abortableSleep: async () => {
          currentTime += INFLIGHT_STALL_TIMEOUT_MS;
        },
        isAborted: () => false,
        now: () => currentTime,
      }),
    ).rejects.toThrow(`最後の進捗からの経過時間=${INFLIGHT_STALL_TIMEOUT_MS}ms`);
    expect(pollCount).toBe(2);
  });

  it("duration guard の pending 増加は stall deadline をリセットしない", async () => {
    await loadContentScript();
    const { waitForAttemptClipsComplete } = await import("../entrypoints/content");
    let currentTime = 0;
    let pollCount = 0;
    const pendingClipIds = new Set(["clip-a", "clip-b"]);

    await expect(
      waitForAttemptClipsComplete(["clip-a", "clip-b", "clip-c"], {
        getPendingIdsByIds: (ids) => ids.filter((id) => pendingClipIds.has(id)),
        requestFeedPoll: async () => {
          pollCount += 1;
          pendingClipIds.add("clip-c");
        },
        abortableSleep: async () => {
          currentTime += INFLIGHT_STALL_TIMEOUT_MS;
        },
        isAborted: () => false,
        now: () => currentTime,
      }),
    ).rejects.toThrow(`最後の進捗からの経過時間=${INFLIGHT_STALL_TIMEOUT_MS}ms`);
    expect(pollCount).toBe(1);
  });

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
    ["runMode 欠落", { runMode: undefined }, /run\.runMode/],
    ["runMode が未知値", { runMode: "parallel" }, /run\.runMode/],
    ["runMode が prototype 継承 key", { runMode: "toString" }, /run\.runMode/],
    ["submittedClipIds が非配列", { submittedClipIds: "clip-1" }, /run\.submittedClipIds/],
    ["submittedClipIds に非 string", { submittedClipIds: ["clip-1", 2] }, /run\.submittedClipIds/],
    [
      "submittedClipIdsAreDurationFiltered が非 boolean",
      { submittedClipIdsAreDurationFiltered: "true" },
      /run\.submittedClipIdsAreDurationFiltered/,
    ],
    ["playlistExpectedClipCount が小数", { playlistExpectedClipCount: 1.5 }, /run\.playlistExpectedClipCount/],
    ["playlistExpectedClipCount が負数", { playlistExpectedClipCount: -1 }, /run\.playlistExpectedClipCount/],
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

  it("Given durationFilter が小数秒 When run を受ける Then payload を受理して実行を開始する", async () => {
    makeViewButton("Grid");
    await loadContentScript();
    const runHandler = getRunHandler();

    const result = runHandler({
      data: {
        ...makeRunPayload(),
        durationFilter: { min_sec: 1.5, max_sec: 300.25 },
      },
    });

    expect(result).toEqual({ ok: true });
    expect(harness.feedPollerStart).toHaveBeenCalledOnce();
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
  });

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
      addCompletedRemixCard();
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
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
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
              message: expect.stringContaining("beforeinput fallback"),
            }),
          ]),
        ),
      { timeout: 3000 },
    );
    expect(onGenerate).not.toHaveBeenCalled();
    expect(lyrics.textContent).toBe("old lyrics");
    expect(consoleError).toHaveBeenCalledWith(
      "[suno-helper] Lyrics 欄への全注入方式が失敗しました",
      expect.objectContaining({
        entryName: "lexical",
        lyricsLength: "new lexical lyrics".length,
        lyrics: "new lexical lyrics",
        actualLength: "old lyrics".length,
        actualLyrics: "old lyrics",
        diagnosticMessage: expect.stringMatching(
          new RegExp(
            `expectedLength=${"new lexical lyrics".length}, actualLength=${"old lyrics".length}, ` +
              'firstDiffIndex=0, expectedExcerpt="new lexical lyrics", actualExcerpt="old lyrics"',
          ),
        ),
        pasteError: expect.any(Error),
        fallbackError: expect.any(Error),
      }),
    );
    consoleError.mockRestore();
  });

  it("Given Lexical lyrics editor が paste を反映せず beforeinput を反映する When run を受ける Then fallback 後に Generate へ進む", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    const lyrics = makeBeforeInputOnlyLexicalLyrics("old lyrics");
    let lyricsAtGenerate = "";
    makeGenerateButtonWithClickObserver(() => {
      lyricsAtGenerate = lyrics.textContent ?? "";
      addCompletedRemixCard();
    });
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = [
      {
        name: "beforeinput-fallback",
        style: "neo soul",
        lyrics: "new lexical lyrics",
      },
    ];

    const result = runHandler({ data: makeRunPayload(entries) });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce(), { timeout: 3000 });
    expect(lyrics.textContent).toBe("new lexical lyrics");
    expect(lyricsAtGenerate).toBe("new lexical lyrics");
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

  it("Given queue mode When 1 entry 目の生成完了が未観測 Then 完了待ちの前に 2 entry 目を投入する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    const style = makeTextarea(null);
    makeTextarea("lyrics-textarea");
    const clickedStyles: string[] = [];
    makeGenerateButtonWithClickObserver(() => {
      clickedStyles.push(style.value);
      appendSubmittedClipIdsForRequest("queue-clip");
    });
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = [
      { name: "queue-1", style: "style 1", lyrics: "" },
      { name: "queue-2", style: "style 2", lyrics: "" },
    ];
    let releaseFirstGeneration!: () => void;
    const firstGeneration = new Promise<void>((resolve) => {
      releaseFirstGeneration = resolve;
    });
    harness.waitForGeneration.mockImplementationOnce(() => firstGeneration);

    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    const result = runHandler({ data: payload });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(clickedStyles).toContain("style 1"));
    let secondClickBeforeCompletion = false;
    try {
      await vi.waitFor(() => expect(clickedStyles).toContain("style 2"), { timeout: 200 });
      secondClickBeforeCompletion = true;
    } catch {
      secondClickBeforeCompletion = false;
    } finally {
      releaseFirstGeneration();
    }
    expect(secondClickBeforeCompletion).toBe(true);
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    const progress = progressPayloads();
    const submitted0Index = progress.findIndex(
      (payload) =>
        typeof payload === "object" &&
        payload !== null &&
        (payload as { phase?: string; index?: number }).phase === PHASE.SUBMITTED &&
        (payload as { phase?: string; index?: number }).index === 0,
    );
    const submitted1Index = progress.findIndex(
      (payload) =>
        typeof payload === "object" &&
        payload !== null &&
        (payload as { phase?: string; index?: number }).phase === PHASE.SUBMITTED &&
        (payload as { phase?: string; index?: number }).index === 1,
    );
    const done0Index = progress.findIndex(
      (payload) =>
        typeof payload === "object" &&
        payload !== null &&
        (payload as { phase?: string; index?: number }).phase === PHASE.DONE &&
        (payload as { phase?: string; index?: number }).index === 0,
    );
    expect(submitted0Index).toBeGreaterThanOrEqual(0);
    expect(submitted1Index).toBeGreaterThan(submitted0Index);
    expect(done0Index).toBeGreaterThan(submitted1Index);
  });

  it("Given queue mode かつ preset が上限超過 When 11 entry を実行する Then 10 request cap で待機し 11件目を投入しない", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    makeGenerateButtonWithClickObserver(() => appendSubmittedClipIdsForRequest("queue-cap-clip"));
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(11);
    let releaseEleventhSlot!: () => void;
    const eleventhSlot = new Promise<void>((resolve) => {
      releaseEleventhSlot = resolve;
    });
    harness.waitForQueueSlot.mockImplementation(async () => {
      if (harness.waitForQueueSlot.mock.calls.length === 11) {
        await eleventhSlot;
      }
    });

    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    const result = runHandler({ data: payload });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.waitForQueueSlot).toHaveBeenCalledTimes(11));
    expect(harness.waitForQueueSlot.mock.calls.map(([maxGeneratingClips]) => maxGeneratingClips)).toEqual(
      Array.from({ length: 11 }, () => 20),
    );
    expect(document.querySelectorAll("article[aria-busy='true']")).toHaveLength(20);
    releaseEleventhSlot();
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
  });

  it("Given queue mode の投入済み clip が duration 未観測 When fatal 停止する Then raw submitted IDs を resume state に保持する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    makeGenerateButtonWithClickObserver(() => {
      harness.submittedClipIds = ["queue-pending-clip-1", "queue-pending-clip-2"];
    });
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(2);
    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    harness.durationsById = {
      "queue-pending-clip-1": undefined,
      "queue-pending-clip-2": undefined,
    };
    harness.runEntryWithRetry.mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
      await options.attempt();
      return { outcome: "fatal" as const, error: new Error("fatal queue stop") };
    });

    const result = runHandler({ data: payload });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(writeResumeState).toHaveBeenCalledOnce(), { timeout: 3000 });
    expect(writeResumeState).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "20260601-clm-preflight-collection",
        submittedClipIds: ["queue-pending-clip-1", "queue-pending-clip-2"],
        submittedClipIdsAreDurationFiltered: false,
        playlistExpectedClipCount: 2,
      }),
    );
  });

  it("Given queue mode で一部 entry の clip が全て duration filter 外 When 完了待ち後に確定する Then 失敗分を保存し playlist 追加へ進まない", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    makeGenerateButtonWithClickObserver(() => appendSubmittedClipIdsForRequest("queue-duration-clip"));
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(2);
    const payload = {
      ...makeRunPayload(entries),
      runMode: "queue" as const,
      durationFilter: { min_sec: 75, max_sec: 240 },
    };
    harness.submittedClipIds = [];
    harness.durationsById = {
      "queue-duration-clip-1": 120,
      "queue-duration-clip-2": 180,
      "queue-duration-clip-3": 45,
      "queue-duration-clip-4": 46,
    };

    const result = runHandler({ data: payload });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(
      () =>
        expect(writeResumeState).toHaveBeenCalledWith(
          expect.objectContaining({
            collectionId: "20260601-clm-preflight-collection",
            failedIndex: entries.length,
            total: entries.length,
            failedIndices: [1],
          }),
        ),
      { timeout: 3000 },
    );
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(harness.acceptedClipIds).toEqual(["queue-duration-clip-1", "queue-duration-clip-2"]);
    expect(harness.droppedClipIds).toEqual(["queue-duration-clip-3", "queue-duration-clip-4"]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.DONE,
          index: 0,
          acceptedClipIds: ["queue-duration-clip-1", "queue-duration-clip-2"],
        }),
        expect.objectContaining({
          phase: PHASE.ENTRY_FAILED,
          index: 1,
          message: "duration guard NG (75-240s): queue-duration-clip-3, queue-duration-clip-4",
          log: { kind: "skip", entryName: "pattern-2" },
        }),
        expect.objectContaining({
          phase: PHASE.FINISHED,
          total: entries.length,
          message: expect.stringContaining("失敗分のみ再実行"),
        }),
      ]),
    );
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.FINISHED,
          message: expect.stringContaining("entry 2"),
        }),
      ]),
    );
    expect(progressPayloads()).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: PHASE.ADDING_TO_PLAYLIST })]),
    );
  });

  it("Given queue mode が DOM-only ACK で clip ID 未観測 entry を含む When 完了待ち後に確定する Then warn して DONE に縮退する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    let clickCount = 0;
    const clickGenerate = vi.fn(() => {
      clickCount += 1;
      if (clickCount === 2) {
        appendSubmittedClipIdsForRequest("queue-observed-clip");
      }
    });
    makeGenerateButtonWithClickObserver(clickGenerate);
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(2);
    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    harness.runEntryWithRetry.mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
      const actual = await vi.importActual<typeof import("../lib/entry-retry")>("../lib/entry-retry");
      return actual.runEntryWithRetry(options);
    });
    harness.runEntryWithRetry.mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
      const actual = await vi.importActual<typeof import("../lib/entry-retry")>("../lib/entry-retry");
      return actual.runEntryWithRetry(options);
    });

    const result = runHandler({ data: payload });

    expect(result).toEqual({ ok: true });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce(), { timeout: 3000 });
    expect(clickGenerate).toHaveBeenCalledTimes(2);
    expect(warn).toHaveBeenCalledWith(
      "[suno-helper] entry 0 の clip ID を bridge で観測できなかったため duration guard を skip します。",
    );
    expect(harness.acceptedClipIds).toEqual(["queue-observed-clip-1", "queue-observed-clip-2"]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.DONE,
          index: 0,
        }),
        expect.objectContaining({
          phase: PHASE.DONE,
          index: 1,
          acceptedClipIds: ["queue-observed-clip-1", "queue-observed-clip-2"],
        }),
        expect.objectContaining({
          phase: PHASE.ADDING_TO_PLAYLIST,
          total: entries.length,
        }),
        expect.objectContaining({
          phase: PHASE.FINISHED,
          total: entries.length,
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
    expect(writeResumeState).toHaveBeenCalledWith(
      expect.objectContaining({
        failedIndex: entries.length,
        submittedClipIds: ["queue-observed-clip-1", "queue-observed-clip-2"],
        submittedClipIdsAreDurationFiltered: true,
        playlistExpectedClipCount: 2,
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
