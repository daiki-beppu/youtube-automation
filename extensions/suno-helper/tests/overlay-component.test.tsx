// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Overlay } from "../components/Overlay";
import type { ChallengeLogRecord } from "../lib/challenge-log";

const INITIAL_STATE = {
  position: { x: 40, y: 50 },
  minimized: false,
  hidden: false,
};

const messagingMocks = vi.hoisted(() => ({
  onMessage: vi.fn((_name: string, _handler: () => void) => () => undefined),
  sendMessage: vi.fn(async () => ({ version: "0.2.5", matches: true })),
}));

const overlayStateMocks = vi.hoisted(() => ({
  readOverlayState: vi.fn(async () => INITIAL_STATE),
  writeOverlayState: vi.fn(async () => undefined),
}));

const challengeLogMocks = vi.hoisted(() => ({
  readChallengeLog: vi.fn<() => Promise<ChallengeLogRecord[]>>(),
  writeClipboard: vi.fn<(text: string) => Promise<void>>(),
}));

const CHALLENGE_RECORDS: ChallengeLogRecord[] = [
  "preflight",
  "before-create",
  "generation-wait",
  "before-create",
].map((source, index) => ({
  timestamp: 1_800_000_000_000 + index,
  source: source as ChallengeLogRecord["source"],
  runMode: index === 0 ? null : "serial",
  unattended: index === 0,
  entryIndex: index === 0 ? null : index,
  total: index === 0 ? null : 4,
  challengeLevel: index,
  recentCreateCount: index,
  runCreateCount: index,
  lastCreateIntervalMs: index === 0 ? null : 6000,
  appliedDelayMs: index * 15_000,
  inflightRequestCount: index,
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
  discardCollectionQueue: vi.fn(async () => undefined),
  entries: [],
  itemStates: [],
  status: "待機中",
  phase: "idle",
  isError: false,
  compatibilityWarning: "",
  canRun: false,
  isRunning: false,
  completionSoundSettings: { enabled: true },
  setCompletionSoundEnabled: vi.fn(),
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
vi.mock("../lib/overlay-storage", () => ({
  readOverlayState: overlayStateMocks.readOverlayState,
  writeOverlayState: overlayStateMocks.writeOverlayState,
}));
vi.mock("../lib/challenge-log", () => ({
  readChallengeLog: challengeLogMocks.readChallengeLog,
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

  async function rerenderOverlay(): Promise<void> {
    await act(async () => root.unmount());
    container.innerHTML = "";
    root = createRoot(container);
    await act(async () => {
      root.render(createElement(Overlay));
    });
  }

  async function expectReloadRequired(): Promise<void> {
    await waitFor(() => {
      expect(container.querySelector('[data-slot="card"]')).toBeNull();
      expect(
        container.querySelector('[data-suno-control="reload-required"]')
      ).not.toBeNull();
      expect(
        container.querySelector('[data-suno-control="reload-tab"]')?.textContent
      ).toContain("タブを再読み込み");
    });
  }

  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("browser", {
      runtime: { getManifest: vi.fn(() => ({ version: "0.2.5" })) },
    });
    messagingMocks.sendMessage.mockClear();
    messagingMocks.onMessage.mockClear();
    overlayStateMocks.readOverlayState.mockClear();
    overlayStateMocks.writeOverlayState.mockClear();
    challengeLogMocks.readChallengeLog.mockReset();
    challengeLogMocks.readChallengeLog.mockResolvedValue(CHALLENGE_RECORDS);
    challengeLogMocks.writeClipboard.mockReset();
    challengeLogMocks.writeClipboard.mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: challengeLogMocks.writeClipboard },
    });
    Object.assign(runner, {
      collections: [],
      selectedCollectionId: "",
      entries: [],
      itemStates: [],
      canRun: false,
      collectionQueue: null,
    });
    runner.runCollectionQueue.mockClear();
    runner.resumeCollectionQueue.mockClear();
    runner.discardCollectionQueue.mockClear();
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
    expect(card.style.getPropertyValue("--overlay-header-background")).toBe(
      "oklch(0.753 0.2067 57.6 / 96.4%)"
    );
    expect(card.style.getPropertyValue("--overlay-header-foreground")).toBe(
      "oklch(0.205 0 0)"
    );
    expect(card.style.getPropertyValue("--primary")).toBe(
      "oklch(0.753 0.2067 57.6 / 96.4%)"
    );
    expect(card.style.getPropertyValue("--primary-foreground")).toBe(
      "oklch(0.205 0 0)"
    );
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

  it("challenge履歴を総件数と直近5件で表示する", async () => {
    const sixRecords = [
      ...CHALLENGE_RECORDS,
      { ...CHALLENGE_RECORDS[0], timestamp: 1_800_000_000_004 },
      { ...CHALLENGE_RECORDS[1], timestamp: 1_800_000_000_005 },
    ];
    challengeLogMocks.readChallengeLog.mockResolvedValueOnce(sixRecords);
    await rerenderOverlay();

    await waitFor(() => {
      expect(
        container.querySelector('[data-suno-control="challenge-log-count"]')
          ?.textContent
      ).toContain("6件");
    });
    const records = container.querySelectorAll(
      '[data-suno-control="challenge-log-record"]'
    );

    expect(records).toHaveLength(5);
    expect(records[0].textContent).toContain("before-create");
    expect(records[4].textContent).toContain("before-create");
    expect(records[4].textContent).not.toContain("preflight");
  });

  it("toggleで開くたびにchallenge履歴を再読込し、表示とexportを更新する", async () => {
    await waitFor(() =>
      expect(
        container.querySelector('[data-suno-control="challenge-log-count"]')
          ?.textContent
      ).toContain("4件")
    );
    const toggle = messagingMocks.onMessage.mock.calls.find(
      ([name]) => name === "toggleOverlay"
    )?.[1];
    expect(toggle).toBeTypeOf("function");

    await act(async () => toggle?.());

    const tamperedRecord = {
      ...CHALLENGE_RECORDS[0],
      timestamp: 1_800_000_000_004,
      source: "generation-wait" as const,
      secret: "must-not-leak",
    } as ChallengeLogRecord;
    challengeLogMocks.readChallengeLog.mockResolvedValue([
      ...CHALLENGE_RECORDS,
      tamperedRecord,
    ]);
    await act(async () => toggle?.());

    await waitFor(() =>
      expect(
        container.querySelector('[data-suno-control="challenge-log-count"]')
          ?.textContent
      ).toContain("5件")
    );
    expect(
      container.querySelector('[data-suno-control="challenge-log-record"]')
        ?.textContent
    ).toContain("generation-wait");
    expect(container.textContent).not.toContain("must-not-leak");

    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(
          '[data-suno-control="copy-challenge-log"]'
        )!
        .click()
    );
    const exported = JSON.parse(
      challengeLogMocks.writeClipboard.mock.calls[0][0]
    ) as Array<Record<string, unknown>>;
    expect(exported).toHaveLength(5);
    expect(Object.keys(exported[4]).sort()).toEqual(
      [
        "appliedDelayMs",
        "challengeLevel",
        "entryIndex",
        "inflightRequestCount",
        "lastCreateIntervalMs",
        "recentCreateCount",
        "runCreateCount",
        "runMode",
        "source",
        "timestamp",
        "total",
        "unattended",
      ].sort()
    );
    expect(exported[4]).not.toHaveProperty("secret");
  });

  it("challenge履歴の全件を安全なJSONとしてclipboardへコピーする", async () => {
    await waitFor(() =>
      expect(
        container.querySelector<HTMLButtonElement>(
          '[data-suno-control="copy-challenge-log"]'
        )?.disabled
      ).toBe(false)
    );

    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(
          '[data-suno-control="copy-challenge-log"]'
        )!
        .click()
    );

    expect(challengeLogMocks.writeClipboard).toHaveBeenCalledOnce();
    expect(
      JSON.parse(challengeLogMocks.writeClipboard.mock.calls[0][0])
    ).toEqual(CHALLENGE_RECORDS);
    expect(
      container.querySelector('[data-suno-control="challenge-log-status"]')
        ?.textContent
    ).toContain("コピーしました");
  });

  it("challenge履歴が空なら空状態を表示してcopyを無効化する", async () => {
    challengeLogMocks.readChallengeLog.mockResolvedValueOnce([]);

    await rerenderOverlay();

    await waitFor(() =>
      expect(
        container.querySelector('[data-suno-control="challenge-log-status"]')
          ?.textContent
      ).toContain("記録はありません")
    );
    expect(
      container.querySelector<HTMLButtonElement>(
        '[data-suno-control="copy-challenge-log"]'
      )?.disabled
    ).toBe(true);
    expect(container.querySelector('[data-slot="card"]')).not.toBeNull();
    expect(
      container.querySelector('[data-suno-helper="control-panel"]')
    ).not.toBeNull();
  });

  it("challenge履歴のcopy失敗を通知して既存overlayを維持する", async () => {
    challengeLogMocks.writeClipboard.mockRejectedValueOnce(
      new Error("clipboard unavailable")
    );
    await waitFor(() =>
      expect(
        container.querySelector<HTMLButtonElement>(
          '[data-suno-control="copy-challenge-log"]'
        )?.disabled
      ).toBe(false)
    );

    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(
          '[data-suno-control="copy-challenge-log"]'
        )!
        .click()
    );

    expect(
      container.querySelector('[data-suno-control="challenge-log-error"]')
        ?.textContent
    ).toContain("コピーできませんでした");
    expect(container.querySelector('[data-slot="card"]')).not.toBeNull();
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

  it("paused queue は確認後だけ破棄し、戻ると再開操作を維持する", async () => {
    Object.assign(runner, {
      collectionQueue: {
        version: 1,
        queueId: "queue-paused",
        baseUrl: "http://localhost:7873",
        items: [{ collectionId: "first", status: "pending" }],
        currentIndex: 0,
        status: "paused",
        runMode: "serial",
        regenerateDurationOutliers: true,
        createdAt: 100,
        updatedAt: 200,
      },
    });
    await act(async () => root.render(createElement(Overlay)));

    const close = container.querySelector<HTMLButtonElement>(
      'button[data-suno-control="collection-queue-dismiss"]'
    )!;
    expect(close.getAttribute("aria-label")).toContain("停止中");
    await act(async () => close.click());

    const confirmation = container.querySelector<HTMLElement>(
      '[data-suno-control="collection-queue-discard-confirmation"]'
    )!;
    expect(confirmation.textContent).toContain(
      "未完了の collection queue を破棄しますか？"
    );
    expect(runner.discardCollectionQueue).not.toHaveBeenCalled();
    expect(
      Array.from(confirmation.querySelectorAll("button")).map(
        (button) => button.textContent
      )
    ).toEqual(["戻る", "破棄"]);

    await act(async () => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
      );
    });
    await waitFor(() =>
      expect(confirmation.hasAttribute("data-closed")).toBe(true)
    );
    expect(document.activeElement).toBe(close);

    await act(async () => close.click());
    const reopenedConfirmation = container.querySelector<HTMLElement>(
      '[data-suno-control="collection-queue-discard-confirmation"]'
    )!;

    await act(async () =>
      Array.from(reopenedConfirmation.querySelectorAll("button"))
        .find((button) => button.textContent === "戻る")!
        .click()
    );
    expect(
      Array.from(container.querySelectorAll("button")).some(
        (button) => button.textContent === "Queue を再開"
      )
    ).toBe(true);

    await act(async () => close.click());
    await act(async () =>
      Array.from(container.querySelectorAll("button"))
        .find((button) => button.textContent === "破棄")!
        .click()
    );
    expect(runner.discardCollectionQueue).toHaveBeenCalledOnce();
    expect(runner.resumeCollectionQueue).not.toHaveBeenCalled();
  });

  it("completed queue の Close は確認なしで即時破棄する", async () => {
    Object.assign(runner, {
      collectionQueue: {
        version: 1,
        queueId: "queue-completed",
        baseUrl: "http://localhost:7873",
        items: [{ collectionId: "first", status: "succeeded" }],
        currentIndex: 1,
        status: "completed",
        runMode: "serial",
        regenerateDurationOutliers: true,
        createdAt: 100,
        updatedAt: 200,
      },
    });
    await act(async () => root.render(createElement(Overlay)));

    const close = container.querySelector<HTMLButtonElement>(
      'button[data-suno-control="collection-queue-dismiss"]'
    )!;
    expect(close.getAttribute("aria-label")).toContain("完了した");
    await act(async () => close.click());

    expect(runner.discardCollectionQueue).toHaveBeenCalledOnce();
    expect(
      container.querySelector(
        '[data-suno-control="collection-queue-discard-confirmation"]'
      )
    ).toBeNull();
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
      container.querySelector(
        'button[data-suno-control="collection-queue-dismiss"]'
      )
    ).toBeNull();

    expect(
      container.querySelector<HTMLButtonElement>(
        'button[data-suno-control="stop"]'
      )?.disabled
    ).toBe(false);
  });

  // REQ-2918-01: initialization/persistence failures replace the shell with reload UI.
  it("version handshake mismatch では shell を隠して再読み込みを案内する", async () => {
    messagingMocks.sendMessage.mockResolvedValueOnce({
      version: "0.2.4",
      matches: false,
    });

    await rerenderOverlay();

    await expectReloadRequired();
  });

  it("version handshake reject では shell を隠して再読み込みを案内する", async () => {
    messagingMocks.sendMessage.mockRejectedValueOnce(
      new Error("Extension context invalidated.")
    );

    await rerenderOverlay();

    await expectReloadRequired();
  });

  it("overlay state read reject では shell を隠して再読み込みを案内する", async () => {
    overlayStateMocks.readOverlayState.mockRejectedValueOnce(
      new Error("storage unavailable")
    );

    await rerenderOverlay();

    await expectReloadRequired();
  });

  it("overlay state write reject では shell を隠して再読み込みを案内する", async () => {
    overlayStateMocks.writeOverlayState.mockRejectedValueOnce(
      new Error("storage unavailable")
    );

    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('button[aria-label="最小化"]')!
        .click()
    );

    await expectReloadRequired();
  });
});
