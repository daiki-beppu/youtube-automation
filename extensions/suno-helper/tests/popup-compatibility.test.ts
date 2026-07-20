// @vitest-environment jsdom

import { act } from "react";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PHASE, type ProgressPayload } from "../../shared/constants";
import { App } from "../components/App";
import { EXTENSION_RELOAD_REQUIRED_MESSAGE } from "../components/runner-errors";

const BASE_URL = "http://localhost:7873";
const FALLBACK_URL = "http://localhost:7877";
const MANIFEST_VERSION = "0.1.9";

const messagingMocks = vi.hoisted(() => {
  const mocks = {
    progressHandler: undefined as
      | ((message: { data: ProgressPayload }) => void)
      | undefined,
    onMessage: vi.fn(
      (type: string, handler: (message: { data: ProgressPayload }) => void) => {
        if (type === "progress") {
          mocks.progressHandler = handler;
        }
        return () => undefined;
      }
    ),
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

const completionSoundMocks = vi.hoisted(() => ({
  getValue: vi.fn(async () => ({ enabled: true, preset: "chime" })),
  setValue: vi.fn(async () => undefined),
  play: vi.fn(async () => undefined),
}));

const serverSourcesMocks = vi.hoisted(() => ({
  migrateServerSourcesStorage: vi.fn(async () => undefined),
}));

const legacySourceState = vi.hoisted(() => ({ present: true }));

const resumeStateMocks = vi.hoisted(() => ({
  readResumeState: vi.fn(async () => null),
  writeResumeState: vi.fn(async () => undefined),
  clearResumeStateForCollection: vi.fn(async () => undefined),
}));

const collectionQueueMocks = vi.hoisted(() => ({
  readCollectionQueue: vi.fn(async () => null),
  writeCollectionQueue: vi.fn(async () => undefined),
  settleStoredCollectionQueueRun: vi.fn(async () => null),
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
  completionSoundSettingsItem: completionSoundMocks,
  readCompletionSoundSettings: vi.fn(() => completionSoundMocks.getValue()),
  migrateServerSourcesStorage: serverSourcesMocks.migrateServerSourcesStorage,
}));

vi.mock("../lib/completion-sound", async () => {
  const actual = await vi.importActual<
    typeof import("../lib/completion-sound")
  >("../lib/completion-sound");
  return { ...actual, playCompletionSound: completionSoundMocks.play };
});

vi.mock("../lib/messaging", () => messagingMocks);

async function readJson(url: string): Promise<unknown> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

function defaultSendMessage(
  message: string,
  payload?: Record<string, string>
): Promise<unknown> {
  if (message === "queryProgress") {
    throw new Error("runner unavailable");
  }
  if (message === "fetchCompatibilityWarning") {
    return (async () => {
      const resp = await fetch(`${payload?.baseUrl}/version`);
      if (!resp.ok) {
        return "";
      }
      const data = (await resp.json()) as {
        version: string;
        min_extension_version: string;
      };
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
      base_url: payload?.baseUrl ?? BASE_URL,
      label: "localhost",
    });
  }
  if (message === "discoverServerSources") {
    return Promise.resolve([
      {
        id: "youtube-automation-localhost-7873",
        label: "YouTube Automation (default)",
        url: "http://youtube-automation.localhost:7873",
      },
      { id: "abyss-mi", label: "ABYSS MI", url: BASE_URL },
      {
        id: "localhost-7877",
        label: "localhost fallback 7877",
        url: FALLBACK_URL,
      },
      {
        id: "localhost-7873-changed",
        label: "localhost changed",
        url: `${BASE_URL}/changed`,
      },
    ]);
  }
  if (message === "fetchCollections") {
    return readJson(`${payload?.baseUrl}/collections`);
  }
  if (message === "fetchCollectionPrompts") {
    return readJson(
      `${payload?.baseUrl}/collections/${encodeURIComponent(payload?.collectionId ?? "")}/suno/prompts.json`
    );
  }
  if (message === "fetchCollectionPromptResponse") {
    return readJson(
      `${payload?.baseUrl}/collections/${encodeURIComponent(payload?.collectionId ?? "")}/suno/prompts.json`
    );
  }
  return Promise.resolve({ ok: true });
}

vi.mock("../lib/preset-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/preset-state")>(
    "../lib/preset-state"
  );
  return {
    ...actual,
    readRunModeId: presetStateMocks.readRunModeId,
    writeRunModeId: presetStateMocks.writeRunModeId,
  };
});

vi.mock("../lib/resume-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/resume-state")>(
    "../lib/resume-state"
  );
  return {
    ...actual,
    readResumeState: resumeStateMocks.readResumeState,
    writeResumeState: resumeStateMocks.writeResumeState,
    clearResumeStateForCollection:
      resumeStateMocks.clearResumeStateForCollection,
  };
});

vi.mock("../lib/collection-queue-state", async () => {
  const actual = await vi.importActual<
    typeof import("../lib/collection-queue-state")
  >("../lib/collection-queue-state");
  return {
    ...actual,
    readCollectionQueue: collectionQueueMocks.readCollectionQueue,
    writeCollectionQueue: collectionQueueMocks.writeCollectionQueue,
    settleStoredCollectionQueueRun:
      collectionQueueMocks.settleStoredCollectionQueueRun,
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
  const setter = Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype,
    "value"
  )?.set;
  if (!setter) {
    throw new Error("HTMLSelectElement.value setter is unavailable");
  }
  setter.call(select, value);
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

async function setDownloadFormatValue(
  container: HTMLElement,
  value: "mp3" | "m4a" | "wav"
): Promise<void> {
  const trigger = expectControl(
    container,
    "download-format"
  ) as HTMLButtonElement;
  await act(async () => {
    trigger.focus();
    trigger.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })
    );
  });
  const item = Array.from(
    container.querySelectorAll<HTMLElement>('[data-slot="select-item"]')
  ).find((candidate) => candidate.textContent === value.toUpperCase());
  if (!item) throw new Error(`download format item not found: ${value}`);
  await act(async () => {
    item.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
    );
  });
}

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.includes(text)
  );
  if (!button) {
    throw new Error(`button not found: ${text}`);
  }
  return button;
}

function radioByLabel(container: HTMLElement, text: string): HTMLElement {
  const label = Array.from(container.querySelectorAll("label")).find(
    (candidate) => candidate.textContent?.includes(text)
  );
  const input = label?.querySelector<HTMLElement>('[role="radio"]');
  if (!input) {
    throw new Error(`radio not found: ${text}`);
  }
  return input;
}

