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
  App: () => createElement("div", { "data-community-app": "" }, "app"),
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

describe("Community Overlay", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
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
  });

  it("renders the app in the shared shell and persists minimize state", async () => {
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
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;
    await act(async () => messagingMocks.toggle?.());
    expect(shell.style.display).toBe("none");
    await act(async () => messagingMocks.toggle?.());
    expect(shell.style.display).toBe("block");
  });
});
