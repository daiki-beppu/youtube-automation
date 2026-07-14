// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BALANCED_RUN_PACING, CLIPS_PER_REQUEST, INFLIGHT_STALL_TIMEOUT_MS, PHASE } from "../../shared/constants";
import { scrollAndMultiSelectByIds } from "../../shared/playlist-dom";
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
    durationErrorsById: {} as Record<string, Error | undefined>,
    pendingClipIds: [] as string[],
    requestFeedPollError: undefined as Error | undefined,
    abortOnRequestFeedPoll: false,
    requestFeedPoll: vi.fn(async (ids: string[]) => {
      if (harness.abortOnRequestFeedPoll) {
        harness.handlers.get("stop")?.({ data: undefined });
      }
      if (harness.requestFeedPollError) {
        throw harness.requestFeedPollError;
      }
      const requested = new Set(ids);
      harness.pendingClipIds = harness.pendingClipIds.filter((id) => !requested.has(id));
      return [];
    }),
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
  requestFeedPoll: harness.requestFeedPoll,
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
    getPendingIdsByIds: vi.fn((ids: string[]) => ids.filter((id) => harness.pendingClipIds.includes(id))),
    getDuration: vi.fn((id: string) => {
      const durationError = harness.durationErrorsById[id];
      if (durationError) {
        throw durationError;
      }
      return Object.prototype.hasOwnProperty.call(harness.durationsById, id) ? harness.durationsById[id] : 120;
    }),
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

function makeSelectedMode(
  groupRole: "radiogroup" | "tablist",
  controlRole: "radio" | "tab",
  selectedAttribute: "aria-checked" | "aria-selected",
  names: readonly string[],
  selectedName: string,
): void {
  const group = document.createElement("div");
  group.setAttribute("role", groupRole);
  group.setAttribute("aria-label", "翻訳されたグループ名");
  for (const name of names) {
    const control = document.createElement("button");
    control.setAttribute("role", controlRole);
    control.setAttribute(selectedAttribute, String(name === selectedName));
    control.textContent = name;
    group.appendChild(control);
  }
  document.body.appendChild(group);
}

function makeLyricsMode(selectedName: "Write" | "Prompt" | "Instrumental"): void {
  makeSelectedMode("radiogroup", "radio", "aria-checked", ["Write", "Prompt", "Instrumental"], selectedName);
}

