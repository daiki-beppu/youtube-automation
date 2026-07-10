// @vitest-environment jsdom

import { act } from "react";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PHASE, type ProgressPayload } from "../../shared/constants";
import { App } from "../components/App";

const BASE_URL = "http://localhost:7873";
const MANIFEST_VERSION = "0.1.9";

const messagingMocks = vi.hoisted(() => {
  const mocks = {
    progressHandler: undefined as ((message: { data: ProgressPayload }) => void) | undefined,
    onMessage: vi.fn((type: string, handler: (message: { data: ProgressPayload }) => void) => {
      if (type === "progress") {
        mocks.progressHandler = handler;
      }
      return () => undefined;
    }),
    sendMessage: vi.fn(),
  };
  return mocks;
});

const storageMocks = vi.hoisted(() => ({
  getValue: vi.fn(async () => ""),
  setValue: vi.fn(async () => undefined),
}));

const downloadFormatMocks = vi.hoisted(() => ({
  getValue: vi.fn(async () => "mp3"),
  setValue: vi.fn(async () => undefined),
}));

const resumeStateMocks = vi.hoisted(() => ({
  readResumeState: vi.fn(async () => null),
  writeResumeState: vi.fn(async () => undefined),
}));

const presetStateMocks = vi.hoisted(() => ({
  readRunModeId: vi.fn(async () => "serial"),
  writeRunModeId: vi.fn(async () => undefined),
}));

vi.mock("wxt/browser", () => ({
  browser: {
    runtime: {
      getManifest: vi.fn(() => ({ version: MANIFEST_VERSION })),
    },
  },
}));

vi.mock("../lib/storage", () => ({
  serverUrlItem: storageMocks,
  downloadFormatItem: downloadFormatMocks,
  readDownloadFormat: vi.fn(() => downloadFormatMocks.getValue()),
  readServerSources: vi.fn(async () => [
    { id: "localhost-7873", label: "localhost", url: BASE_URL },
    { id: "localhost-7873-changed", label: "localhost changed", url: `${BASE_URL}/changed` },
  ]),
  rememberServerSource: vi.fn(async () => [
    { id: "localhost-7873", label: "localhost", url: BASE_URL },
    { id: "localhost-7873-changed", label: "localhost changed", url: `${BASE_URL}/changed` },
  ]),
}));

vi.mock("../lib/messaging", () => messagingMocks);

async function readJson(url: string): Promise<unknown> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

function defaultSendMessage(message: string, payload?: Record<string, string>): Promise<unknown> {
  if (message === "queryProgress") {
    throw new Error("runner unavailable");
  }
  if (message === "fetchCompatibilityWarning") {
    return (async () => {
      const resp = await fetch(`${payload?.baseUrl}/version`);
      if (!resp.ok) {
        return "";
      }
      const data = (await resp.json()) as { version: string; min_extension_version: string };
      if (payload?.extensionVersion === data.min_extension_version) {
        return "";
      }
      return `拡張を更新してください（拡張 ${payload?.extensionVersion} / 必要 ${data.min_extension_version} / サーバー ${data.version}）。`;
    })();
  }
  if (message === "fetchServerInfo") {
    return Promise.resolve({
      channel_name: "Localhost",
      channel_short: "local",
      hostname: "localhost",
      port: 7873,
      base_url: BASE_URL,
      label: "localhost",
    });
  }
  if (message === "fetchCollections") {
    return readJson(`${payload?.baseUrl}/collections`);
  }
  if (message === "fetchCollectionPrompts") {
    return readJson(
      `${payload?.baseUrl}/collections/${encodeURIComponent(payload?.collectionId ?? "")}/suno/prompts.json`,
    );
  }
  if (message === "fetchCollectionPromptResponse") {
    return readJson(
      `${payload?.baseUrl}/collections/${encodeURIComponent(payload?.collectionId ?? "")}/suno/prompts.json`,
    );
  }
  return Promise.resolve({ ok: true });
}

vi.mock("../lib/preset-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/preset-state")>("../lib/preset-state");
  return {
    ...actual,
    readRunModeId: presetStateMocks.readRunModeId,
    writeRunModeId: presetStateMocks.writeRunModeId,
  };
});

