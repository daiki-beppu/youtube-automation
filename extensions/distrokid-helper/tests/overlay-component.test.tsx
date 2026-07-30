// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Overlay } from "../components/Overlay";

const initialState = {
  position: { x: 40, y: 50 },
  minimized: false,
  hidden: false,
};

const messagingMocks = vi.hoisted(() => ({
  toggle: undefined as (() => void) | undefined,
  unsubscribe: vi.fn(),
}));
const storageMocks = vi.hoisted(() => ({
  read: vi.fn(async () => initialState),
  write: vi.fn(async () => undefined),
}));

vi.mock("../components/App", () => ({
  App: () => createElement("div", { "data-distrokid-app": "" }, "app"),
}));
vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn((_type: string, listener: () => void) => {
    messagingMocks.toggle = listener;
    return messagingMocks.unsubscribe;
  }),
}));
vi.mock("../lib/overlay-storage", () => ({
  readOverlayState: storageMocks.read,
  writeOverlayState: storageMocks.write,
}));

describe("DistroKid Overlay", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    storageMocks.read.mockReset().mockResolvedValue(initialState);
    storageMocks.write.mockReset().mockResolvedValue(undefined);
    messagingMocks.toggle = undefined;
    messagingMocks.unsubscribe.mockClear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  async function renderOverlay(): Promise<void> {
    await act(async () => root.render(createElement(Overlay)));
  }

  afterEach(() => {
    act(() => root.unmount());
    if (messagingMocks.toggle) {
      expect(messagingMocks.unsubscribe).toHaveBeenCalledOnce();
    }
    container.remove();
    vi.unstubAllGlobals();
  });

  it("共通 shell に既存 App を表示し、最小化 state を保存する", async () => {
    await renderOverlay();
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;
    expect(shell.style.left).toBe("40px");
    expect(shell.style.top).toBe("50px");
    expect(shell.textContent).toContain("DistroKid Helper");
    expect(shell.style.getPropertyValue("--overlay-header-background")).toBe(
      "oklch(0.8703 0.1962 116.38)"
    );
    expect(shell.style.getPropertyValue("--overlay-header-foreground")).toBe(
      "oklch(0.205 0 0)"
    );
    expect(shell.style.getPropertyValue("--primary")).toBe(
      "oklch(0.8703 0.1962 116.38)"
    );
    expect(shell.style.getPropertyValue("--primary-foreground")).toBe(
      "oklch(0.205 0 0)"
    );
    expect(container.querySelector("[data-distrokid-app]")).not.toBeNull();

    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('button[aria-label="最小化"]')!
        .click()
    );

    expect(storageMocks.write).toHaveBeenLastCalledWith({
      ...initialState,
      minimized: true,
    });
    expect(
      container.querySelector<HTMLElement>("[data-overlay-content]")!.style
        .display
    ).toBe("none");
  });

  it("hidden 中も action toggle listener を保って再表示する", async () => {
    await renderOverlay();
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;

    await act(async () => messagingMocks.toggle?.());
    expect(shell.style.display).toBe("none");
    await act(async () => messagingMocks.toggle?.());
    expect(shell.style.display).toBe("block");
  });

  it("initial storage read reject で再読み込み UI を表示する", async () => {
    storageMocks.read.mockRejectedValueOnce(new Error("storage unavailable"));

    await renderOverlay();

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "再読み込みが必要です"
    );
    expect(container.querySelector("[data-overlay-shell]")).toBeNull();
    expect(messagingMocks.toggle).toBeUndefined();
  });

  it("state write reject を onError 経由で再読み込み UI に変換する", async () => {
    storageMocks.write.mockRejectedValueOnce(new Error("write unavailable"));
    await renderOverlay();

    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('button[aria-label="最小化"]')!
        .click();
      await Promise.resolve();
    });

    expect(storageMocks.write).toHaveBeenCalledOnce();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "再読み込みが必要です"
    );
  });
});
