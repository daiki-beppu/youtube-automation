// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Overlay } from "../components/Overlay";

const INITIAL_STATE = {
  position: { x: 40, y: 50 },
  minimized: false,
  hidden: false,
};

const messagingMocks = vi.hoisted(() => ({
  onMessage: vi.fn(() => () => undefined),
  sendMessage: vi.fn(async () => ({ version: "0.2.5", matches: true })),
}));

const overlayStateMocks = vi.hoisted(() => ({
  readOverlayState: vi.fn(async () => INITIAL_STATE),
  writeOverlayState: vi.fn(async () => undefined),
}));

const runner = vi.hoisted(() => ({
  reloadRequired: false,
  url: "",
  setUrl: vi.fn(),
  serverSources: [],
  refreshServerSources: vi.fn(async () => undefined),
  collections: [],
  selectedCollectionId: "",
  selectCollection: vi.fn(),
  collectionQueue: null,
  runCollectionQueue: vi.fn(),
  resumeCollectionQueue: vi.fn(),
  entries: [],
  itemStates: [],
  status: "待機中",
  phase: "idle",
  isError: false,
  compatibilityWarning: "",
  canRun: false,
  isRunning: false,
  completionSoundSettings: { enabled: true, preset: "chime" },
  setCompletionSoundEnabled: vi.fn(),
  setCompletionSoundPreset: vi.fn(),
  previewCompletionSound: vi.fn(async () => undefined),
  playlistName: "",
  runModeId: "serial",
  setRunMode: vi.fn(),
  regenerateDurationOutliers: true,
  setRegenerateDurationOutliers: vi.fn(),
  resumeBanner: null,
  acceptResume: vi.fn(),
  dismissResume: vi.fn(),
  failedEntries: [],
  rerunFailed: vi.fn(),
  retryPlaylist: vi.fn(),
  retryDownload: vi.fn(),
  adoptSelectedClips: vi.fn(),
  run: vi.fn(),
  stop: vi.fn(),
}));

vi.mock("../lib/messaging", () => messagingMocks);
vi.mock("../lib/overlay-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/overlay-state")>(
    "../lib/overlay-state"
  );
  return {
    ...actual,
    readOverlayState: overlayStateMocks.readOverlayState,
    writeOverlayState: overlayStateMocks.writeOverlayState,
  };
});
vi.mock("../lib/storage", () => ({
  downloadFormatItem: { setValue: vi.fn(async () => undefined) },
  readDownloadFormat: vi.fn(async () => "mp3"),
}));
vi.mock("../components/useSunoRunner", () => ({ useSunoRunner: () => runner }));

async function waitFor(assertion: () => void): Promise<void> {
  for (let i = 0; i < 20; i += 1) {
    try {
      assertion();
      return;
    } catch (error) {
      if (i === 19) throw error;
      await act(async () => {
        await Promise.resolve();
      });
    }
  }
}