vi.mock("../lib/resume-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/resume-state")>("../lib/resume-state");
  return {
    ...actual,
    readResumeState: resumeStateMocks.readResumeState,
    writeResumeState: resumeStateMocks.writeResumeState,
  };
});

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

function setSelectValue(select: HTMLSelectElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
  if (!setter) {
    throw new Error("HTMLSelectElement.value setter is unavailable");
  }
  setter.call(select, value);
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find((candidate) =>
    candidate.textContent?.includes(text),
  );
  if (!button) {
    throw new Error(`button not found: ${text}`);
  }
  return button;
}

function radioByLabel(container: HTMLElement, text: string): HTMLInputElement {
  const label = Array.from(container.querySelectorAll("label")).find((candidate) =>
    candidate.textContent?.includes(text),
  );
  const input = label?.querySelector<HTMLInputElement>('input[type="radio"]');
  if (!input) {
    throw new Error(`radio not found: ${text}`);
  }
  return input;
}

function expectRangeUiAbsent(container: HTMLElement): void {
  expect(container.textContent).not.toContain("実行範囲");
  expect(container.textContent).not.toContain("範囲指定");
  expect(container.querySelector('input[name="range-mode"]')).toBeNull();
  expect(container.querySelector('[aria-label="開始 entry"]')).toBeNull();
  expect(container.querySelector('[aria-label="終了 entry"]')).toBeNull();
}

function expectControl(container: HTMLElement, control: string): HTMLElement {
  const element = container.querySelector<HTMLElement>(`[data-suno-control="${control}"]`);
  expect(element).not.toBeNull();
  return element!;
}

async function waitFor(assertion: () => void): Promise<void> {
  for (let i = 0; i < 20; i += 1) {
    try {
      assertion();
      return;
    } catch (error) {
      if (i === 19) {
        throw error;
      }
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }
  }
}

