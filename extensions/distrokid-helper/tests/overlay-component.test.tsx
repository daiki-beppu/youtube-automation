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
    return vi.fn();
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
    storageMocks.read.mockClear();
    storageMocks.write.mockClear();
    messagingMocks.toggle = undefined;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(createElement(Overlay)));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  it("共通 shell に既存 App を表示し、最小化 state を保存する", async () => {
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;
    expect(shell.style.left).toBe("40px");
    expect(shell.style.top).toBe("50px");
    expect(shell.textContent).toContain("DistroKid Helper");
    expect(shell.style.getPropertyValue("--overlay-header-background")).toBe(
      "#0073C7"
    );
    expect(shell.style.getPropertyValue("--overlay-header-foreground")).toBe(
      "#FFFFFF"
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
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;

    await act(async () => messagingMocks.toggle?.());
    expect(shell.style.display).toBe("none");
    await act(async () => messagingMocks.toggle?.());
    expect(shell.style.display).toBe("block");
  });
});