describe("Overlay shell", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("browser", {
      runtime: { getManifest: vi.fn(() => ({ version: "0.2.5" })) },
    });
    messagingMocks.sendMessage.mockClear();
    messagingMocks.onMessage.mockClear();
    overlayStateMocks.readOverlayState.mockClear();
    overlayStateMocks.writeOverlayState.mockClear();
    Object.assign(runner, {
      collections: [],
      selectedCollectionId: "",
      entries: [],
      itemStates: [],
      canRun: false,
      collectionQueue: null,
    });
    runner.runCollectionQueue.mockClear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(createElement(Overlay));
    });
    await waitFor(() =>
      expect(container.querySelector('[data-slot="card"]')).not.toBeNull()
    );
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  it("Card shell を最小化・復元し、同じ visibility/control 状態を永続化する", async () => {
    const card = container.querySelector<HTMLElement>('[data-slot="card"]')!;
    const header = container.querySelector<HTMLElement>(
      '[data-slot="card-header"]'
    )!;
    const content = container.querySelector<HTMLElement>(
      '[data-slot="card-content"]'
    )!;
    const minimize = container.querySelector<HTMLButtonElement>(
      'button[aria-label="最小化"]'
    )!;

    expect(card.style.left).toBe("40px");
    expect(card.style.top).toBe("50px");
    expect(header.className.split(" ")).toContain("flex-row");
    expect(header.style.pointerEvents).toBe("auto");
    expect(content.style.pointerEvents).toBe("auto");
    expect(content.style.display).toBe("block");
    expect(minimize.dataset.slot).toBe("button");
    expect(minimize.className.split(" ")).not.toContain("size-9");
    const panel = content.querySelector<HTMLElement>(
      ':scope > [data-suno-helper="control-panel"]'
    )!;
    expect(panel.dataset.sunoPhase).toBe("idle");
    expect(panel.dataset.sunoRunning).toBe("false");
    expect(panel.dataset.sunoError).toBe("false");
    const status = panel.querySelector<HTMLElement>('[role="status"]')!;
    expect(status.dataset.slot).toBe("alert");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.dataset.sunoStatus).toBe("ok");
    expect(status.textContent).toBe("待機中");

    await act(async () => minimize.click());

    expect(content.style.pointerEvents).toBe("none");
    expect(content.style.display).toBe("none");
    expect(container.querySelector('button[aria-label="展開"]')).not.toBeNull();
    expect(overlayStateMocks.writeOverlayState).toHaveBeenLastCalledWith({
      position: { x: 40, y: 50 },
      minimized: true,
      hidden: false,
    });

    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('button[aria-label="展開"]')!
        .click()
    );

    expect(content.style.pointerEvents).toBe("auto");
    expect(content.style.display).toBe("block");
    expect(
      container.querySelector('button[aria-label="最小化"]')
    ).not.toBeNull();
    expect(overlayStateMocks.writeOverlayState).toHaveBeenLastCalledWith({
      position: { x: 40, y: 50 },
      minimized: false,
      hidden: false,
    });
  });

  it("drag handle の pointer 操作で位置を更新し pointerup 時に永続化する", async () => {
    const header = container.querySelector<HTMLElement>(
      '[data-slot="card-header"]'
    )!;
    const card = container.querySelector<HTMLElement>('[data-slot="card"]')!;

    await act(async () => {
      header.dispatchEvent(
        new MouseEvent("pointerdown", {
          clientX: 10,
          clientY: 20,
          bubbles: true,
        })
      );
    });
    expect(header.style.cursor).toBe("grabbing");

    await act(async () => {
      window.dispatchEvent(
        new MouseEvent("pointermove", {
          clientX: 50,
          clientY: 60,
          bubbles: true,
        })
      );
    });
    expect(card.style.left).toBe("80px");
    expect(card.style.top).toBe("90px");

    await act(async () => {
      window.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    });
    expect(header.style.cursor).toBe("grab");
    expect(overlayStateMocks.writeOverlayState).toHaveBeenLastCalledWith({
      position: { x: 80, y: 90 },
      minimized: false,
      hidden: false,
    });
  });

  it("collection checkbox の複数選択を一覧順 queue として開始する", async () => {
    Object.assign(runner, {
      collections: [
        {
          id: "first",
          name: "First",
          status: "ready",
          pattern_count: 1,
          downloaded_count: 0,
        },
        {
          id: "second",
          name: "Second",
          status: "ready",
          pattern_count: 1,
          downloaded_count: 0,
        },
      ],
      selectedCollectionId: "first",
      entries: [
        { name: "pattern", style: "ambient", lyrics: "[Instrumental]" },
      ],
      itemStates: ["idle"],
      canRun: true,
    });
    await act(async () => root.render(createElement(Overlay)));
    const checkboxes = container.querySelectorAll<HTMLElement>(
      '[data-suno-control="collection-checkbox"]'
    );

    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0].dataset.slot).toBe("checkbox");
    expect(checkboxes[0].getAttribute("aria-checked")).toBe("true");
    await act(async () => checkboxes[1].click());
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('button[data-suno-control="run"]')!
        .click()
    );

    expect(runner.runCollectionQueue).toHaveBeenCalledWith(["first", "second"]);
  });

  it("collection queue の成功/失敗 summary から失敗分だけ再実行する", async () => {
    Object.assign(runner, {
      collectionQueue: {
        version: 1,
        queueId: "queue-summary",
        baseUrl: "http://localhost:7873",
        items: [
          { collectionId: "first", status: "succeeded" },
          {
            collectionId: "second",
            status: "failed",
            message: "download failed",
          },
        ],
        currentIndex: 2,
        status: "completed",
        runMode: "queue",
        regenerateDurationOutliers: true,
        createdAt: 100,
        updatedAt: 200,
      },
    });
    await act(async () => root.render(createElement(Overlay)));
    const summary = container.querySelector<HTMLElement>(
      '[data-suno-control="collection-queue-summary"]'
    )!;

    expect(summary.dataset.variant).toBe("destructive");
    expect(summary.textContent).toContain("first: succeeded");
    expect(summary.textContent).toContain("second: failed — download failed");
    await act(async () =>
      Array.from(summary.querySelectorAll("button"))
        .find((button) => button.textContent?.includes("失敗した"))!
        .click()
    );

    expect(runner.runCollectionQueue).toHaveBeenCalledWith(["second"]);
  });

  it("collection queue の完了 summary を success 色で表示する", async () => {
    Object.assign(runner, {
      collectionQueue: {
        version: 1,
        queueId: "queue-success",
        baseUrl: "http://localhost:7873",
        items: [{ collectionId: "first", status: "succeeded" }],
        currentIndex: 1,
        status: "completed",
        runMode: "queue",
        regenerateDurationOutliers: true,
        createdAt: 100,
        updatedAt: 200,
      },
    });
    await act(async () => root.render(createElement(Overlay)));

    expect(
      container.querySelector<HTMLElement>(
        '[data-suno-control="collection-queue-summary"]'
      )?.dataset.variant
    ).toBe("success");
  });

  it("collection 間の queue 遷移中は入力を固定し Stop だけを有効にする", async () => {
    Object.assign(runner, {
      collectionQueue: {
        version: 1,
        queueId: "queue-transition",
        baseUrl: "http://localhost:7873",
        items: [{ collectionId: "first", status: "pending" }],
        currentIndex: 0,
        status: "running",
        runMode: "serial",
        regenerateDurationOutliers: true,
        createdAt: 100,
        updatedAt: 100,
      },
      isRunning: false,
    });
    await act(async () => root.render(createElement(Overlay)));

    expect(
      container.querySelector<HTMLElement>(
        '[data-suno-control="collection-queue-summary"]'
      )?.dataset.variant
    ).toBe("info");

    expect(
      container.querySelector<HTMLButtonElement>(
        'button[data-suno-control="download-format"]'
      )?.disabled
    ).toBe(true);
    expect(
      container.querySelector<HTMLButtonElement>(
        'button[data-suno-control="stop"]'
      )?.disabled
    ).toBe(false);
  });
});