function makeCreateFormMode(selectedName: "Simple" | "Advanced" | "Sounds"): void {
  makeSelectedMode("tablist", "tab", "aria-selected", ["Simple", "Advanced", "Sounds"], selectedName);
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
  regenerateDurationOutliers: boolean;
} {
  harness.submittedClipIds = Array.from({ length: entries.length * 2 }, (_, index) => `generated-clip-${index + 1}`);
  return {
    entries,
    playlistName: "clm | preflight",
    collectionId: "20260601-clm-preflight-collection",
    runMode: "serial",
    regenerateDurationOutliers: true,
  };
}

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  harness.sendMessage.mockReset();
  harness.sendMessage.mockImplementation(() => undefined);
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
  harness.durationErrorsById = {};
  harness.pendingClipIds = [];
  harness.requestFeedPollError = undefined;
  harness.abortOnRequestFeedPoll = false;
  harness.requestFeedPoll.mockReset();
  harness.requestFeedPoll.mockImplementation(async (ids: string[]) => {
    if (harness.abortOnRequestFeedPoll) {
      harness.handlers.get("stop")?.({ data: undefined });
    }
    if (harness.requestFeedPollError) {
      throw harness.requestFeedPollError;
    }
    const requested = new Set(ids);
    harness.pendingClipIds = harness.pendingClipIds.filter((id) => !requested.has(id));
    return [];
  });
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
    [
      "regenerateDurationOutliers が非 boolean",
      { regenerateDurationOutliers: "true" },
      /run\.regenerateDurationOutliers/,
    ],
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

  it("Given option 欠落の旧 run payload When run を受ける Then 既定 ON で実行を開始する", async () => {
    makeRunnableSunoDom("Grid");
    await loadContentScript();
    const payload = makeRunPayload(makePromptEntries(1));
    delete (payload as Partial<typeof payload>).regenerateDurationOutliers;

    expect(getRunHandler()({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(progressPayloads()).toEqual(expect.arrayContaining([expect.objectContaining({ phase: PHASE.FINISHED })]));
  });

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

  it.each([
    [
      "Lyrics mode = Prompt",
      () => {
        makeTextarea(null);
        makeLyricsMode("Prompt");
        makeCreateFormMode("Advanced");
      },
      "Lyrics mode が Prompt になっています。Write に切り替えてください。",
    ],
    [
      "Create form mode = Simple",
      () => {
        makeLyricsMode("Write");
        makeCreateFormMode("Simple");
      },
      "Advanced タブを選択してください。",
    ],
  ] as const)(
    "Given %s で非空 lyrics When run を受ける Then 状態診断つき ERROR で停止する",
    async (_label, arrange, expected) => {
      makeViewButton("Newest ▼");
      makeViewButton("Grid");
      arrange();
      await loadContentScript();
      const runHandler = getRunHandler();
      const entries = [{ name: "vocal", style: "neo soul", lyrics: "sing this" }];
      harness.runEntryWithRetry.mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
        try {
          await options.attempt();
          return { outcome: "ok" };
        } catch (error) {
          return options.isFatal(error) ? { outcome: "fatal", error } : { outcome: "failed", error };
        }
      });

      expect(runHandler({ data: makeRunPayload(entries) })).toEqual({ ok: true });

      await vi.waitFor(() =>
        expect(progressPayloads()).toEqual(
          expect.arrayContaining([
            expect.objectContaining({
              phase: PHASE.ERROR,
              message: expect.stringContaining(expected),
            }),
          ]),
        ),
      );
      expect(harness.feedPollerStop).toHaveBeenCalledOnce();
    },
  );

  it("Given ARIA 状態を特定できず Lyrics 欄がない When run を受ける Then 3 項目 checklist つき ERROR で停止する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = [{ name: "vocal", style: "neo soul", lyrics: "sing this" }];
    harness.runEntryWithRetry.mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
      try {
        await options.attempt();
        return { outcome: "ok" };
      } catch (error) {
        return options.isFatal(error) ? { outcome: "fatal", error } : { outcome: "failed", error };
      }
    });

    expect(runHandler({ data: makeRunPayload(entries) })).toEqual({ ok: true });

    await vi.waitFor(() => {
      const errorMessage = progressPayloads().find(
        (payload): payload is { phase: string; message: string } =>
          typeof payload === "object" && payload !== null && "phase" in payload && payload.phase === PHASE.ERROR,
      )?.message;
      expect(errorMessage).toContain("Advanced タブが選択されているか");
      expect(errorMessage).toContain("Lyrics mode が Write になっているか");
      expect(errorMessage).toContain("UI 言語が日本語になっていないか（英語推奨）");
    });
    expect(harness.feedPollerStop).toHaveBeenCalledOnce();
  });

  it("Given collection server と Lyrics 欄が同時に利用不能 When run を受ける Then server ERROR を先に出す", async () => {
    makeViewButton("Grid");
    makeTextarea(null);
    harness.sendMessage.mockImplementation((type: string) => {
      if (type === "fetchCollectionPromptResponse") {
        return Promise.reject(new Error("fetch failed"));
      }
      return undefined;
    });
    await loadContentScript();

    expect(
      getRunHandler()({ data: makeRunPayload([{ name: "missing-lyrics", style: "ambient", lyrics: "lyrics" }]) }),
    ).toEqual({
      ok: true,
    });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());

    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.ERROR,
          message: expect.stringContaining("collection server から実行対象を取得できません"),
        }),
      ]),
    );
    expect(progressPayloads()).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ message: expect.stringContaining("Lyrics 欄が見つかりません") }),
      ]),
    );
    expect(harness.sendMessage).toHaveBeenCalledWith("fetchCollectionPromptResponse", {
      baseUrl: "http://localhost:8787",
      collectionId: "20260601-clm-preflight-collection",
    });
  });

  it("Given fetchServerInfo 非対応の旧 server は正常で Lyrics 欄だけがない When run を受ける Then 従来の Lyrics ERROR を出す", async () => {
    makeViewButton("Grid");
    makeTextarea(null);
    harness.sendMessage.mockImplementation((type: string) => {
      if (type === "fetchServerInfo") {
        return Promise.reject(new Error("HTTP 404"));
      }
      if (type === "fetchCollectionPromptResponse") {
        return Promise.resolve({ entries: [], duration_filter: { min_sec: 60, max_sec: 300 } });
      }
      return undefined;
    });
    harness.runEntryWithRetry.mockImplementationOnce(async (options: RunEntryWithRetryOptions) => {
      try {
        await options.attempt();
        return { outcome: "ok" };
      } catch (error) {
        return options.isFatal(error) ? { outcome: "fatal", error } : { outcome: "failed", error };
      }
    });
    await loadContentScript();

    expect(
      getRunHandler()({ data: makeRunPayload([{ name: "missing-lyrics", style: "ambient", lyrics: "lyrics" }]) }),
    ).toEqual({
      ok: true,
    });
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());

    expect(harness.sendMessage).not.toHaveBeenCalledWith("fetchServerInfo", expect.anything());
    expect(harness.sendMessage).toHaveBeenCalledWith("fetchCollectionPromptResponse", {
      baseUrl: "http://localhost:8787",
      collectionId: "20260601-clm-preflight-collection",
    });
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.ERROR,
          message: expect.stringContaining("Lyrics 欄が見つかりません"),
        }),
      ]),
    );
  });

  it("Given Lyrics 欄がなく entry.lyrics が空 When run を受ける Then従来どおり停止せず Generate する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    const onGenerate = vi.fn();
    makeGenerateButtonWithClickObserver(onGenerate);
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = [{ name: "instrumental", style: "cinematic", lyrics: "" }];

    expect(runHandler({ data: makeRunPayload(entries) })).toEqual({ ok: true });

    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: PHASE.FINISHED, total: 1 })]),
    );
    expect(onGenerate).toHaveBeenCalledOnce();
  });

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
    makeLyricsMode("Write");
    makeCreateFormMode("Advanced");
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
    const errorMessage = (
      progressPayloads().find(
        (payload): payload is { phase: string; message: string } =>
          typeof payload === "object" && payload !== null && "phase" in payload && payload.phase === PHASE.ERROR,
      ) as { message: string }
    ).message;
    expect(errorMessage).toContain("Advanced タブが選択されているか");
    expect(errorMessage).toContain("Lyrics mode が Write になっているか");
    expect(errorMessage).toContain("UI 言語が日本語になっていないか（英語推奨）");
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

  it("Given serial mode と再生成 OFF で全clipがduration外 When 実行する Then 再生成せず全clipをplaylist候補に保持する", async () => {
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    const clickGenerate = vi.fn(() => appendSubmittedClipIdsForRequest("serial-off-clip"));
    makeGenerateButtonWithClickObserver(clickGenerate);
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(1);
    const payload = {
      ...makeRunPayload(entries),
      regenerateDurationOutliers: false,
      durationFilter: { min_sec: 75, max_sec: 240 },
    };
    harness.submittedClipIds = [];
    harness.durationsById = { "serial-off-clip-1": 45, "serial-off-clip-2": 46 };

    expect(runHandler({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce(), { timeout: 3000 });
    expect(clickGenerate).toHaveBeenCalledTimes(1);
    expect(harness.droppedClipIds).toEqual([]);
    expect(harness.acceptedClipIds).toEqual(["serial-off-clip-1", "serial-off-clip-2"]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.DONE,
          index: 0,
          acceptedClipIds: ["serial-off-clip-1", "serial-off-clip-2"],
          message: expect.stringContaining("再生成 OFF"),
        }),
        expect.objectContaining({ phase: PHASE.ADDING_TO_PLAYLIST }),
        expect.objectContaining({ phase: PHASE.FINISHED }),
      ]),
    );
  });

  it("Given serial mode と再生成 ON で初回2回が全NG When 3回目がOK Then retry 2回をprogress表示して採用する", async () => {
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    let clickCount = 0;
    const clickGenerate = vi.fn(() => {
      clickCount += 1;
      harness.submittedClipIds.push(`serial-on-${clickCount}-a`, `serial-on-${clickCount}-b`);
    });
    makeGenerateButtonWithClickObserver(clickGenerate);
    addCompletedRemixCard();
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(1);
    const payload = {
      ...makeRunPayload(entries),
      durationFilter: { min_sec: 75, max_sec: 240 },
    };
    harness.submittedClipIds = [];
    harness.durationsById = {
      "serial-on-1-a": 45,
      "serial-on-1-b": 46,
      "serial-on-2-a": 360,
      "serial-on-2-b": 361,
      "serial-on-3-a": 120,
      "serial-on-3-b": 180,
    };

    expect(runHandler({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce(), { timeout: 3000 });
    expect(clickGenerate).toHaveBeenCalledTimes(3);
    expect(harness.droppedClipIds).toEqual(["serial-on-1-a", "serial-on-1-b", "serial-on-2-a", "serial-on-2-b"]);
    expect(harness.acceptedClipIds).toEqual(["serial-on-3-a", "serial-on-3-b"]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.WAITING_SLOT,
          message: expect.stringContaining("retry 1/2"),
          log: { kind: "retry", entryName: "pattern-1", attempt: 1, max: 2 },
        }),
        expect.objectContaining({
          phase: PHASE.WAITING_SLOT,
          message: expect.stringContaining("retry 2/2"),
          log: { kind: "retry", entryName: "pattern-1", attempt: 2, max: 2 },
        }),
        expect.objectContaining({
          phase: PHASE.DONE,
          acceptedClipIds: ["serial-on-3-a", "serial-on-3-b"],
          yieldRetryCount: 2,
        }),
      ]),
    );
  });

  it("Given serial mode と再生成 OFF でduration評価がthrow When 実行する Then DONEに見せずENTRY_FAILEDにする", async () => {
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    makeGenerateButtonWithClickObserver(() => appendSubmittedClipIdsForRequest("serial-error-clip"));
    addCompletedRemixCard();
    await loadContentScript();
    const entries = makePromptEntries(1);
    const payload = { ...makeRunPayload(entries), regenerateDurationOutliers: false };
    harness.submittedClipIds = [];
    harness.durationErrorsById = { "serial-error-clip-1": new Error("feed unavailable") };

    expect(getRunHandler()({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce(), { timeout: 3000 });
    expect(harness.acceptedClipIds).toEqual([]);
    expect(harness.droppedClipIds).toEqual(["serial-error-clip-1", "serial-error-clip-2"]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ phase: PHASE.ENTRY_FAILED, message: "feed unavailable" }),
        expect.objectContaining({ phase: PHASE.FINISHED, message: expect.stringContaining("失敗分のみ再実行") }),
      ]),
    );
    expect(progressPayloads()).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: PHASE.ADDING_TO_PLAYLIST })]),
    );
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
    let generateCount = 0;
    makeGenerateButtonWithClickObserver(() => {
      generateCount += 1;
      const firstClipNumber = generateCount * 2 - 1;
      const generatedIds = [`queue-duration-clip-${firstClipNumber}`, `queue-duration-clip-${firstClipNumber + 1}`];
      harness.submittedClipIds.push(...generatedIds);
      if (generateCount > 2) {
        harness.pendingClipIds = generatedIds;
      }
    });
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
      "queue-duration-clip-5": 45,
      "queue-duration-clip-6": 46,
      "queue-duration-clip-7": 45,
      "queue-duration-clip-8": 46,
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
    expect(generateCount).toBe(4);
    expect(harness.waitForQueueSlot).toHaveBeenCalledTimes(4);
    const progress = progressPayloads();
    const secondOriginalSubmittedAt = progress.findIndex(
      (payload) =>
        typeof payload === "object" &&
        payload !== null &&
        "phase" in payload &&
        payload.phase === PHASE.SUBMITTED &&
        "index" in payload &&
        payload.index === 1 &&
        "yieldRetryCount" in payload &&
        payload.yieldRetryCount === 0,
    );
    const firstDurationRetryAt = progress.findIndex(
      (payload) =>
        typeof payload === "object" &&
        payload !== null &&
        "phase" in payload &&
        payload.phase === PHASE.WAITING_SLOT &&
        "index" in payload &&
        payload.index === 1 &&
        "yieldRetryCount" in payload &&
        payload.yieldRetryCount === 1,
    );
    expect(secondOriginalSubmittedAt).toBeGreaterThanOrEqual(0);
    expect(firstDurationRetryAt).toBeGreaterThan(secondOriginalSubmittedAt);
    expect(harness.acceptedClipIds).toEqual(["queue-duration-clip-1", "queue-duration-clip-2"]);
    expect(harness.requestFeedPoll).toHaveBeenCalledWith(["queue-duration-clip-5", "queue-duration-clip-6"]);
    expect(harness.droppedClipIds).toEqual([
      "queue-duration-clip-3",
      "queue-duration-clip-4",
      "queue-duration-clip-5",
      "queue-duration-clip-6",
      "queue-duration-clip-7",
      "queue-duration-clip-8",
    ]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          phase: PHASE.DONE,
          index: 0,
          acceptedClipIds: ["queue-duration-clip-1", "queue-duration-clip-2"],
        }),
        expect.objectContaining({
          phase: PHASE.WAITING_SLOT,
          index: 1,
          message: expect.stringContaining("retry 1/2"),
          log: { kind: "retry", entryName: "pattern-2", attempt: 1, max: 2 },
        }),
        expect.objectContaining({
          phase: PHASE.WAITING_SLOT,
          index: 1,
          message: expect.stringContaining("retry 2/2"),
          log: { kind: "retry", entryName: "pattern-2", attempt: 2, max: 2 },
        }),
        expect.objectContaining({
          phase: PHASE.ENTRY_FAILED,
          index: 1,
          message: "duration guard NG (75-240s): queue-duration-clip-7, queue-duration-clip-8",
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

  it("Given queue mode で複数 entry の clip が全て duration filter 外 When 再生成する Then 最初の retry 完了待ち前に全 retry を ACK 済みにする", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    const events: string[] = [];
    let generateCount = 0;
    makeGenerateButtonWithClickObserver(() => {
      generateCount += 1;
      const firstClipNumber = generateCount * 2 - 1;
      const generatedIds = [`queue-parallel-retry-${firstClipNumber}`, `queue-parallel-retry-${firstClipNumber + 1}`];
      events.push(`generate-${generateCount}`);
      harness.submittedClipIds.push(...generatedIds);
      if (generateCount > 2) {
        harness.pendingClipIds.push(...generatedIds);
      }
    });
    addCompletedRemixCard();
    await loadContentScript();
    const entries = makePromptEntries(2);
    const payload = {
      ...makeRunPayload(entries),
      runMode: "queue" as const,
      durationFilter: { min_sec: 75, max_sec: 240 },
    };
    harness.submittedClipIds = [];
    harness.durationsById = {
      "queue-parallel-retry-1": 45,
      "queue-parallel-retry-2": 46,
      "queue-parallel-retry-3": 45,
      "queue-parallel-retry-4": 46,
      "queue-parallel-retry-5": 120,
      "queue-parallel-retry-6": 180,
      "queue-parallel-retry-7": 120,
      "queue-parallel-retry-8": 180,
    };
    harness.requestFeedPoll.mockImplementation(async (ids: string[]) => {
      events.push(`poll-${ids[0]}`);
      const requested = new Set(ids);
      harness.pendingClipIds = harness.pendingClipIds.filter((id) => !requested.has(id));
      return [];
    });

    expect(getRunHandler()({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce(), { timeout: 3000 });
    expect(generateCount).toBe(4);
    expect(harness.waitForQueueSlot).toHaveBeenCalledTimes(4);
    expect(events.indexOf("generate-4")).toBeGreaterThan(events.indexOf("generate-3"));
    expect(events.indexOf("generate-4")).toBeLessThan(events.findIndex((event) => event.startsWith("poll-")));
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ phase: PHASE.DONE, index: 0, yieldRetryCount: 1 }),
        expect.objectContaining({ phase: PHASE.DONE, index: 1, yieldRetryCount: 1 }),
      ]),
    );
  });

  it("Given queue 再生成clipの完了待ちがthrow When 失敗確定する Then originalとretry IDsをresume候補から除去する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    let generateCount = 0;
    makeGenerateButtonWithClickObserver(() => {
      generateCount += 1;
      const generatedIds = [`queue-error-${generateCount}-a`, `queue-error-${generateCount}-b`];
      harness.submittedClipIds.push(...generatedIds);
      if (generateCount > 1) {
        harness.pendingClipIds = generatedIds;
      }
    });
    addCompletedRemixCard();
    await loadContentScript();
    const entries = makePromptEntries(1);
    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    harness.durationsById = { "queue-error-1-a": 45, "queue-error-1-b": 46 };
    harness.requestFeedPollError = new Error("feed unavailable");

    expect(getRunHandler()({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(
      () =>
        expect(writeResumeState).toHaveBeenCalledWith(
          expect.objectContaining({ failedIndices: [0], submittedClipIds: [] }),
        ),
      { timeout: 3000 },
    );
    expect(harness.droppedClipIds).toEqual([
      "queue-error-2-a",
      "queue-error-2-b",
      "queue-error-1-a",
      "queue-error-1-b",
    ]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: PHASE.ENTRY_FAILED, message: "feed unavailable" })]),
    );
  });

  it("Given queue 再生成clipの完了待ち中にstop When 中断保存する Then 中断suffixのoriginalとretry IDsを除去する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    let generateCount = 0;
    makeGenerateButtonWithClickObserver(() => {
      generateCount += 1;
      const generatedIds = [`queue-stop-${generateCount}-a`, `queue-stop-${generateCount}-b`];
      harness.submittedClipIds.push(...generatedIds);
      if (generateCount > 1) {
        harness.pendingClipIds = generatedIds;
      }
    });
    addCompletedRemixCard();
    await loadContentScript();
    const entries = makePromptEntries(1);
    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    harness.durationsById = { "queue-stop-1-a": 45, "queue-stop-1-b": 46 };
    harness.abortOnRequestFeedPoll = true;

    expect(getRunHandler()({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(
      () =>
        expect(writeResumeState).toHaveBeenCalledWith(
          expect.objectContaining({
            failedIndex: 0,
            remainingIndices: [0],
            submittedClipIds: [],
          }),
        ),
      { timeout: 3000 },
    );
    expect(harness.droppedClipIds).toEqual(["queue-stop-2-a", "queue-stop-2-b", "queue-stop-1-a", "queue-stop-1-b"]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: PHASE.STOPPED, index: 0 })]),
    );
  });

  it("Given 複数queue retryの1件目ACK後 When 2件目の投入中にstop Then 全entryを再開候補にしてoriginalとretry IDsを除去する", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    let generateCount = 0;
    makeGenerateButtonWithClickObserver(() => {
      generateCount += 1;
      harness.submittedClipIds.push(`queue-submit-stop-${generateCount}-a`, `queue-submit-stop-${generateCount}-b`);
    });
    addCompletedRemixCard();
    await loadContentScript();
    const entries = makePromptEntries(2);
    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    harness.durationsById = {
      "queue-submit-stop-1-a": 45,
      "queue-submit-stop-1-b": 46,
      "queue-submit-stop-2-a": 45,
      "queue-submit-stop-2-b": 46,
    };
    harness.waitForQueueSlot.mockImplementation(async () => {
      if (harness.waitForQueueSlot.mock.calls.length === 4) {
        harness.handlers.get("stop")?.({ data: undefined });
      }
    });

    expect(getRunHandler()({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(
      () =>
        expect(writeResumeState).toHaveBeenCalledWith(
          expect.objectContaining({
            failedIndex: 0,
            remainingIndices: [0, 1],
            submittedClipIds: [],
          }),
        ),
      { timeout: 3000 },
    );
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(generateCount).toBe(3);
    expect(harness.droppedClipIds).toEqual([
      "queue-submit-stop-3-a",
      "queue-submit-stop-3-b",
      "queue-submit-stop-1-a",
      "queue-submit-stop-1-b",
      "queue-submit-stop-2-a",
      "queue-submit-stop-2-b",
    ]);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: PHASE.STOPPED, index: 0 })]),
    );
  });

  it("Given queue duration retry の WAITING_SLOT 中にstop When 中断保存する Then Generateを増やさず同じentryを再開候補に残す", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    let generateCount = 0;
    makeGenerateButtonWithClickObserver(() => {
      generateCount += 1;
      harness.submittedClipIds.push(`queue-slot-stop-${generateCount}-a`, `queue-slot-stop-${generateCount}-b`);
    });
    addCompletedRemixCard();
    await loadContentScript();
    const entries = makePromptEntries(1);
    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    harness.durationsById = { "queue-slot-stop-1-a": 45, "queue-slot-stop-1-b": 46 };
    harness.waitForQueueSlot.mockImplementation(async () => {
      if (harness.waitForQueueSlot.mock.calls.length === 2) {
        harness.handlers.get("stop")?.({ data: undefined });
      }
    });

    expect(getRunHandler()({ data: payload })).toEqual({ ok: true });

    await vi.waitFor(
      () =>
        expect(writeResumeState).toHaveBeenCalledWith(
          expect.objectContaining({
            failedIndex: 0,
            remainingIndices: [0],
            submittedClipIds: [],
          }),
        ),
      { timeout: 3000 },
    );
    await vi.waitFor(() => expect(harness.feedPollerStop).toHaveBeenCalledOnce());
    expect(generateCount).toBe(1);
    expect(harness.droppedClipIds).toEqual(["queue-slot-stop-1-a", "queue-slot-stop-1-b"]);
    expect(new Set(harness.droppedClipIds).size).toBe(harness.droppedClipIds.length);
    expect(progressPayloads()).toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: PHASE.STOPPED, index: 0 })]),
    );
    expect(progressPayloads()).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: PHASE.ENTRY_FAILED, index: 0 })]),
    );
  });

  it("Given 後続originalがduration OKのqueue再生成中にstop When 保存した残りを再開 Then entryごとに再生成した1組だけをplaylistへ渡す", async () => {
    makeViewButton("Newest ▼");
    makeViewButton("Grid");
    makeTextarea(null);
    makeTextarea("lyrics-textarea");
    let generateCount = 0;
    makeGenerateButtonWithClickObserver(() => {
      generateCount += 1;
      const generatedIds = [`queue-resume-${generateCount}-a`, `queue-resume-${generateCount}-b`];
      harness.submittedClipIds.push(...generatedIds);
      if (generateCount === 3) {
        harness.pendingClipIds = generatedIds;
      }
    });
    addCompletedRemixCard();
    await loadContentScript();
    const entries = makePromptEntries(2);
    const runHandler = getRunHandler();
    const payload = { ...makeRunPayload(entries), runMode: "queue" as const };
    harness.submittedClipIds = [];
    harness.durationsById = {
      "queue-resume-1-a": 45,
      "queue-resume-1-b": 46,
      "queue-resume-2-a": 120,
      "queue-resume-2-b": 121,
      "queue-resume-4-a": 120,
      "queue-resume-4-b": 121,
      "queue-resume-5-a": 122,
      "queue-resume-5-b": 123,
    };
    harness.abortOnRequestFeedPoll = true;

    expect(runHandler({ data: payload })).toEqual({ ok: true });
    await vi.waitFor(
      () =>
        expect(writeResumeState).toHaveBeenCalledWith(
          expect.objectContaining({ failedIndex: 0, remainingIndices: [0, 1], submittedClipIds: [] }),
        ),
      { timeout: 3000 },
    );

    harness.abortOnRequestFeedPoll = false;
    harness.pendingClipIds = [];
    harness.sendMessage.mockClear();
    expect(
      runHandler({
        data: {
          ...payload,
          indices: [0, 1],
          submittedClipIds: [],
        },
      }),
    ).toEqual({ ok: true });

    await vi.waitFor(
      () =>
        expect(progressPayloads()).toEqual(
          expect.arrayContaining([expect.objectContaining({ phase: PHASE.FINISHED })]),
        ),
      { timeout: 3000 },
    );
    expect(scrollAndMultiSelectByIds).toHaveBeenCalledWith(
      ["queue-resume-4-a", "queue-resume-4-b", "queue-resume-5-a", "queue-resume-5-b"],
      expect.any(Object),
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