describe("Suno popup compatibility check", () => {
  let root: Root;
  let container: HTMLDivElement;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    fetchMock = vi.fn();
    storageMocks.getValue.mockResolvedValue("");
    storageMocks.setValue.mockResolvedValue(undefined);
    downloadFormatMocks.getValue.mockResolvedValue("mp3");
    downloadFormatMocks.setValue.mockResolvedValue(undefined);
    presetStateMocks.readRunModeId.mockResolvedValue("serial");
    presetStateMocks.writeRunModeId.mockResolvedValue(undefined);
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    messagingMocks.progressHandler = undefined;
    messagingMocks.onMessage.mockImplementation(
      (type: string, handler: (message: { data: ProgressPayload }) => void) => {
        if (type === "progress") {
          messagingMocks.progressHandler = handler;
        }
        return () => undefined;
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      root.render(createElement(App));
    });
  });

  async function rerenderAppWithDownloadFormat(value: string): Promise<void> {
    await act(async () => {
      root.unmount();
    });
    container.innerHTML = "";
    root = createRoot(container);
    downloadFormatMocks.getValue.mockResolvedValueOnce(value);
    await act(async () => {
      root.render(createElement(App));
    });
  }

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    storageMocks.getValue.mockResolvedValue("");
    storageMocks.setValue.mockResolvedValue(undefined);
    resumeStateMocks.readResumeState.mockResolvedValue(null);
    resumeStateMocks.writeResumeState.mockResolvedValue(undefined);
    presetStateMocks.readRunModeId.mockResolvedValue("serial");
    presetStateMocks.writeRunModeId.mockResolvedValue(undefined);
  });

  it("popup に投入方式 selector を表示し、Fast / Balanced / Safe の速度プリセットは表示しない", () => {
    expect(container.textContent).toContain("投入方式");
    expect(container.querySelector('input[name="run-mode"]')).not.toBeNull();
    expect(container.textContent).not.toContain("Fast");
    expect(container.textContent).not.toContain("Balanced");
    expect(container.textContent).not.toContain("Safe");
    expect(container.querySelector('input[name="speed-preset"]')).toBeNull();
  });

  it("progress handler が DONE + duration-check log を受けると live status を更新する", async () => {
    expect(messagingMocks.progressHandler).toBeDefined();
    const panel = container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]');
    expect(panel).not.toBeNull();
    expect(panel?.dataset.sunoPhase).toBe("idle");

    await act(async () => {
      messagingMocks.progressHandler?.({ data: { phase: PHASE.DONE, index: 1, total: 3 } });
    });
    expect(panel?.dataset.sunoPhase).toBe(PHASE.DONE);
    expect(container.textContent).not.toContain('"p2": 259s ✓');

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: {
          phase: PHASE.DONE,
          index: 1,
          total: 3,
          log: { kind: "duration-check", entryName: "p2", durationSec: 259, ok: true, maxSec: 300 },
        },
      });
    });

    expect(container.textContent).toContain('"p2": 259s ✓');
    expect(container.querySelector('[role="status"]')?.getAttribute("data-suno-status")).toBe("ok");
  });

  it("agent 操作用の root 状態属性と主要 control selector を実 DOM に公開する", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "" },
      { name: "p2", style: "ambient", lyrics: "" },
    ];
    const panel = container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]');
    expect(panel).not.toBeNull();
    expect(panel?.dataset.sunoPhase).toBe("idle");
    expect(panel?.dataset.sunoRunning).toBe("false");
    expect(panel?.dataset.sunoError).toBe("false");
    expect(panel?.dataset.sunoCollectionId).toBe("");
    expect(panel?.dataset.sunoEntryCount).toBe("0");
    expect(panel?.dataset.sunoSelectedEntryCount).toBe("0");
    for (const control of ["server-url", "collection-select", "fetch-data", "run", "stop"]) {
      expectControl(container, control);
    }

    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a",
            channel: "clm",
            theme: "theme-a",
            status: "ready",
            pattern_count: 2,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(expectControl(container, "server-url") as HTMLSelectElement, BASE_URL);
    });
    await act(async () => {
      expectControl(container, "fetch-data").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("2 パターンを取得しました。");
    });
    expect(panel?.dataset.sunoPhase).toBe("idle");
    expect(panel?.dataset.sunoRunning).toBe("false");
    expect(panel?.dataset.sunoError).toBe("false");
    expect(panel?.dataset.sunoCollectionId).toBe("20260601-clm-theme-a-collection");
    expect(panel?.dataset.sunoEntryCount).toBe("2");
    expect(panel?.dataset.sunoSelectedEntryCount).toBe("2");
    expect(container.querySelector('[role="status"]')?.getAttribute("data-suno-status")).toBe("ok");
    expect(container.querySelector("[data-suno-entry-list]")).not.toBeNull();
    expect(container.querySelectorAll("[data-suno-entry-index]")).toHaveLength(2);
    for (const control of ["adopt-selected-clips", "retry-playlist", "retry-download"]) {
      expectControl(container, control);
    }
  });

  it("データ取得中と取得失敗を root phase と status 属性で公開する", async () => {
    const versionResponse = deferred<Response>();
    const panel = container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]');
    expect(panel).not.toBeNull();
    fetchMock
      .mockReturnValueOnce(versionResponse.promise)
      .mockResolvedValueOnce(jsonResponse(500, { error: "server down" }));

    await act(async () => {
      setSelectValue(expectControl(container, "server-url") as HTMLSelectElement, BASE_URL);
    });
    await act(async () => {
      expectControl(container, "fetch-data").click();
    });

    await waitFor(() => {
      expect(panel?.dataset.sunoPhase).toBe("loading");
      expect(panel?.dataset.sunoRunning).toBe("false");
      expect(container.querySelector('[role="status"]')?.getAttribute("data-suno-status")).toBe("ok");
      expect(container.textContent).toContain("取得中…");
    });

    await act(async () => {
      versionResponse.resolve(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }));
    });

    await waitFor(() => {
      expect(panel?.dataset.sunoPhase).toBe("error");
      expect(panel?.dataset.sunoError).toBe("true");
      expect(container.querySelector('[role="status"]')?.getAttribute("data-suno-status")).toBe("error");
      expect(container.textContent).toContain("取得失敗: HTTP 500");
    });
  });

  it("データ取得時に manifest version で /version を先に呼び、非互換警告を表示して prompts 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: "0.2.0" }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain(`拡張を更新してください（拡張 ${MANIFEST_VERSION}`);
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/collections/20260601-clm-theme-a-collection/suno/prompts.json`,
    );
  });

  it("旧サーバーの /version 404 は警告なしで prompts 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(container.textContent).not.toContain("拡張を更新してください");
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/collections/20260601-clm-theme-a-collection/suno/prompts.json`,
    );
  });

  it("dir mode で URL 入力後にデータ取得すると collection endpoint の entries を run payload に渡す", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const runResponse = deferred<unknown>();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a",
            channel: "clm",
            theme: "theme-a",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expectRangeUiAbsent(container);

    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "run") {
        return runResponse.promise;
      }
      return defaultSendMessage(message, payload);
    });
    await act(async () => {
      buttonByText(container, "全パターンを連続実行").click();
    });

    await waitFor(() => {
      const panel = container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]');
      expect(panel?.dataset.sunoPhase).toBe("starting");
      expect(panel?.dataset.sunoRunning).toBe("true");
      expect(buttonByText(container, "停止").disabled).toBe(false);
    });

    await act(async () => {
      runResponse.resolve({ ok: true });
    });
    await waitFor(() => {
      expect(container.textContent).toContain("連続実行を開始しました。");
    });
    expect(container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]')?.dataset.sunoRunning).toBe(
      "true",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/collections/20260601-clm-theme-a-collection/suno/prompts.json`,
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | theme-a",
      range: undefined,
      collectionId: "20260601-clm-theme-a-collection",
      runMode: "serial",
      indices: undefined,
      submittedClipIds: undefined,
      submittedClipIdsAreDurationFiltered: undefined,
      playlistExpectedClipCount: undefined,
    });
  });

  it("投入方式 Queue を選択して実行すると storage に保存し run payload に queue を渡す", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a",
            channel: "clm",
            theme: "theme-a",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      radioByLabel(container, "Queue").click();
    });
    expect(presetStateMocks.writeRunModeId).toHaveBeenCalledWith("queue");

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "全パターンを連続実行").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | theme-a",
      range: undefined,
      collectionId: "20260601-clm-theme-a-collection",
      runMode: "queue",
      indices: undefined,
      submittedClipIds: undefined,
      submittedClipIdsAreDurationFiltered: undefined,
      playlistExpectedClipCount: undefined,
    });
  });

  it("ACK 済み clip ID 未観測の resume state から再開しても同じ entry を再投入しない", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "" },
      { name: "p2", style: "ambient", lyrics: "" },
    ];
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    resumeStateMocks.readResumeState.mockResolvedValue({
      collectionId: "20260601-clm-theme-a-collection",
      failedIndex: 1,
      total: 2,
      timestamp: Date.now(),
      submittedClipIds: [],
    } as never);
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a",
            channel: "clm",
            theme: "theme-a",
            status: "ready",
            pattern_count: 2,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);

    await act(async () => {
      root.render(createElement(App));
    });
    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("前回の実行が中断されました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | theme-a",
      range: { start: 1, end: 1 },
      collectionId: "20260601-clm-theme-a-collection",
      runMode: "serial",
      indices: undefined,
      submittedClipIds: [],
      submittedClipIdsAreDurationFiltered: false,
      playlistExpectedClipCount: 4,
    });
  });

  it("dir mode でチェックを外した entry を除外して 0-based indices を run payload に渡す", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "" },
      { name: "p2", style: "lofi", lyrics: "" },
      { name: "p3", style: "lofi", lyrics: "" },
    ];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a",
            channel: "clm",
            theme: "theme-a",
            status: "ready",
            pattern_count: 3,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("3 パターンを取得しました。");
    });

    const checkboxes = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    expect(checkboxes.map((checkbox) => checkbox.checked)).toEqual([true, true, true]);

    await act(async () => {
      checkboxes[1].click();
    });

    await waitFor(() => {
      expect(buttonByText(container, "選択した2件を連続実行")).toBeTruthy();
    });

    await act(async () => {
      buttonByText(container, "選択した2件を連続実行").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("連続実行を開始しました。");
    });
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | theme-a",
      range: undefined,
      collectionId: "20260601-clm-theme-a-collection",
      runMode: "serial",
      indices: [0, 2],
      submittedClipIds: undefined,
      submittedClipIdsAreDurationFiltered: undefined,
      playlistExpectedClipCount: undefined,
    });
  });

  it("content snapshot 復元だけで再実行すると snapshot の collectionId を run payload に使う", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    storageMocks.getValue.mockResolvedValue(BASE_URL);
    fetchMock.mockReset();
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [
        {
          id: "20260601-clm-other-collection",
          name: "other-collection",
          status: "ready",
          pattern_count: 1,
          downloaded_count: 0,
        },
        {
          id: "20260602-clm-snapshot-collection",
          name: "snapshot-collection",
          channel: "clm",
          theme: "snapshot",
          status: "ready",
          pattern_count: 1,
          downloaded_count: 0,
        },
      ]),
    );
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        return Promise.resolve({
          collectionId: "20260602-clm-snapshot-collection",
          entries,
          itemStates: ["idle"],
          isRunning: false,
          progress: { phase: "stopped", total: 1 },
          playlistName: "clm | snapshot",
        });
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      root.render(createElement(App));
    });
    await waitFor(() => {
      expect(container.textContent).toContain("停止しました。手動で続行できます。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "全パターンを連続実行").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | snapshot",
      range: undefined,
      collectionId: "20260602-clm-snapshot-collection",
      runMode: "serial",
      indices: undefined,
      submittedClipIds: undefined,
      submittedClipIdsAreDurationFiltered: undefined,
      playlistExpectedClipCount: undefined,
    });
  });

  it("snapshot 復元後にデータ再取得すると restored collection ではなく取得した collectionId で run する", async () => {
    const restoredEntries = [{ name: "old", style: "lofi", lyrics: "" }];
    const fetchedEntries = [{ name: "fresh", style: "ambient", lyrics: "" }];
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    fetchMock.mockReset();
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        return Promise.resolve({
          collectionId: "20260602-clm-restored-collection",
          entries: restoredEntries,
          itemStates: ["idle"],
          isRunning: false,
          progress: { phase: "stopped", total: 1 },
          playlistName: "clm | restored",
        });
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      root.render(createElement(App));
    });
    await waitFor(() => {
      expect(container.textContent).toContain("停止しました。手動で続行できます。");
    });

    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260603-clm-fresh-collection",
            name: "fresh-collection",
            channel: "clm",
            theme: "fresh",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, fetchedEntries));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "全パターンを連続実行").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries: fetchedEntries,
      playlistName: "clm | fresh",
      range: undefined,
      collectionId: "20260603-clm-fresh-collection",
      runMode: "serial",
      indices: undefined,
      submittedClipIds: undefined,
      submittedClipIdsAreDurationFiltered: undefined,
      playlistExpectedClipCount: undefined,
    });
  });

  it("dir mode で全チェックを外すと run payload を送らず実行対象選択を促す", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "" },
      { name: "p2", style: "lofi", lyrics: "" },
      { name: "p3", style: "lofi", lyrics: "" },
    ];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a",
            channel: "clm",
            theme: "theme-a",
            status: "ready",
            pattern_count: 3,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("3 パターンを取得しました。");
    });

    const checkboxes = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    expect(checkboxes.map((checkbox) => checkbox.checked)).toEqual([true, true, true]);

    for (const checkbox of checkboxes) {
      await act(async () => {
        checkbox.click();
      });
    }

    await waitFor(() => {
      const button = buttonByText(container, "実行対象を選択");
      expect(button.disabled).toBe(true);
    });

    await act(async () => {
      buttonByText(container, "実行対象を選択").click();
    });

    expect(messagingMocks.sendMessage.mock.calls.filter(([message]) => message === "run")).toHaveLength(0);
  });

  it("dir mode の channel/theme から multi-word channel の playlist 名を導出する", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-soulful-grooves-wah-groove-collection",
            name: "wah-groove",
            channel: "soulful-grooves",
            theme: "wah-groove",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "全パターンを連続実行").click();
    });

    await waitFor(() => {
      expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
        "run",
        expect.objectContaining({
          playlistName: "soulful-grooves | wah-groove",
        }),
      );
    });
  });

  it("dir mode でデータ取得後に collection を変更すると再取得まで連続実行できない", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
          {
            id: "20260602-clm-theme-b-collection",
            name: "theme-b-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, "20260602-clm-theme-b-collection");
    });

    const runButton = buttonByText(container, "全パターンを連続実行");
    expect(runButton.disabled).toBe(true);

    await act(async () => {
      runButton.click();
    });
    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("run", expect.anything());
  });

  it("clip ID が無い再開時に Suno 上の選択中 clip を採用して resume state に保存する", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const adoptionResponse = deferred<{ ok: true; clipIds: string[] }>();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return adoptionResponse.promise;
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });

    await waitFor(() => {
      const panel = container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]');
      expect(panel?.dataset.sunoPhase).toBe("adopting");
      expect(panel?.dataset.sunoRunning).toBe("true");
    });
    await act(async () => {
      adoptionResponse.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });
    expect(container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]')?.dataset.sunoPhase).toBe("idle");
    expect(container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]')?.dataset.sunoRunning).toBe(
      "false",
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("adoptSelectedClips", { expectedClipCount: 2 });
    expect(resumeStateMocks.writeResumeState).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "20260601-clm-theme-a-collection",
        failedIndex: 1,
        total: 1,
        submittedClipIds: ["clip-a", "clip-b"],
        submittedClipIdsAreDurationFiltered: false,
        playlistExpectedClipCount: 2,
      }),
    );
  });

  it("選択中 clip 採用後に Download から再開すると retryDownload payload を送る", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const downloadResponse = deferred<unknown>();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
      }
      if (message === "retryDownload") {
        return downloadResponse.promise;
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    await waitFor(() => {
      const panel = container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]');
      expect(panel?.dataset.sunoPhase).toBe("downloading");
      expect(panel?.dataset.sunoRunning).toBe("true");
    });
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryDownload", {
      collectionId: "20260601-clm-theme-a-collection",
      submittedClipIds: ["clip-a", "clip-b"],
      expectedClipCount: 2,
    });
    await act(async () => {
      downloadResponse.resolve({ ok: true });
    });
    await waitFor(() => {
      expect(container.textContent).toContain("ダウンロードを再実行しています…");
    });
  });

  it("collection に保存済み playlist URL がある場合も Download 再開 payload に含めない", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
            suno_playlist_url: "https://suno.com/playlist/saved",
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryDownload", {
      collectionId: "20260601-clm-theme-a-collection",
      submittedClipIds: ["clip-a", "clip-b"],
      expectedClipCount: 2,
    });
  });

  it("expected_file_count が entries×2 より大きい場合は手動採用と Download 再開に expected_file_count を使う", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 4,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b", "clip-c", "clip-d"] });
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 4 件を採用しました。");
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("adoptSelectedClips", { expectedClipCount: 4 });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryDownload", {
      collectionId: "20260601-clm-theme-a-collection",
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      expectedClipCount: 4,
    });
  });

  it("DL 形式 select は storage の初期値を反映し、変更時に保存する", async () => {
    await rerenderAppWithDownloadFormat("m4a");

    const select = Array.from(container.querySelectorAll("select")).find((candidate) =>
      Array.from(candidate.options).some((option) => option.value === "wav"),
    );
    if (!select) throw new Error("download format select not found");
    await waitFor(() => {
      expect(select.value).toBe("m4a");
    });

    await act(async () => {
      setSelectValue(select, "wav");
    });

    expect(downloadFormatMocks.setValue).toHaveBeenCalledWith("wav");
    expect(select.value).toBe("wav");
  });

  it("DL 形式 select は不正な storage 値を MP3 に戻す", async () => {
    await rerenderAppWithDownloadFormat("flac");

    const select = Array.from(container.querySelectorAll("select")).find((candidate) =>
      Array.from(candidate.options).some((option) => option.value === "wav"),
    );
    if (!select) throw new Error("download format select not found");
    await waitFor(() => {
      expect(select.value).toBe("mp3");
    });
  });

  it("App 配線で done entry の自動 OFF と手動再チェック保持を反映する", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "" },
      { name: "p2", style: "jazz", lyrics: "" },
      { name: "p3", style: "ambient", lyrics: "" },
    ];
    const snapshot = {
      entries,
      itemStates: entries.map(() => "idle"),
      isRunning: true,
      progress: { phase: PHASE.INJECTING, total: entries.length },
      collectionId: null,
    };
    let progressHandler: ((event: { data: ProgressPayload }) => void) | undefined;

    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        return Promise.resolve(snapshot);
      }
      return defaultSendMessage(message, payload);
    });
    messagingMocks.onMessage.mockImplementation((message?: unknown, handler?: unknown) => {
      if (message === "progress" && typeof handler === "function") {
        progressHandler = handler as (event: { data: ProgressPayload }) => void;
      }
      return () => undefined;
    });

    await act(async () => {
      root.unmount();
    });
    container.innerHTML = "";
    root = createRoot(container);
    await act(async () => {
      root.render(createElement(App));
    });

    const checkboxStates = (): boolean[] =>
      Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')).map(
        (checkbox) => checkbox.checked,
      );

    await waitFor(() => {
      expect(checkboxStates()).toEqual([true, true, true]);
    });

    await act(async () => {
      progressHandler?.({ data: { phase: PHASE.DONE, index: 1, total: entries.length } });
    });
    await waitFor(() => {
      expect(checkboxStates()).toEqual([true, false, true]);
    });
    expect(
      Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))[1]?.closest("li")?.className,
    ).toContain("line-through");

    await act(async () => {
      Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))[1]?.click();
    });
    await waitFor(() => {
      expect(checkboxStates()).toEqual([true, true, true]);
    });

    await act(async () => {
      progressHandler?.({ data: { phase: PHASE.DONE, index: 0, total: entries.length } });
    });
    await waitFor(() => {
      expect(checkboxStates()).toEqual([false, true, true]);
    });
  });

  it("選択中 clip 採用後に Playlist から再開すると retryPlaylist payload を送る", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const playlistResponse = deferred<unknown>();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
      }
      if (message === "retryPlaylist") {
        return playlistResponse.promise;
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    await waitFor(() => {
      const panel = container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]');
      expect(panel?.dataset.sunoPhase).toBe("adding-to-playlist");
      expect(panel?.dataset.sunoRunning).toBe("true");
    });
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryPlaylist", {
      collectionId: "20260601-clm-theme-a-collection",
      playlistName: "clm | theme-a",
      submittedClipIds: ["clip-a", "clip-b"],
      expectedClipCount: 2,
      durationFilter: undefined,
      submittedClipIdsAreDurationFiltered: false,
      shouldDownload: true,
    });
    await act(async () => {
      playlistResponse.resolve({ ok: true });
    });
    await waitFor(() => {
      expect(container.textContent).toContain("playlist 追加とダウンロードを再実行しています…");
    });
  });

  it("persisted resume が entries 未取得でも Playlist から再開すると Download all 対象として送る", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    resumeStateMocks.readResumeState.mockResolvedValue({
      collectionId: "20260601-clm-theme-a-collection",
      failedIndex: 1,
      total: 1,
      timestamp: Date.now(),
      submittedClipIds: ["clip-a", "clip-b"],
      durationFilter: { min_sec: 75, max_sec: 180 },
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    } as never);
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(500, {}));
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);

    await act(async () => {
      root.render(createElement(App));
    });
    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).not.toContain("全 entry 投入済みです。playlist 追加から再開しますか？");
      expect(container.textContent).toContain("Playlist: clm | theme-a");
      expect(container.textContent).toContain("Playlist から再開");
    });
    expectControl(container, "retry-playlist");

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryPlaylist", {
      collectionId: "20260601-clm-theme-a-collection",
      playlistName: "clm | theme-a",
      submittedClipIds: ["clip-a", "clip-b"],
      expectedClipCount: 2,
      durationFilter: { min_sec: 75, max_sec: 180 },
      submittedClipIdsAreDurationFiltered: true,
      shouldDownload: true,
    });
  });

  it("persisted resume が entries 未取得の途中再開ならバナーを残して run を送らない", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    resumeStateMocks.readResumeState.mockResolvedValue({
      collectionId: "20260601-clm-theme-a-collection",
      failedIndex: 0,
      total: 1,
      timestamp: Date.now(),
      submittedClipIds: [],
    } as never);
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(500, {}));
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);

    await act(async () => {
      root.render(createElement(App));
    });
    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("前回の実行が中断されました。");
      expect(container.textContent).toContain("取得失敗:");
    });
    expectControl(container, "resume");
    expectControl(container, "dismiss-resume");

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "再開").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("run", expect.anything());
    expect(container.textContent).toContain("再開に必要なパターンが未取得です。");
    expect(container.textContent).toContain("前回の実行が中断されました。");
  });

  it("clip ID が無い状態で Playlist から再開しても retryPlaylist を送らずエラー表示する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("retryPlaylist", expect.anything());
    expect(container.textContent).toContain("playlist 再開に必要な clip ID がありません。");
  });

  it("Playlist から再開の送信に失敗したらエラーを表示して再試行可能にする", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
      }
      if (message === "retryPlaylist") {
        return Promise.reject(new Error("relay failed"));
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryPlaylist", expect.anything());
    await waitFor(() => {
      expect(container.textContent).toContain("開始失敗: relay failed");
      expect(buttonByText(container, "Playlist から再開").disabled).toBe(false);
    });
  });

  it("clip ID が無い状態で Download から再開しても retryDownload を送らずエラー表示する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("retryDownload", expect.anything());
    expect(container.textContent).toContain("ダウンロード再開に必要な clip ID がありません。");
  });

  it("dir mode でデータ取得後に URL を変更すると再取得まで連続実行できない", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, `${BASE_URL}/changed`);
    });

    const runButton = buttonByText(container, "全パターンを連続実行");
    expect(runButton.disabled).toBe(true);

    await act(async () => {
      runButton.click();
    });
    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("run", expect.anything());
  });

  it("dir mode の collection 一覧に実行可能候補が無い場合は legacy endpoint へフォールバックしない", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(jsonResponse(200, []));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("取得失敗: prompts を取得できる collection がありません。");
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
  });

  it("/collections が HTTP 404 の場合は legacy endpoint へフォールバックせずエラー表示する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(jsonResponse(404, {}));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("取得失敗: HTTP 404");
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
  });

  it("popup 起動時の collection 一覧同期は status ベースの新スキーマで動作する (#1216)", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    fetchMock.mockReset();
    storageMocks.getValue.mockResolvedValue(BASE_URL);
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [
        {
          id: "20260601-clm-theme-a-collection",
          name: "theme-a-collection",
          status: "ready",
          pattern_count: 1,
          downloaded_count: 0,
        },
      ]),
    );

    await act(async () => {
      root.render(createElement(App));
    });

    await waitFor(() => {
      expect(container.textContent).toContain("コレクション");
    });
    expect(container.textContent).not.toContain("コレクション一覧取得失敗");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/collections`);
  });

  it("popup 起動時の collection 一覧同期は downloaded collection を完了件数付きで表示する", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    fetchMock.mockReset();
    storageMocks.getValue.mockResolvedValue(BASE_URL);
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [
        {
          id: "20260601-clm-done-collection",
          name: "done-collection",
          status: "downloaded",
          pattern_count: 2,
          downloaded_count: 4,
        },
        {
          id: "20260601-clm-ready-collection",
          name: "ready-collection",
          status: "ready",
          pattern_count: 1,
          downloaded_count: 0,
        },
      ]),
    );

    await act(async () => {
      root.render(createElement(App));
    });

    await waitFor(() => {
      expect(container.textContent).toContain("ready-collection");
    });
    expect(container.textContent).toContain("done-collection（完了 4/4）");
    const doneOption = Array.from(container.querySelectorAll("option")).find((option) =>
      option.textContent?.includes("done-collection"),
    );
    expect(doneOption?.disabled).toBe(false);
  });

  it("CORS なし 404 (TypeError) で /collections が reject されたら legacy endpoint へ fallback しない", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("取得失敗: Failed to fetch");
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
  });
});