function checkboxByLabel(container: HTMLElement, text: string): HTMLElement {
  const label = Array.from(container.querySelectorAll("label")).find(
    (candidate) => candidate.textContent?.includes(text)
  );
  const input = label?.querySelector<HTMLElement>('[data-slot="checkbox"]');
  if (!input) {
    throw new Error(`checkbox not found: ${text}`);
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
  const element = container.querySelector<HTMLElement>(
    `[data-suno-control="${control}"]`
  );
  expect(element).not.toBeNull();
  return element!;
}

function expectShadcnControl(
  element: HTMLElement,
  variant:
    | "default"
    | "destructive"
    | "info"
    | "outline"
    | "success"
    | "warning",
  slot = "button"
): void {
  expect(element.dataset.slot).toBe(slot);
  expect(element.dataset.variant).toBe(variant);
  expect(element.dataset.size).toBe("sm");
}

function alertByText(container: HTMLElement, text: string): HTMLElement {
  const alert = Array.from(
    container.querySelectorAll<HTMLElement>('[data-slot="alert"]')
  ).find((candidate) => candidate.textContent?.includes(text));
  if (!alert) {
    throw new Error(`alert not found: ${text}`);
  }
  return alert;
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
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    fetchMock = vi.fn();
    storageMocks.getValue.mockResolvedValue("");
    storageMocks.setValue.mockResolvedValue(undefined);
    downloadFormatMocks.getValue.mockResolvedValue("mp3");
    downloadFormatMocks.setValue.mockResolvedValue(undefined);
    completionSoundMocks.getValue.mockResolvedValue({
      enabled: true,
      preset: "chime",
    });
    completionSoundMocks.setValue.mockResolvedValue(undefined);
    completionSoundMocks.play.mockResolvedValue(undefined);
    presetStateMocks.readRunModeId.mockResolvedValue("serial");
    presetStateMocks.writeRunModeId.mockResolvedValue(undefined);
    collectionQueueMocks.readCollectionQueue.mockResolvedValue(null);
    collectionQueueMocks.writeCollectionQueue.mockResolvedValue(undefined);
    serverSourcesMocks.migrateServerSourcesStorage.mockImplementation(
      async () => {
        legacySourceState.present = false;
      }
    );
    legacySourceState.present = true;
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    messagingMocks.progressHandler = undefined;
    messagingMocks.onMessage.mockImplementation(
      (type: string, handler: (message: { data: ProgressPayload }) => void) => {
        if (type === "progress") {
          messagingMocks.progressHandler = handler;
        }
        return () => undefined;
      }
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

  async function rerenderApp(): Promise<void> {
    await act(async () => {
      root.unmount();
    });
    container.innerHTML = "";
    root = createRoot(container);
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
    resumeStateMocks.clearResumeStateForCollection.mockResolvedValue(undefined);
    presetStateMocks.readRunModeId.mockResolvedValue("serial");
    presetStateMocks.writeRunModeId.mockResolvedValue(undefined);
    serverSourcesMocks.migrateServerSourcesStorage.mockResolvedValue(undefined);
    completionSoundMocks.getValue.mockResolvedValue({
      enabled: true,
      preset: "chime",
    });
    completionSoundMocks.setValue.mockResolvedValue(undefined);
    completionSoundMocks.play.mockResolvedValue(undefined);
  });

  it("ローカル配信元 option は URL を表示せず、URL value はデータ取得先として維持する", async () => {
    const select = expectControl(container, "server-url") as HTMLSelectElement;

    await waitFor(() => {
      expect(select.options).toHaveLength(4);
    });

    expect(
      Array.from(select.options, (option) => ({
        text: option.text,
        value: option.value,
      }))
    ).toEqual([
      {
        text: "YouTube Automation (default) | suno-helper",
        value: "http://youtube-automation.localhost:7873",
      },
      { text: "ABYSS MI | suno-helper", value: BASE_URL },
      { text: "localhost fallback 7877 | suno-helper", value: FALLBACK_URL },
      { text: "localhost changed | suno-helper", value: `${BASE_URL}/changed` },
    ]);
    expect(select.textContent).not.toContain("http://");
  });

  it("popup に投入方式 selector を表示し、Fast / Balanced / Safe の速度プリセットは表示しない", () => {
    expect(container.textContent).toContain("投入方式");
    expect(container.querySelector('[data-slot="radio-group"]')).not.toBeNull();
    expect(container.textContent).not.toContain("Fast");
    expect(container.textContent).not.toContain("Balanced");
    expect(container.textContent).not.toContain("Safe");
    expect(container.querySelector('input[name="speed-preset"]')).toBeNull();
  });

  it("可視 control を shared shadcn primitive で描画し、value・aria・data 属性を維持する", () => {
    const collectionSelect = expectControl(container, "collection-select");
    expect(collectionSelect).toBeInstanceOf(HTMLSelectElement);
    expect(collectionSelect.classList).toContain("sr-only");
    expect(collectionSelect.getAttribute("aria-hidden")).toBe("true");
    expect(collectionSelect.getAttribute("role")).not.toBe("button");

    const serverTrigger = expectControl(container, "server-source-trigger");
    expectShadcnControl(serverTrigger, "outline");
    expect(serverTrigger.getAttribute("aria-haspopup")).toBe("listbox");
    const downloadFormat = expectControl(
      container,
      "download-format"
    ) as HTMLButtonElement;
    expect(downloadFormat.dataset.slot).toBe("select-trigger");
    expect(downloadFormat.getAttribute("role")).toBe("combobox");
    expect(downloadFormat.getAttribute("aria-labelledby")).toContain(
      "download-format-label"
    );
    expect(downloadFormat.textContent).toContain("MP3");
    expect(
      expectControl(container, "regenerate-duration-outliers").dataset.slot
    ).toBe("checkbox");
    expect(
      expectControl(container, "completion-sound-enabled").dataset.slot
    ).toBe("checkbox");

    const serialMode = radioByLabel(container, "安全モード");
    const queueMode = radioByLabel(container, "高速モード");
    expect(serialMode.dataset.slot).toBe("radio-group-item");
    expect(queueMode.dataset.slot).toBe("radio-group-item");
    expect((serialMode.nextElementSibling as HTMLInputElement).value).toBe(
      "serial"
    );
    expect(serialMode.hasAttribute("data-checked")).toBe(true);
    expect((queueMode.nextElementSibling as HTMLInputElement).value).toBe(
      "queue"
    );
    expect(queueMode.hasAttribute("data-checked")).toBe(false);
    for (const radio of [serialMode, queueMode]) {
      expect(Array.from(radio.classList)).toEqual(
        expect.arrayContaining([
          "data-checked:border-info-foreground",
          "data-checked:text-info-foreground",
        ])
      );
    }
    expectShadcnControl(
      serialMode.closest<HTMLElement>('[data-slot="field-label"]')!,
      "info",
      "field-label"
    );
    const selectedModeCard = serialMode.closest<HTMLElement>(
      '[data-slot="field-label"]'
    )!;
    expect(Array.from(selectedModeCard.classList)).toEqual(
      expect.arrayContaining([
        "border-info-border",
        "bg-info-background/40",
        "dark:bg-info-background/25",
      ])
    );
    expect(
      selectedModeCard.querySelector('[data-suno-slot="run-mode-description"]')
        ?.classList
    ).toContain("text-info-foreground");
    expectShadcnControl(
      queueMode.closest<HTMLElement>('[data-slot="field-label"]')!,
      "outline",
      "field-label"
    );
    const unselectedModeCard = queueMode.closest<HTMLElement>(
      '[data-slot="field-label"]'
    )!;
    expect(unselectedModeCard.classList).not.toContain("bg-info-background/40");
    expect(
      unselectedModeCard.querySelector(
        '[data-suno-slot="run-mode-description"]'
      )?.classList
    ).toContain("text-muted-foreground");

    expectShadcnControl(expectControl(container, "run"), "info");
    expectShadcnControl(expectControl(container, "stop"), "destructive");
  });

  it("progress handler が DONE + duration-check log を受けると live status を更新する", async () => {
    expect(messagingMocks.progressHandler).toBeDefined();
    const panel = container.querySelector<HTMLElement>(
      '[data-suno-helper="control-panel"]'
    );
    expect(panel).not.toBeNull();
    expect(panel?.dataset.sunoPhase).toBe("idle");

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.DONE, index: 1, total: 3 },
      });
    });
    expect(panel?.dataset.sunoPhase).toBe(PHASE.DONE);
    expect(container.textContent).not.toContain('"p2": 259s ✓');

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: {
          phase: PHASE.DONE,
          index: 1,
          total: 3,
          log: {
            kind: "duration-check",
            entryName: "p2",
            durationSec: 259,
            ok: true,
            maxSec: 300,
          },
        },
      });
    });

    expect(container.textContent).toContain('"p2": 259s ✓');
    const status = container.querySelector<HTMLElement>('[role="status"]');
    expect(status?.dataset.slot).toBe("alert");
    expect(status?.dataset.variant).toBe("info");
    expect(status?.getAttribute("aria-live")).toBe("polite");
    expect(status?.getAttribute("data-suno-status")).toBe("ok");
  });

  it("FINISHED/ERROR だけを区別して鳴らし、STOPPED と同一終端の重複通知は鳴らさない", async () => {
    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 1 },
      });
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 1 },
      });
    });
    expect(completionSoundMocks.play).toHaveBeenCalledTimes(1);
    expect(completionSoundMocks.play).toHaveBeenLastCalledWith(
      "chime",
      "success"
    );
    expect(
      container.querySelector<HTMLElement>('[role="status"]')?.dataset.variant
    ).toBe("success");

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.INJECTING, index: 0, total: 1 },
      });
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.ERROR, index: 0, total: 1, message: "failed" },
      });
    });
    expect(
      container.querySelector<HTMLElement>('[role="status"]')?.dataset.variant
    ).toBe("destructive");

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.STOPPED, total: 1 },
      });
    });
    expect(completionSoundMocks.play).toHaveBeenCalledTimes(2);
    expect(completionSoundMocks.play).toHaveBeenLastCalledWith(
      "chime",
      "error"
    );
  });

  it("設定読込前の終端通知を保留し、保存済み OFF なら鳴らさない", async () => {
    const settings = deferred<{ enabled: boolean; preset: "bell" }>();
    completionSoundMocks.getValue.mockReturnValueOnce(settings.promise);
    await rerenderApp();
    const enabled = expectControl(container, "completion-sound-enabled");
    expect(enabled.getAttribute("data-disabled")).not.toBeNull();
    await act(async () => enabled.click());
    expect(completionSoundMocks.setValue).not.toHaveBeenCalled();

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 1 },
      });
    });
    expect(completionSoundMocks.play).not.toHaveBeenCalled();

    await act(async () => {
      settings.resolve({ enabled: false, preset: "bell" });
      await settings.promise;
    });
    expect(completionSoundMocks.play).not.toHaveBeenCalled();
    expect(enabled.getAttribute("data-disabled")).toBeNull();
  });

  it("設定読込前の終端通知を保留し、初期 ON 設定の確定後に一度だけ鳴らす", async () => {
    const settings = deferred<{ enabled: boolean; preset: "chime" }>();
    completionSoundMocks.getValue.mockReturnValueOnce(settings.promise);
    await rerenderApp();

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 1 },
      });
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 1 },
      });
    });
    expect(completionSoundMocks.play).not.toHaveBeenCalled();

    await act(async () => {
      settings.resolve({ enabled: true, preset: "chime" });
      await settings.promise;
    });
    expect(completionSoundMocks.play).toHaveBeenCalledOnce();
    expect(completionSoundMocks.play).toHaveBeenCalledWith("chime", "success");
  });

  it("shadcn 完了音 UI で OFF・preset 保存と試聴を行う", async () => {
    const enabled = expectControl(container, "completion-sound-enabled");
    expect(enabled.dataset.slot).toBe("checkbox");
    await act(async () => enabled.click());
    expect(completionSoundMocks.setValue).toHaveBeenCalledWith({
      enabled: false,
      preset: "chime",
    });

    const soft = container.querySelector<HTMLButtonElement>(
      '[data-suno-control="completion-sound-preset"][data-suno-preset="soft"]'
    )!;
    expect(soft.dataset.slot).toBe("button");
    await act(async () => soft.click());
    expect(completionSoundMocks.setValue).toHaveBeenLastCalledWith({
      enabled: false,
      preset: "soft",
    });

    await act(async () => {
      (
        expectControl(
          container,
          "completion-sound-preview"
        ) as HTMLButtonElement
      ).click();
    });
    expect(completionSoundMocks.play).toHaveBeenCalledWith("soft", "success");

    completionSoundMocks.play.mockClear();
    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.INJECTING, index: 0, total: 1 },
      });
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 1 },
      });
    });
    expect(completionSoundMocks.play).not.toHaveBeenCalled();
  });

  it("agent 操作用の root 状態属性と主要 control selector を実 DOM に公開する", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "" },
      { name: "p2", style: "ambient", lyrics: "" },
    ];
    const panel = container.querySelector<HTMLElement>(
      '[data-suno-helper="control-panel"]'
    );
    expect(panel).not.toBeNull();
    expect(panel?.dataset.sunoPhase).toBe("idle");
    expect(panel?.dataset.sunoRunning).toBe("false");
    expect(panel?.dataset.sunoError).toBe("false");
    expect(panel?.dataset.sunoCollectionId).toBe("");
    expect(panel?.dataset.sunoEntryCount).toBe("0");
    expect(panel?.dataset.sunoSelectedEntryCount).toBe("0");
    for (const control of ["server-url", "collection-select", "run", "stop"]) {
      expectControl(container, control);
    }
    expect(
      container.querySelector('[data-suno-control="fetch-data"]')
    ).toBeNull();
    expect(container.textContent).not.toContain("データ取得");

    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(
        expectControl(container, "server-url") as HTMLSelectElement,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("2 パターンを取得しました。");
    });
    expect(panel?.dataset.sunoPhase).toBe("idle");
    expect(panel?.dataset.sunoRunning).toBe("false");
    expect(panel?.dataset.sunoError).toBe("false");
    expect(panel?.dataset.sunoCollectionId).toBe(
      "20260601-clm-theme-a-collection"
    );
    expect(panel?.dataset.sunoEntryCount).toBe("2");
    expect(panel?.dataset.sunoSelectedEntryCount).toBe("2");
    expect(
      container
        .querySelector('[role="status"]')
        ?.getAttribute("data-suno-status")
    ).toBe("ok");
    expect(container.querySelector("[data-suno-entry-list]")).not.toBeNull();
    expect(container.querySelectorAll("[data-suno-entry-index]")).toHaveLength(
      2
    );
    for (const control of [
      "adopt-selected-clips",
      "retry-playlist",
      "retry-download",
    ]) {
      expectControl(container, control);
    }
    expectShadcnControl(
      expectControl(container, "adopt-selected-clips"),
      "outline"
    );
    expectShadcnControl(expectControl(container, "retry-playlist"), "warning");
    expectShadcnControl(expectControl(container, "retry-download"), "success");
    expect(expectControl(container, "collection-checkbox").dataset.slot).toBe(
      "checkbox"
    );
  });

  it("配信元選択時の自動取得中と取得失敗を root phase と status 属性で公開し、select を操作可能に保つ", async () => {
    const versionResponse = deferred<Response>();
    const panel = container.querySelector<HTMLElement>(
      '[data-suno-helper="control-panel"]'
    );
    expect(panel).not.toBeNull();
    fetchMock
      .mockReturnValueOnce(versionResponse.promise)
      .mockResolvedValueOnce(jsonResponse(500, { error: "server down" }));

    await act(async () => {
      setSelectValue(
        expectControl(container, "server-url") as HTMLSelectElement,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(panel?.dataset.sunoPhase).toBe("loading");
      expect(panel?.dataset.sunoRunning).toBe("false");
      expect(
        container
          .querySelector('[role="status"]')
          ?.getAttribute("data-suno-status")
      ).toBe("ok");
      expect(container.textContent).toContain("取得中…");
    });

    await act(async () => {
      versionResponse.resolve(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      );
    });

    await waitFor(() => {
      expect(panel?.dataset.sunoPhase).toBe("error");
      expect(panel?.dataset.sunoError).toBe("true");
      expect(
        container
          .querySelector('[role="status"]')
          ?.getAttribute("data-suno-status")
      ).toBe("error");
      expect(container.textContent).toContain("取得失敗: HTTP 500");
      expect(
        expectControl(container, "server-url").getAttribute("disabled")
      ).toBeNull();
      expect(
        expectControl(container, "collection-select").getAttribute("disabled")
      ).toBeNull();
    });
    const errorStatus =
      container.querySelector<HTMLElement>('[role="status"]')!;
    expect(errorStatus.dataset.slot).toBe("alert");
    expect(errorStatus.dataset.variant).toBe("destructive");
    expect(errorStatus.getAttribute("aria-live")).toBe("polite");
  });

  it("配信元選択時に manifest version で /version を先に呼び、非互換警告を表示して prompts 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, { version: "5.5.7", min_extension_version: "0.2.0" })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }])
      );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain(
        `拡張を更新してください（拡張 ${MANIFEST_VERSION}`
      );
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    const warning = alertByText(container, "拡張を更新してください");
    expect(warning.dataset.variant).toBe("warning");
    expect(warning.getAttribute("role")).toBe("alert");
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/collections/20260601-clm-theme-a-collection/suno/prompts.json`
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
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }])
      );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(container.textContent).not.toContain("拡張を更新してください");
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/collections/20260601-clm-theme-a-collection/suno/prompts.json`
    );
  });

  it("fetchServerInfo 非対応の旧サーバーでも選択 URL のまま自動取得を継続する", async () => {
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "fetchServerInfo") {
          return Promise.reject(new Error("HTTP 404"));
        }
        return defaultSendMessage(message, payload);
      }
    );
    fetchMock
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-legacy-collection",
            name: "legacy-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "legacy", style: "lofi", lyrics: "" }])
      );

    await act(async () => {
      setSelectValue(
        expectControl(container, "server-url") as HTMLSelectElement,
        FALLBACK_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(storageMocks.setValue).toHaveBeenLastCalledWith(FALLBACK_URL);
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "fetchCollections",
      { baseUrl: FALLBACK_URL }
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "fetchCollectionPromptResponse",
      {
        baseUrl: FALLBACK_URL,
        collectionId: "20260601-clm-legacy-collection",
      }
    );
  });

  it("dir mode で配信元を選択すると collection endpoint の entries を run payload に渡す", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const runResponse = deferred<unknown>();
    const outlierOption = checkboxByLabel(container, "異常値の曲を再生成する");
    expect(outlierOption.hasAttribute("data-checked")).toBe(true);
    expect(outlierOption.hasAttribute("data-disabled")).toBe(true);
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(outlierOption.hasAttribute("data-disabled")).toBe(false);
    await act(async () => {
      outlierOption.click();
    });
    expect(outlierOption.hasAttribute("data-checked")).toBe(false);
    expect(container.textContent).toContain(
      "duration guard NG も Playlist / Download 候補に残ります"
    );
    expectRangeUiAbsent(container);

    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "run") {
          return runResponse.promise;
        }
        return defaultSendMessage(message, payload);
      }
    );
    await act(async () => {
      buttonByText(container, "全パターンを連続実行").click();
    });

    await waitFor(() => {
      const panel = container.querySelector<HTMLElement>(
        '[data-suno-helper="control-panel"]'
      );
      expect(panel?.dataset.sunoPhase).toBe("starting");
      expect(panel?.dataset.sunoRunning).toBe("true");
      expect(buttonByText(container, "停止").disabled).toBe(false);
      expect(outlierOption.hasAttribute("data-disabled")).toBe(true);
    });

    await act(async () => {
      runResponse.resolve({ ok: true });
    });
    await waitFor(() => {
      expect(container.textContent).toContain("連続実行を開始しました。");
    });
    expect(
      container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]')
        ?.dataset.sunoRunning
    ).toBe("true");
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/collections/20260601-clm-theme-a-collection/suno/prompts.json`
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | theme-a",
      range: undefined,
      collectionId: "20260601-clm-theme-a-collection",
      runMode: "serial",
      regenerateDurationOutliers: false,
      indices: undefined,
      submittedClipIds: undefined,
      submittedClipIdsAreDurationFiltered: undefined,
      playlistExpectedClipCount: undefined,
      durationOutlierWarnings: undefined,
    });
  });

  it("投入方式 高速モードを選択して実行すると storage に保存し run payload に queue を渡す", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      const serialMode = radioByLabel(container, "安全モード");
      serialMode.focus();
      serialMode.dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: "ArrowRight" })
      );
    });
    expect(
      radioByLabel(container, "高速モード").hasAttribute("data-checked")
    ).toBe(true);
    await act(async () => {
      radioByLabel(container, "安全モード").click();
      radioByLabel(container, "高速モード").click();
    });
    expect(presetStateMocks.writeRunModeId).toHaveBeenCalledWith("queue");
    expect(
      radioByLabel(container, "安全モード").hasAttribute("data-checked")
    ).toBe(false);
    expect(
      radioByLabel(container, "高速モード").hasAttribute("data-checked")
    ).toBe(true);
    expectShadcnControl(
      radioByLabel(container, "安全モード").closest<HTMLElement>(
        '[data-slot="field-label"]'
      )!,
      "outline",
      "field-label"
    );
    expectShadcnControl(
      radioByLabel(container, "高速モード").closest<HTMLElement>(
        '[data-slot="field-label"]'
      )!,
      "info",
      "field-label"
    );
    expect(
      radioByLabel(container, "高速モード").closest<HTMLElement>(
        '[data-slot="field-label"]'
      )?.classList
    ).toContain("bg-info-background/40");
    expect(
      radioByLabel(container, "安全モード").closest<HTMLElement>(
        '[data-slot="field-label"]'
      )?.classList
    ).not.toContain("bg-info-background/40");

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
      regenerateDurationOutliers: true,
      indices: undefined,
      submittedClipIds: undefined,
      submittedClipIdsAreDurationFiltered: undefined,
      playlistExpectedClipCount: undefined,
      durationOutlierWarnings: undefined,
    });
  });

  it("queue の互換性 preflight が失敗すると current collection を failed settlement する", async () => {
    const queue = {
      version: 1 as const,
      queueId: "queue-preflight",
      baseUrl: BASE_URL,
      items: [
        {
          collectionId: "20260601-clm-theme-a-collection",
          status: "pending" as const,
        },
      ],
      currentIndex: 0,
      status: "running" as const,
      runMode: "serial" as const,
      regenerateDurationOutliers: true,
      createdAt: 100,
      updatedAt: 100,
    };
    const completed = {
      ...queue,
      items: [{ ...queue.items[0], status: "failed" as const }],
      currentIndex: 1,
      status: "completed" as const,
      updatedAt: 200,
    };
    collectionQueueMocks.readCollectionQueue.mockResolvedValue(queue as never);
    collectionQueueMocks.settleStoredCollectionQueueRun.mockResolvedValue({
      state: completed,
      requiresPageReload: false,
    } as never);
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "fetchCompatibilityWarning") {
          return Promise.reject(new Error("version endpoint unavailable"));
        }
        return defaultSendMessage(message, payload);
      }
    );

    await rerenderApp();

    await waitFor(() => {
      expect(
        collectionQueueMocks.settleStoredCollectionQueueRun
      ).toHaveBeenCalledWith("queue-preflight", {
        collectionId: "20260601-clm-theme-a-collection",
        phase: "error",
        failedEntryCount: 0,
        message: "互換性確認失敗: version endpoint unavailable",
        now: expect.any(Number),
      });
    });
    expect(container.textContent).toContain("version endpoint unavailable");
  });

  it("queue の拡張再読み込み必須 preflight は current collection を失敗確定せず pause する", async () => {
    const queue = {
      version: 1 as const,
      queueId: "queue-reload-required",
      baseUrl: BASE_URL,
      items: [
        {
          collectionId: "20260601-clm-theme-a-collection",
          status: "pending" as const,
        },
      ],
      currentIndex: 0,
      status: "running" as const,
      runMode: "serial" as const,
      regenerateDurationOutliers: true,
      createdAt: 100,
      updatedAt: 100,
    };
    collectionQueueMocks.readCollectionQueue.mockResolvedValue(queue as never);
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "fetchCompatibilityWarning") {
          return Promise.reject(new Error("Extension context invalidated."));
        }
        return defaultSendMessage(message, payload);
      }
    );

    await rerenderApp();

    await waitFor(() => {
      expect(container.textContent).toContain(
        EXTENSION_RELOAD_REQUIRED_MESSAGE
      );
    });
    expect(
      collectionQueueMocks.settleStoredCollectionQueueRun
    ).not.toHaveBeenCalled();
    expect(collectionQueueMocks.writeCollectionQueue).toHaveBeenCalledWith(
      expect.objectContaining({
        queueId: "queue-reload-required",
        currentIndex: 0,
        status: "paused",
        items: [
          expect.objectContaining({
            collectionId: "20260601-clm-theme-a-collection",
            status: "pending",
          }),
        ],
      })
    );
  });

  it("queue run の negative ACK で保存済み queue が消えていても in-memory queue を durable pause する", async () => {
    const collectionId = "20260601-clm-theme-a-collection";
    const queue = {
      version: 1 as const,
      queueId: "queue-negative-ack-missing",
      baseUrl: BASE_URL,
      items: [{ collectionId, status: "pending" as const }],
      currentIndex: 0,
      status: "running" as const,
      runMode: "serial" as const,
      regenerateDurationOutliers: true,
      createdAt: 100,
      updatedAt: 100,
    };
    collectionQueueMocks.readCollectionQueue.mockResolvedValue(queue as never);
    collectionQueueMocks.settleStoredCollectionQueueRun.mockResolvedValue(null);
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "fetchCompatibilityWarning") return Promise.resolve("");
        if (message === "fetchCollections") {
          return Promise.resolve([
            {
              id: collectionId,
              name: "theme-a",
              channel: "clm",
              theme: "theme-a",
              status: "ready",
              pattern_count: 1,
              downloaded_count: 0,
            },
          ]);
        }
        if (message === "fetchCollectionPromptResponse") {
          return Promise.resolve({
            entries: [{ name: "p1", style: "lofi", lyrics: "" }],
          });
        }
        if (message === "run")
          return Promise.resolve({ ok: false, busy: true });
        return defaultSendMessage(message, payload);
      }
    );

    await rerenderApp();

    await waitFor(() => {
      expect(collectionQueueMocks.writeCollectionQueue).toHaveBeenCalledWith(
        expect.objectContaining({
          queueId: "queue-negative-ack-missing",
          currentIndex: 0,
          status: "paused",
        })
      );
    });
    expect(container.textContent).toContain("queue を一時停止しました");
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
      regenerateDurationOutliers: false,
      durationOutlierWarnings: {
        0: "duration guard NG (60-300s): clip-short; 再生成 OFF のため全 clip を採用候補として保持します",
      },
    } as never);
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);

    await act(async () => {
      root.render(createElement(App));
    });
    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("前回の実行が中断されました。");
      expect(
        checkboxByLabel(container, "異常値の曲を再生成する").hasAttribute(
          "data-checked"
        )
      ).toBe(false);
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
      regenerateDurationOutliers: false,
      indices: undefined,
      submittedClipIds: [],
      submittedClipIdsAreDurationFiltered: false,
      playlistExpectedClipCount: 4,
      durationOutlierWarnings: {
        0: "duration guard NG (60-300s): clip-short; 再生成 OFF のため全 clip を採用候補として保持します",
      },
    });

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 2 },
      });
    });
    expect(container.textContent).toContain("異常値警告");
    expect(container.textContent).toContain("clip-short");
  });

  it("失敗分のみ再実行して FINISHED を受けても前回の異常値警告を維持する", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "" },
      { name: "p2", style: "ambient", lyrics: "" },
    ];
    const warning =
      "duration guard NG (60-300s): clip-short; 再生成 OFF のため全 clip を採用候補として保持します";
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    resumeStateMocks.readResumeState.mockResolvedValue({
      collectionId: "20260601-clm-theme-a-collection",
      failedIndex: 2,
      total: 2,
      timestamp: Date.now(),
      failedIndices: [1],
      submittedClipIds: ["clip-a", "clip-short"],
      submittedClipIdsAreDurationFiltered: false,
      playlistExpectedClipCount: 4,
      regenerateDurationOutliers: false,
      durationOutlierWarnings: { 0: warning },
    } as never);
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);

    await act(async () => {
      root.render(createElement(App));
    });
    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(buttonByText(container, "失敗分のみ再実行")).toBeTruthy();
    });
    const failedAlert = alertByText(
      container,
      "失敗してスキップされた entry: 2"
    );
    expect(failedAlert.dataset.variant).toBe("destructive");
    expect(failedAlert.getAttribute("role")).toBe("alert");
    expectShadcnControl(
      buttonByText(container, "失敗分のみ再実行"),
      "destructive"
    );

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "失敗分のみ再実行").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | theme-a",
      range: undefined,
      collectionId: "20260601-clm-theme-a-collection",
      runMode: "serial",
      regenerateDurationOutliers: false,
      indices: [1],
      submittedClipIds: ["clip-a", "clip-short"],
      submittedClipIdsAreDurationFiltered: false,
      playlistExpectedClipCount: 4,
      durationOutlierWarnings: { 0: warning },
    });

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 2 },
      });
    });
    expect(container.textContent).toContain("異常値警告");
    expect(container.textContent).toContain("clip-short");
  });

  it("実行中に popup を再 open して FINISHED を受けても snapshot の異常値警告を完了表示に残す", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const warning =
      "duration guard NG (60-300s): clip-short; 再生成 OFF のため全 clip を採用候補として保持します";
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "queryProgress") {
          return Promise.resolve({
            collectionId: "20260601-clm-theme-a-collection",
            entries,
            itemStates: ["active"],
            isRunning: true,
            progress: { phase: PHASE.GENERATING, index: 0, total: 1 },
            playlistName: "clm | theme-a",
            regenerateDurationOutliers: false,
            durationOutlierWarnings: { 0: warning },
          });
        }
        return defaultSendMessage(message, payload);
      }
    );

    await rerenderApp();
    await waitFor(() => {
      expect(
        container.querySelector<HTMLElement>(
          '[data-suno-helper="control-panel"]'
        )?.dataset.sunoRunning
      ).toBe("true");
    });

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 1 },
      });
    });

    expect(container.textContent).toContain("異常値警告");
    expect(container.textContent).toContain("clip-short");
  });

  it("dir mode でチェックを外した entry を除外して 0-based indices を run payload に渡す", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "" },
      { name: "p2", style: "lofi", lyrics: "" },
      { name: "p3", style: "lofi", lyrics: "" },
    ];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("3 パターンを取得しました。");
    });

    const checkboxes = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-suno-entry-index] [data-slot="checkbox"]'
      )
    );
    expect(
      checkboxes.map((checkbox) => checkbox.hasAttribute("data-checked"))
    ).toEqual([true, true, true]);

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
      regenerateDurationOutliers: true,
      indices: [0, 2],
      submittedClipIds: undefined,
      submittedClipIdsAreDurationFiltered: undefined,
      playlistExpectedClipCount: undefined,
    });
  });

  it("content snapshot の ERROR だけから再開して FINISHED を受けても option と異常値警告を維持する", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const warning =
      "duration guard NG (60-300s): clip-short; 再生成 OFF のため全 clip を採用候補として保持します";
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
      ])
    );
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "queryProgress") {
          return Promise.resolve({
            collectionId: "20260602-clm-snapshot-collection",
            entries,
            itemStates: ["idle"],
            isRunning: false,
            progress: {
              phase: PHASE.ERROR,
              index: 0,
              total: 1,
              message: "stopped",
            },
            failedIndex: 0,
            playlistName: "clm | snapshot",
            regenerateDurationOutliers: false,
            durationOutlierWarnings: { 0: warning },
          });
        }
        return defaultSendMessage(message, payload);
      }
    );

    await act(async () => {
      root.render(createElement(App));
    });
    await waitFor(() => {
      expect(container.textContent).toContain("前回の実行が中断されました。");
      expect(container.textContent).toContain("異常値警告");
      expect(
        checkboxByLabel(container, "異常値の曲を再生成する").hasAttribute(
          "data-checked"
        )
      ).toBe(false);
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | snapshot",
      range: { start: 0, end: 0 },
      collectionId: "20260602-clm-snapshot-collection",
      runMode: "serial",
      regenerateDurationOutliers: false,
      indices: undefined,
      submittedClipIds: [],
      submittedClipIdsAreDurationFiltered: false,
      playlistExpectedClipCount: 2,
      durationOutlierWarnings: { 0: warning },
    });

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 1 },
      });
    });
    expect(container.textContent).toContain("異常値警告");
    expect(container.textContent).toContain("clip-short");
  });

  it("snapshot 復元後にデータ再取得すると restored collection ではなく取得した collectionId で run する", async () => {
    const restoredEntries = [{ name: "old", style: "lofi", lyrics: "" }];
    const fetchedEntries = [{ name: "fresh", style: "ambient", lyrics: "" }];
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    fetchMock.mockReset();
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
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
      }
    );

    await act(async () => {
      root.render(createElement(App));
    });
    await waitFor(() => {
      expect(container.textContent).toContain("停止しました。再実行できます。");
    });

    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, fetchedEntries));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
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
      regenerateDurationOutliers: true,
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
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("3 パターンを取得しました。");
    });

    const checkboxes = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-suno-entry-index] [data-slot="checkbox"]'
      )
    );
    expect(
      checkboxes.map((checkbox) => checkbox.hasAttribute("data-checked"))
    ).toEqual([true, true, true]);

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

    expect(
      messagingMocks.sendMessage.mock.calls.filter(
        ([message]) => message === "run"
      )
    ).toHaveLength(0);
  });

  it("dir mode の channel/theme から multi-word channel の playlist 名を導出する", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
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
        })
      );
    });
  });

  it("collection を変更するとフル取得を自動実行し entries と実行対象を更新する", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
            pattern_count: 2,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          { name: "b1", style: "jazz", lyrics: "" },
          { name: "b2", style: "ambient", lyrics: "" },
        ])
      );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      setSelectValue(
        expectControl(container, "collection-select") as HTMLSelectElement,
        "20260602-clm-theme-b-collection"
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("2 パターンを取得しました。");
      expect(
        container.querySelector<HTMLElement>(
          '[data-suno-helper="control-panel"]'
        )?.dataset.sunoCollectionId
      ).toBe("20260602-clm-theme-b-collection");
      expect(
        container.querySelectorAll("[data-suno-entry-index]")
      ).toHaveLength(2);
    });
    expect(buttonByText(container, "全パターンを連続実行").disabled).toBe(
      false
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("fetchServerInfo", {
      baseUrl: BASE_URL,
    });
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "fetchCompatibilityWarning",
      {
        baseUrl: BASE_URL,
        extensionVersion: MANIFEST_VERSION,
      }
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "fetchCollections",
      { baseUrl: BASE_URL }
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "fetchCollectionPromptResponse",
      {
        baseUrl: BASE_URL,
        collectionId: "20260602-clm-theme-b-collection",
      }
    );
  });

  it("collection 変更時に配信元が停止していたら起動確認を表示し、select を操作可能に保つ", async () => {
    const collections = [
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
    ];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(jsonResponse(200, collections))
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "a", style: "lofi", lyrics: "" }])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(jsonResponse(500, { error: "server down" }));

    await act(async () => {
      setSelectValue(
        expectControl(container, "server-url") as HTMLSelectElement,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      setSelectValue(
        expectControl(container, "collection-select") as HTMLSelectElement,
        "20260602-clm-theme-b-collection"
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain(
        "yt-collection-serve が起動しているか確認してください。"
      );
      expect(
        expectControl(container, "server-url").getAttribute("disabled")
      ).toBeNull();
      expect(
        expectControl(container, "collection-select").getAttribute("disabled")
      ).toBeNull();
    });
  });

  it("連続する collection 選択では遅れて完了した旧 prompts が最新 entries を上書きしない", async () => {
    const stalePrompts = deferred<Response>();
    const collections = [
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
    ];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(jsonResponse(200, collections))
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "initial-a", style: "lofi", lyrics: "" }])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(jsonResponse(200, collections))
      .mockReturnValueOnce(stalePrompts.promise)
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(jsonResponse(200, collections))
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "latest-a", style: "ambient", lyrics: "" }])
      );

    await act(async () => {
      setSelectValue(
        expectControl(container, "server-url") as HTMLSelectElement,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("initial-a");
    });

    await act(async () => {
      setSelectValue(
        expectControl(container, "collection-select") as HTMLSelectElement,
        "20260602-clm-theme-b-collection"
      );
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(6);
    });
    await act(async () => {
      setSelectValue(
        expectControl(container, "collection-select") as HTMLSelectElement,
        "20260601-clm-theme-a-collection"
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("latest-a");
    });

    await act(async () => {
      stalePrompts.resolve(
        jsonResponse(200, [{ name: "stale-b", style: "jazz", lyrics: "" }])
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("latest-a");
      expect(container.textContent).not.toContain("stale-b");
      expect(
        container.querySelector<HTMLElement>(
          '[data-suno-helper="control-panel"]'
        )?.dataset.sunoCollectionId
      ).toBe("20260601-clm-theme-a-collection");
    });
  });

  it("clip ID が無い再開時に Suno 上の選択中 clip を採用して resume state に保存する", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const adoptionResponse = deferred<{ ok: true; clipIds: string[] }>();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "queryProgress") {
          throw new Error("runner unavailable");
        }
        if (message === "adoptSelectedClips") {
          return adoptionResponse.promise;
        }
        return defaultSendMessage(message, payload);
      }
    );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });

    await waitFor(() => {
      const panel = container.querySelector<HTMLElement>(
        '[data-suno-helper="control-panel"]'
      );
      expect(panel?.dataset.sunoPhase).toBe("adopting");
      expect(panel?.dataset.sunoRunning).toBe("true");
    });
    await act(async () => {
      adoptionResponse.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        "選択中の曲 2 件を採用しました。"
      );
    });
    expect(
      container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]')
        ?.dataset.sunoPhase
    ).toBe("idle");
    expect(
      container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]')
        ?.dataset.sunoRunning
    ).toBe("false");
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "adoptSelectedClips",
      { expectedClipCount: 2 }
    );
    expect(resumeStateMocks.writeResumeState).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "20260601-clm-theme-a-collection",
        failedIndex: 1,
        total: 1,
        submittedClipIds: ["clip-a", "clip-b"],
        submittedClipIdsAreDurationFiltered: false,
        playlistExpectedClipCount: 2,
      })
    );
  });

  it("選択中 clip 採用後に Download から再開すると retryDownload payload を送る", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const downloadResponse = deferred<unknown>();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
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
      }
    );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        "選択中の曲 2 件を採用しました。"
      );
    });
    expectShadcnControl(expectControl(container, "retry-playlist"), "warning");
    expectShadcnControl(expectControl(container, "retry-download"), "success");

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    await waitFor(() => {
      const panel = container.querySelector<HTMLElement>(
        '[data-suno-helper="control-panel"]'
      );
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
      expect(container.textContent).toContain(
        "ダウンロードを再実行しています…"
      );
    });
  });

  it("collection に保存済み playlist URL がある場合も Download 再開 payload に含めない", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "queryProgress") {
          throw new Error("runner unavailable");
        }
        if (message === "adoptSelectedClips") {
          return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
        }
        return defaultSendMessage(message, payload);
      }
    );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        "選択中の曲 2 件を採用しました。"
      );
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
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "queryProgress") {
          throw new Error("runner unavailable");
        }
        if (message === "adoptSelectedClips") {
          return Promise.resolve({
            ok: true,
            clipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
          });
        }
        return defaultSendMessage(message, payload);
      }
    );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        "選択中の曲 4 件を採用しました。"
      );
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "adoptSelectedClips",
      { expectedClipCount: 4 }
    );

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

    await waitFor(() => {
      expect(expectControl(container, "download-format").textContent).toContain(
        "M4A"
      );
    });

    await setDownloadFormatValue(container, "wav");

    expect(downloadFormatMocks.setValue).toHaveBeenCalledWith("wav");
    expect(expectControl(container, "download-format").textContent).toContain(
      "WAV"
    );
  });

  it("DL 形式の読込が失敗すると未捕捉にせず再読み込み案内を表示する", async () => {
    downloadFormatMocks.getValue.mockRejectedValueOnce(
      new Error("'wxt/storage' must be loaded in a web extension environment")
    );

    await act(async () => {
      root.unmount();
    });
    container.innerHTML = "";
    root = createRoot(container);
    await act(async () => {
      root.render(createElement(App));
    });

    await waitFor(() => {
      expect(container.textContent).toContain(
        EXTENSION_RELOAD_REQUIRED_MESSAGE
      );
      const alert = expectControl(container, "reload-required");
      expect(alert.dataset.slot).toBe("alert");
      expect(alert.dataset.variant).toBe("warning");
      expectShadcnControl(expectControl(container, "reload-tab"), "outline");
    });
  });

  it.each([
    [
      "server URL",
      () =>
        storageMocks.getValue.mockRejectedValueOnce(
          new Error("Extension context invalidated.")
        ),
    ],
    [
      "server source migration",
      () =>
        serverSourcesMocks.migrateServerSourcesStorage.mockRejectedValueOnce(
          new Error("Extension context invalidated.")
        ),
    ],
    [
      "run mode",
      () =>
        presetStateMocks.readRunModeId.mockRejectedValueOnce(
          new Error("Extension context invalidated.")
        ),
    ],
    [
      "resume state",
      () =>
        resumeStateMocks.readResumeState.mockRejectedValueOnce(
          new Error("Extension context invalidated.")
        ),
    ],
  ])("%s の読込失敗を再読み込み案内へ集約する", async (_label, rejectRead) => {
    rejectRead();
    await rerenderApp();

    await waitFor(() => {
      expect(container.textContent).toContain(
        EXTENSION_RELOAD_REQUIRED_MESSAGE
      );
      expect(buttonByText(container, "タブを再読み込み")).toBeTruthy();
    });
  });

  it("run mode の保存失敗を再読み込み案内へ集約する", async () => {
    presetStateMocks.writeRunModeId.mockRejectedValueOnce(
      new Error("Extension context invalidated.")
    );
    const queueRadio = radioByLabel(container, "高速モード");

    await act(async () => {
      queueRadio.click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain(
        EXTENSION_RELOAD_REQUIRED_MESSAGE
      );
    });
  });

  it("server URL の保存失敗を再読み込み案内へ集約し、再保存しない", async () => {
    storageMocks.setValue.mockRejectedValueOnce(
      new Error("Extension context invalidated.")
    );
    const serverSelect = expectControl(
      container,
      "server-url"
    ) as HTMLSelectElement;
    setSelectValue(serverSelect, BASE_URL);

    await waitFor(() => {
      expect(container.textContent).toContain(
        EXTENSION_RELOAD_REQUIRED_MESSAGE
      );
    });
    expect(storageMocks.setValue).toHaveBeenCalledOnce();
  });

  it("互換性確認の No response を未捕捉にせず再読み込み案内へ集約する", async () => {
    messagingMocks.sendMessage.mockImplementation((message, payload) => {
      if (message === "fetchCompatibilityWarning") {
        return Promise.reject(new Error("No response at sendMessage"));
      }
      return defaultSendMessage(message, payload);
    });
    const serverSelect = expectControl(
      container,
      "server-url"
    ) as HTMLSelectElement;
    setSelectValue(serverSelect, BASE_URL);

    await waitFor(() => {
      expect(container.textContent).toContain(
        EXTENSION_RELOAD_REQUIRED_MESSAGE
      );
      expect(buttonByText(container, "タブを再読み込み")).toBeTruthy();
    });
  });

  it("DL 形式の保存が失敗すると未捕捉にせず再読み込み案内を表示する", async () => {
    downloadFormatMocks.setValue.mockRejectedValueOnce(
      new Error("Extension context invalidated.")
    );
    await setDownloadFormatValue(container, "wav");

    await waitFor(() => {
      expect(container.textContent).toContain(
        EXTENSION_RELOAD_REQUIRED_MESSAGE
      );
      expect(buttonByText(container, "タブを再読み込み")).toBeTruthy();
    });
  });

  it("DL 形式 select は不正な storage 値を MP3 に戻す", async () => {
    await rerenderAppWithDownloadFormat("flac");

    await waitFor(() => {
      expect(expectControl(container, "download-format").textContent).toContain(
        "MP3"
      );
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
    let progressHandler:
      | ((event: { data: ProgressPayload }) => void)
      | undefined;

    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "queryProgress") {
          return Promise.resolve(snapshot);
        }
        return defaultSendMessage(message, payload);
      }
    );
    messagingMocks.onMessage.mockImplementation(
      (message?: unknown, handler?: unknown) => {
        if (message === "progress" && typeof handler === "function") {
          progressHandler = handler as (event: {
            data: ProgressPayload;
          }) => void;
        }
        return () => undefined;
      }
    );

    await act(async () => {
      root.unmount();
    });
    container.innerHTML = "";
    root = createRoot(container);
    await act(async () => {
      root.render(createElement(App));
    });

    const checkboxStates = (): boolean[] =>
      Array.from(
        container.querySelectorAll<HTMLButtonElement>(
          '[data-suno-entry-index] [data-slot="checkbox"]'
        )
      ).map((checkbox) => checkbox.hasAttribute("data-checked"));

    await waitFor(() => {
      expect(checkboxStates()).toEqual([true, true, true]);
    });

    await act(async () => {
      progressHandler?.({
        data: { phase: PHASE.DONE, index: 1, total: entries.length },
      });
    });
    await waitFor(() => {
      expect(checkboxStates()).toEqual([true, false, true]);
    });
    expect(
      Array.from(
        container.querySelectorAll<HTMLButtonElement>(
          '[data-suno-entry-index] [data-slot="checkbox"]'
        )
      )[1]?.closest("li")?.className
    ).toContain("line-through");

    await act(async () => {
      Array.from(
        container.querySelectorAll<HTMLButtonElement>(
          '[data-suno-entry-index] [data-slot="checkbox"]'
        )
      )[1]?.click();
    });
    await waitFor(() => {
      expect(checkboxStates()).toEqual([true, true, true]);
    });

    await act(async () => {
      progressHandler?.({
        data: { phase: PHASE.DONE, index: 0, total: entries.length },
      });
    });
    await waitFor(() => {
      expect(checkboxStates()).toEqual([false, true, true]);
    });
  });

  it("選択中 clip 採用後に Playlist から再開すると retryPlaylist payload を送る", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    const playlistResponse = deferred<unknown>();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
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
      }
    );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        "選択中の曲 2 件を採用しました。"
      );
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    await waitFor(() => {
      const panel = container.querySelector<HTMLElement>(
        '[data-suno-helper="control-panel"]'
      );
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
      regenerateDurationOutliers: true,
      durationOutlierWarnings: undefined,
      shouldDownload: true,
    });
    await act(async () => {
      playlistResponse.resolve({ ok: true });
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        "playlist 追加とダウンロードを再実行しています…"
      );
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
      regenerateDurationOutliers: false,
      durationOutlierWarnings: {
        0: "duration guard NG (75-180s): clip-b; 再生成 OFF のため全 clip を採用候補として保持します",
      },
    } as never);
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(500, {}));
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);

    await act(async () => {
      root.render(createElement(App));
    });
    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).not.toContain(
        "全 entry 投入済みです。playlist 追加から再開しますか？"
      );
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
      regenerateDurationOutliers: false,
      durationOutlierWarnings: {
        0: "duration guard NG (75-180s): clip-b; 再生成 OFF のため全 clip を採用候補として保持します",
      },
      shouldDownload: true,
    });

    await act(async () => {
      messagingMocks.progressHandler?.({
        data: { phase: PHASE.FINISHED, total: 0 },
      });
    });
    expect(container.textContent).toContain("異常値警告");
    expect(container.textContent).toContain("clip-b");
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
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(jsonResponse(500, {}));
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);

    await act(async () => {
      root.render(createElement(App));
    });
    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("前回の実行が中断されました。");
      expect(container.textContent).toContain("取得失敗:");
    });
    const resumeAlert = alertByText(container, "前回の実行が中断されました。");
    expect(resumeAlert.dataset.variant).toBe("warning");
    expect(resumeAlert.getAttribute("role")).toBe("alert");
    expectShadcnControl(expectControl(container, "resume"), "warning");
    expectShadcnControl(expectControl(container, "dismiss-resume"), "outline");

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "再開").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith(
      "run",
      expect.anything()
    );
    expect(container.textContent).toContain(
      "再開に必要なパターンが未取得です。ページを再読み込みしてから再試行してください。"
    );
    expect(container.textContent).toContain("前回の実行が中断されました。");
  });

  it("clip ID が無い状態で Playlist から再開しても retryPlaylist を送らずエラー表示する", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }])
      );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith(
      "retryPlaylist",
      expect.anything()
    );
    expect(container.textContent).toContain(
      "playlist 再開に必要な clip ID がありません。ページを再読み込みしてから再試行してください。"
    );
  });

  it("Playlist から再開の送信に失敗したらエラーを表示して再試行可能にする", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
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
      }
    );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        "選択中の曲 2 件を採用しました。"
      );
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "retryPlaylist",
      expect.anything()
    );
    await waitFor(() => {
      expect(container.textContent).toContain("開始失敗: relay failed");
      expect(buttonByText(container, "Playlist から再開").disabled).toBe(false);
    });
  });

  it("clip ID が無い状態で Download から再開しても retryDownload を送らずエラー表示する", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }])
      );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith(
      "retryDownload",
      expect.anything()
    );
    expect(container.textContent).toContain(
      "ダウンロード再開に必要な clip ID がありません。ページを再読み込みしてから再試行してください。"
    );
  });

  it("期待 clip 数を解決できない場合は採用を送らずページ再読み込みを案内する", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-empty-collection",
            name: "empty-collection",
            status: "ready",
            pattern_count: 0,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, []));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("0 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith(
      "adoptSelectedClips",
      expect.anything()
    );
    expect(container.textContent).toContain(
      "期待 clip 数を解決できません。ページを再読み込みしてから再試行してください。"
    );
  });

  it("ローカル配信元を変更すると新しい URL の一覧と prompts へ自動で切り替わる", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260602-clm-new-source-collection",
            name: "new-source-collection",
            status: "ready",
            pattern_count: 2,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          { name: "new-1", style: "jazz", lyrics: "" },
          { name: "new-2", style: "ambient", lyrics: "" },
        ])
      );

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        `${BASE_URL}/changed`
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("2 パターンを取得しました。");
      expect(
        container.querySelector<HTMLElement>(
          '[data-suno-helper="control-panel"]'
        )?.dataset.sunoCollectionId
      ).toBe("20260602-clm-new-source-collection");
      expect(
        container.querySelectorAll("[data-suno-entry-index]")
      ).toHaveLength(2);
    });
    expect(buttonByText(container, "全パターンを連続実行").disabled).toBe(
      false
    );
    expect(storageMocks.setValue).toHaveBeenLastCalledWith(
      `${BASE_URL}/changed`
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "fetchCollections",
      { baseUrl: `${BASE_URL}/changed` }
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
      "fetchCollectionPromptResponse",
      {
        baseUrl: `${BASE_URL}/changed`,
        collectionId: "20260602-clm-new-source-collection",
      }
    );
  });

  it("配信元の一時失敗では明示した配信元と collection の表示を保持する", async () => {
    const collections = [
      {
        id: "20260601-clm-theme-a-collection",
        name: "theme-a-collection",
        status: "ready",
        pattern_count: 1,
        downloaded_count: 0,
      },
    ];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(jsonResponse(200, collections))
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "initial", style: "lofi", lyrics: "" }])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (
          message === "fetchServerInfo" &&
          payload?.baseUrl === FALLBACK_URL
        ) {
          return Promise.resolve({
            base_url: "http://127.0.0.1:7877",
            label: "fallback",
          });
        }
        return defaultSendMessage(message, payload);
      }
    );

    await act(async () => {
      setSelectValue(
        expectControl(container, "server-url") as HTMLSelectElement,
        BASE_URL
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      setSelectValue(
        expectControl(container, "server-url") as HTMLSelectElement,
        FALLBACK_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("取得失敗: Failed to fetch");
    });
    expect(
      (expectControl(container, "server-url") as HTMLSelectElement).value
    ).toBe(FALLBACK_URL);
    expect(
      container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]')
        ?.dataset.sunoCollectionId
    ).toBe("20260601-clm-theme-a-collection");
    expect(container.textContent).toContain("initial");
  });

  it("連続する配信元変更では遅い旧保存が最新 URL・配信元一覧・entries を上書きしない", async () => {
    const firstSave = deferred<undefined>();
    let saveCount = 0;
    storageMocks.setValue.mockImplementation(() => {
      saveCount += 1;
      if (saveCount === 1) {
        return firstSave.promise;
      }
      return Promise.resolve(undefined);
    });
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260602-clm-new-source-collection",
            name: "new-source-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "new-source", style: "jazz", lyrics: "" }])
      );

    const serverSelect = expectControl(
      container,
      "server-url"
    ) as HTMLSelectElement;
    await act(async () => {
      setSelectValue(serverSelect, BASE_URL);
    });
    await waitFor(() => {
      expect(storageMocks.setValue).toHaveBeenCalledWith(BASE_URL);
    });

    await act(async () => {
      setSelectValue(serverSelect, `${BASE_URL}/changed`);
    });
    await act(async () => {
      firstSave.resolve(undefined);
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(storageMocks.setValue).toHaveBeenLastCalledWith(
      `${BASE_URL}/changed`
    );
    expect(serverSelect.value).toBe(`${BASE_URL}/changed`);
    expect(
      Array.from(serverSelect.options, (option) => option.value)
    ).toContain(`${BASE_URL}/changed`);
    expect(
      container.querySelector<HTMLElement>('[data-suno-helper="control-panel"]')
        ?.dataset.sunoCollectionId
    ).toBe("20260602-clm-new-source-collection");
    expect(container.textContent).toContain("new-source");
  });

  it("dir mode の collection 一覧に実行可能候補が無い場合は legacy endpoint へフォールバックしない", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(jsonResponse(200, []));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain(
        "取得失敗: prompts を取得できる collection がありません。"
      );
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
  });

  it("/collections が HTTP 404 の場合は legacy endpoint へフォールバックせずエラー表示する", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(jsonResponse(404, {}));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("取得失敗: HTTP 404");
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
  });

  it("popup 起動時に保存 URL から一覧と選択 collection の prompts まで一度だけ自動取得する", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    fetchMock.mockReset();
    storageMocks.getValue.mockResolvedValue(BASE_URL);
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "mounted", style: "lofi", lyrics: "" }])
      );

    await act(async () => {
      root.render(createElement(App));
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(buttonByText(container, "全パターンを連続実行").disabled).toBe(
      false
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/collections/20260601-clm-theme-a-collection/suno/prompts.json`
    );
    expect(
      messagingMocks.sendMessage.mock.calls.filter(
        ([message]) => message === "fetchCollections"
      )
    ).toHaveLength(1);
  });

  it("popup 起動時の collection 一覧同期は downloaded collection を完了件数付きで表示する", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    fetchMock.mockReset();
    storageMocks.getValue.mockResolvedValue(BASE_URL);
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockResolvedValueOnce(
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
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse(200, [{ name: "done", style: "lofi", lyrics: "" }])
      );

    await act(async () => {
      root.render(createElement(App));
    });

    await waitFor(() => {
      expect(container.textContent).toContain("ready-collection");
    });
    expect(container.textContent).toContain("done-collection（完了 4/4）");
    const doneOption = Array.from(container.querySelectorAll("option")).find(
      (option) => option.textContent?.includes("done-collection")
    );
    expect(doneOption?.disabled).toBe(false);
  });

  it("CORS なし 404 (TypeError) で /collections が reject されたら legacy endpoint へ fallback しない", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("取得失敗: Failed to fetch");
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
  });

  it("should migrate before initial discovery and replace stopped candidates before the selector opens", async () => {
    const defaultSource = {
      id: "youtube-automation-localhost-7873",
      label: "YouTube Automation (default)",
      url: "http://youtube-automation.localhost:7873",
    };
    const oldSource = {
      id: "old-9001",
      label: "Old",
      url: "http://old.localhost:9001",
    };
    const newSource = {
      id: "new-49152",
      label: "New",
      url: "http://new.localhost:49152",
    };
    const events: string[] = [];
    serverSourcesMocks.migrateServerSourcesStorage.mockImplementation(
      async () => {
        events.push("migration");
      }
    );
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "discoverServerSources") {
          events.push("discovery");
          const discoveryCount = events.filter(
            (event) => event === "discovery"
          ).length;
          return Promise.resolve(
            discoveryCount === 1
              ? [defaultSource, oldSource]
              : [defaultSource, newSource]
          );
        }
        return defaultSendMessage(message, payload);
      }
    );

    await rerenderApp();
    const select = expectControl(container, "server-url") as HTMLSelectElement;
    await waitFor(() =>
      expect(Array.from(select.options, ({ value }) => value)).toContain(
        oldSource.url
      )
    );
    expect(events.slice(0, 2)).toEqual(["migration", "discovery"]);

    await act(async () => {
      (
        expectControl(container, "server-source-trigger") as HTMLButtonElement
      ).click();
    });
    await waitFor(() =>
      expect(Array.from(select.options, ({ value }) => value)).toContain(
        newSource.url
      )
    );
    expect(Array.from(select.options, ({ value }) => value)).toEqual([
      defaultSource.url,
      newSource.url,
    ]);

    await act(async () =>
      (
        expectControl(container, "server-source-trigger") as HTMLButtonElement
      ).click()
    );
    await waitFor(() =>
      expect(events.filter((event) => event === "discovery")).toHaveLength(3)
    );
  });

  it("should run discovery once when opening an unfocused selector with the mouse", async () => {
    await rerenderApp();
    const initialCalls = messagingMocks.sendMessage.mock.calls.filter(
      ([message]) => message === "discoverServerSources"
    ).length;

    await act(async () => {
      (
        expectControl(container, "server-source-trigger") as HTMLButtonElement
      ).click();
    });

    await waitFor(() =>
      expect(
        messagingMocks.sendMessage.mock.calls.filter(
          ([message]) => message === "discoverServerSources"
        )
      ).toHaveLength(initialCalls + 1)
    );
  });

  it("should refresh and open the selector while the initial collection fetch is still pending", async () => {
    const initialCollections = deferred<unknown>();
    const defaultSource = {
      id: "youtube-automation-localhost-7873",
      label: "YouTube Automation (default)",
      url: "http://youtube-automation.localhost:7873",
    };
    const liveSource = {
      id: "live",
      label: "Live",
      url: "http://live.localhost:49152",
    };
    storageMocks.getValue.mockResolvedValue(defaultSource.url);
    let discoveryCount = 0;
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "discoverServerSources") {
          discoveryCount += 1;
          return Promise.resolve(
            discoveryCount === 1 ? [defaultSource] : [defaultSource, liveSource]
          );
        }
        if (message === "fetchCompatibilityWarning") {
          return Promise.resolve("");
        }
        if (message === "fetchCollections") {
          return initialCollections.promise;
        }
        return defaultSendMessage(message, payload);
      }
    );

    await rerenderApp();
    await waitFor(() =>
      expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
        "fetchCollections",
        { baseUrl: defaultSource.url }
      )
    );

    await act(async () => {
      (
        expectControl(container, "server-source-trigger") as HTMLButtonElement
      ).click();
    });

    await waitFor(() => expect(discoveryCount).toBe(2));
    await waitFor(() =>
      expect(container.querySelector('[role="listbox"]')).not.toBeNull()
    );
    expect(container.querySelector('[role="listbox"]')?.textContent).toContain(
      "Live"
    );
  });

  it("should replace a restored URL removed by discovery during an early selector refresh", async () => {
    await act(async () => root.unmount());
    container.innerHTML = "";
    root = createRoot(container);
    const initialDiscovery =
      deferred<Array<{ id: string; label: string; url: string }>>();
    const defaultSource = {
      id: "youtube-automation-localhost-7873",
      label: "YouTube Automation (default)",
      url: "http://youtube-automation.localhost:7873",
    };
    const restoredSource = {
      id: "restored",
      label: "Restored",
      url: "http://restored.localhost:49152",
    };
    storageMocks.getValue.mockResolvedValue(restoredSource.url);
    fetchMock.mockResolvedValue(jsonResponse(404, {}));
    let discoveryCount = 0;
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "discoverServerSources") {
          discoveryCount += 1;
          return discoveryCount === 1
            ? initialDiscovery.promise
            : Promise.resolve([defaultSource]);
        }
        return defaultSendMessage(message, payload);
      }
    );

    await act(async () => root.render(createElement(App)));
    const select = expectControl(container, "server-url") as HTMLSelectElement;
    await act(async () => {
      (
        expectControl(container, "server-source-trigger") as HTMLButtonElement
      ).click();
      initialDiscovery.resolve([defaultSource, restoredSource]);
      await initialDiscovery.promise;
    });

    await waitFor(() =>
      expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
        "fetchCollections",
        { baseUrl: defaultSource.url }
      )
    );
    expect(select.value).toBe(defaultSource.url);
    expect(discoveryCount).toBe(2);
  });

  it.each([
    [
      "keeps a saved live URL",
      "http://live.localhost:49152",
      "http://live.localhost:49152",
    ],
    [
      "replaces a saved stopped URL",
      "http://stopped.localhost:9001",
      "http://youtube-automation.localhost:7873",
    ],
  ])(
    "should %s without fetching the stopped URL",
    async (_label, savedUrl, expectedUrl) => {
      const defaultSource = {
        id: "youtube-automation-localhost-7873",
        label: "YouTube Automation (default)",
        url: "http://youtube-automation.localhost:7873",
      };
      const liveSource = {
        id: "live",
        label: "Live",
        url: "http://live.localhost:49152",
      };
      storageMocks.getValue.mockResolvedValue(savedUrl);
      messagingMocks.sendMessage.mockImplementation(
        (message: string, payload?: Record<string, string>) => {
          if (message === "discoverServerSources")
            return Promise.resolve([defaultSource, liveSource]);
          if (payload?.baseUrl === "http://stopped.localhost:9001") {
            throw new Error("stopped URL must not be fetched");
          }
          return defaultSendMessage(message, payload);
        }
      );

      await rerenderApp();
      await waitFor(() =>
        expect(
          (expectControl(container, "server-url") as HTMLSelectElement).value
        ).toBe(expectedUrl)
      );

      expect(
        messagingMocks.sendMessage.mock.calls.some(
          ([, payload]) => payload?.baseUrl === "http://stopped.localhost:9001"
        )
      ).toBe(false);
      if (savedUrl !== expectedUrl)
        expect(storageMocks.setValue).toHaveBeenCalledWith(expectedUrl);
    }
  );

  it("should persist only the selected URL when choosing a discovered non-default source", async () => {
    const liveSource = {
      id: "channel-a-49152",
      label: "Channel A",
      url: "http://channel-a.localhost:49152",
    };
    fetchMock.mockResolvedValue(jsonResponse(404, {}));
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "discoverServerSources") {
          return Promise.resolve([
            {
              id: "youtube-automation-localhost-7873",
              label: "YouTube Automation (default)",
              url: "http://youtube-automation.localhost:7873",
            },
            liveSource,
          ]);
        }
        return defaultSendMessage(message, payload);
      }
    );
    await rerenderApp();
    const select = expectControl(container, "server-url") as HTMLSelectElement;
    await waitFor(() =>
      expect(Array.from(select.options, ({ value }) => value)).toContain(
        liveSource.url
      )
    );
    await act(async () =>
      (
        expectControl(container, "server-source-trigger") as HTMLButtonElement
      ).click()
    );
    await waitFor(() =>
      expect(container.querySelector('[role="listbox"]')).not.toBeNull()
    );
    await act(async () => {
      Array.from(
        container.querySelectorAll<HTMLButtonElement>('[role="option"]')
      )
        .find((option) => option.textContent?.includes("Channel A"))!
        .click();
    });

    await waitFor(() =>
      expect(storageMocks.setValue).toHaveBeenCalledWith(liveSource.url)
    );
    expect(container.querySelector('[role="listbox"]')).toBeNull();
    expect(legacySourceState.present).toBe(false);
    await waitFor(() =>
      expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
        "fetchCollections",
        { baseUrl: liveSource.url }
      )
    );

    storageMocks.getValue.mockResolvedValue(liveSource.url);
    await rerenderApp();
    await waitFor(() =>
      expect(
        (expectControl(container, "server-url") as HTMLSelectElement).value
      ).toBe(liveSource.url)
    );
  });

  it("should ignore an older discovery completion", async () => {
    const older = deferred<Array<{ id: string; label: string; url: string }>>();
    const newer = deferred<Array<{ id: string; label: string; url: string }>>();
    let refreshCount = 0;
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "discoverServerSources") {
          refreshCount += 1;
          if (refreshCount === 1) {
            return Promise.resolve([]);
          }
          return refreshCount === 2 ? older.promise : newer.promise;
        }
        return defaultSendMessage(message, payload);
      }
    );
    await rerenderApp();
    const select = expectControl(container, "server-url") as HTMLSelectElement;
    await act(async () => {
      const trigger = expectControl(
        container,
        "server-source-trigger"
      ) as HTMLButtonElement;
      trigger.click();
      trigger.click();
    });
    newer.resolve([
      { id: "new", label: "New", url: "http://new.localhost:49152" },
    ]);
    await waitFor(() => expect(select.textContent).toContain("New"));
    older.resolve([
      { id: "old", label: "Old", url: "http://old.localhost:9001" },
    ]);
    await act(async () => Promise.resolve());
    expect(select.textContent).toContain("New");
    expect(select.textContent).not.toContain("Old");
  });

  it("should discard a deferred discovery result when a run starts", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          version: "5.5.7",
          min_extension_version: MANIFEST_VERSION,
        })
      )
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
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    await act(async () =>
      setSelectValue(
        expectControl(container, "server-url") as HTMLSelectElement,
        BASE_URL
      )
    );
    await waitFor(() =>
      expect(buttonByText(container, "全パターンを連続実行").disabled).toBe(
        false
      )
    );
    await act(async () =>
      (
        expectControl(container, "server-source-trigger") as HTMLButtonElement
      ).click()
    );
    await waitFor(() =>
      expect(container.querySelector('[role="listbox"]')).not.toBeNull()
    );

    const pendingDiscovery =
      deferred<Array<{ id: string; label: string; url: string }>>();
    messagingMocks.sendMessage.mockImplementation(
      (message: string, payload?: Record<string, string>) => {
        if (message === "discoverServerSources")
          return pendingDiscovery.promise;
        return defaultSendMessage(message, payload);
      }
    );
    const select = expectControl(container, "server-url") as HTMLSelectElement;
    await act(async () => {
      (
        expectControl(container, "server-source-trigger") as HTMLButtonElement
      ).click();
      buttonByText(container, "全パターンを連続実行").click();
    });
    await waitFor(() =>
      expect(
        container.querySelector<HTMLElement>(
          '[data-suno-helper="control-panel"]'
        )?.dataset.sunoRunning
      ).toBe("true")
    );
    expect(container.querySelector('[role="listbox"]')).toBeNull();

    pendingDiscovery.resolve([
      { id: "new", label: "New", url: "http://new.localhost:49152" },
    ]);
    await act(async () => pendingDiscovery.promise);

    expect(select.textContent).not.toContain("New");
    expect(select.value).toBe(BASE_URL);
    expect(
      messagingMocks.sendMessage.mock.calls.some(
        ([, payload]) => payload?.baseUrl === "http://new.localhost:49152"
      )
    ).toBe(false);
  });
});
