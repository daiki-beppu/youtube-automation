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
  App: () => createElement("div", { "data-community-app": "" }, "app"),
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

describe("Community Overlay", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
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
  });

  it("renders the app in the shared shell and persists minimize state", async () => {
    await renderOverlay();
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;
    expect(shell.style.left).toBe("40px");
    expect(shell.style.top).toBe("50px");
    expect(shell.textContent).toContain("Community Helper");
    expect(shell.style.getPropertyValue("--overlay-header-background")).toBe(
      "#C90028"
    );
    expect(shell.style.getPropertyValue("--overlay-header-foreground")).toBe(
      "#FFFFFF"
    );
    expect(shell.style.getPropertyValue("--primary")).toBe("");
    expect(shell.style.getPropertyValue("--primary-foreground")).toBe("");
    expect(container.querySelector("[data-community-app]")).not.toBeNull();

    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('button[aria-label="最小化"]')!
        .click()
    );

    expect(storageMocks.write).toHaveBeenLastCalledWith({
      ...initialState,
      minimized: true,
    });
  });

  it("keeps the action toggle listener alive while hidden", async () => {
    await renderOverlay();
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;
    await act(async () => messagingMocks.toggle?.());
    expect(shell.style.display).toBe("none");
    await act(async () => messagingMocks.toggle?.());
    expect(shell.style.display).toBe("block");
  });

  it("shows reload guidance when initial storage read rejects", async () => {
    storageMocks.read.mockRejectedValueOnce(new Error("storage context lost"));

    await renderOverlay();

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "再読み込みが必要です"
    );
    expect(container.querySelector("[data-overlay-shell]")).toBeNull();
    expect(messagingMocks.toggle).toBeUndefined();
  });

  it("shows reload guidance when state persistence rejects", async () => {
    storageMocks.write.mockRejectedValueOnce(new Error("write failed"));
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
