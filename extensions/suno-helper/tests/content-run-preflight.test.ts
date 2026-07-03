// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PHASE } from "../../shared/constants";
import type { EntryRunResult, RunEntryWithRetryOptions } from "../lib/entry-retry";
import { makePromptEntries, markBbox } from "./_helpers";

const harness = vi.hoisted(() => {
  const handlers = new Map<string, (message: { data: unknown }) => unknown>();
  const feedPollerStart = vi.fn();
  const feedPollerStop = vi.fn();
  const runEntryWithRetry = vi.fn(
    async (options: Pick<RunEntryWithRetryOptions, "attempt">): Promise<EntryRunResult> => {
      await options.attempt();
      return { outcome: "ok" };
    },
  );

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
    requestSliderSet: vi.fn(),
  };
});

vi.mock("../lib/preset-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/preset-state")>("../lib/preset-state");
  return {
    ...actual,
    readSpeedPresetId: vi.fn(async () => actual.DEFAULT_SPEED_PRESET_ID),
    resolveSpeedPreset: vi.fn(() => ({
      interCreateDelayMs: 0,
      jitterMs: 0,
      maxInflightRequests: 10,
      maxInjectRetry: 0,
      injectAckTimeoutMs: 100,
      maxEntryRetry: 0,
      label: "Test",
      riskNote: "Test preset",
    })),
    applyJitter: vi.fn((baseMs: number) => baseMs),
  };
});

vi.mock("../../shared/dom", async () => {
  const actual = await vi.importActual<typeof import("../../shared/dom")>("../../shared/dom");
  return {
    ...actual,
    abortableSleep: vi.fn(async () => undefined),
    injectAdvancedFields: vi.fn(async () => undefined),
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

// 完了時リロード前の snapshot 退避。実物は chrome.storage へアクセスするため node/jsdom 環境では mock 必須。
// 退避契約そのものの検証は content-finished-snapshot.test.ts が担う。
vi.mock("../lib/finished-snapshot", () => ({
  writeFinishedSnapshot: vi.fn(() => Promise.resolve()),
  readFreshFinishedSnapshot: vi.fn(() => Promise.resolve(null)),
  clearFinishedSnapshot: vi.fn(() => Promise.resolve()),
}));

vi.mock("../../shared/api", () => ({
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
  submittedClipIds: string[];
  playlistExpectedClipCount: number;
} {
  return {
    entries,
    playlistName: "clm | preflight",
    collectionId: "20260601-clm-preflight-collection",
    submittedClipIds: ["clip-a"],
    playlistExpectedClipCount: 1,
  };
}

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  harness.runEntryWithRetry.mockImplementation(async (options: Pick<RunEntryWithRetryOptions, "attempt">) => {
    await options.attempt();
    return { outcome: "ok" };
  });
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

  it("Given indices 指定で supported view かつ entries がある When run を受ける Then 指定 index だけを絶対 index で処理する", async () => {
    makeRunnableSunoDom("Grid");
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(3);

    const result = runHandler({ data: { ...makeRunPayload(entries), indices: [0, 2] } });

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

  it("Given entry retry が発生する When run を受ける Then retry progress log を content 経由で emit する", async () => {
    makeRunnableSunoDom("List ▼");
    await loadContentScript();
    const runHandler = getRunHandler();
    const entries = makePromptEntries(1);
    harness.runEntryWithRetry.mockImplementationOnce(
      async (options: Pick<RunEntryWithRetryOptions, "attempt" | "onRetry">) => {
        await options.attempt();
        options.onRetry?.(1, 2, new Error("temporary"));
        return { outcome: "ok" };
      },
    );

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
