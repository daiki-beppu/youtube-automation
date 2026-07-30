// @vitest-environment jsdom

import { OverlayShell } from "@youtube-automation/ui";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const INITIAL_STATE = {
  position: { x: 40, y: 50 },
  minimized: false,
  hidden: false,
};

function pointer(type: string, x: number, y: number): PointerEvent {
  return new PointerEvent(type, {
    bubbles: true,
    clientX: x,
    clientY: y,
  });
}

describe("OverlayShell runtime contract", () => {
  let container: HTMLDivElement;
  let root: Root;
  let mounted: boolean;
  let unsubscribe: () => void;

  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1024,
      writable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 768,
      writable: true,
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    mounted = true;
    unsubscribe = vi.fn();
  });

  afterEach(() => {
    if (mounted) act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  async function renderShell({
    title = "Overlay",
    onStateChange = vi.fn(async () => undefined),
    onError,
    width,
    brandColors,
    initialState = INITIAL_STATE,
  }: {
    title?: ReactNode;
    onStateChange?: (state: typeof INITIAL_STATE) => void | Promise<void>;
    onError?: (error: unknown) => void;
    width?: number;
    brandColors?: {
      headerBackground: string;
      headerForeground: string;
      primary?: string;
      primaryForeground?: string;
    };
    initialState?: typeof INITIAL_STATE;
  } = {}): Promise<void> {
    await act(async () =>
      root.render(
        <OverlayShell
          title={title}
          initialState={initialState}
          onStateChange={onStateChange}
          subscribeToggle={() => unsubscribe}
          onError={onError}
          width={width}
          brandColors={brandColors}
        >
          Body
        </OverlayShell>
      )
    );
  }

  it("forwards writer rejection to onError and keeps the subscription cleanup", async () => {
    const failure = new Error("storage write failed");
    const onError = vi.fn();
    const onStateChange = vi.fn(async () => {
      throw failure;
    });
    await renderShell({ onStateChange, onError });

    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('button[aria-label="最小化"]')!
        .click();
      await Promise.resolve();
    });
    expect(onStateChange).toHaveBeenCalledWith({
      ...INITIAL_STATE,
      minimized: true,
    });
    expect(onError).toHaveBeenCalledWith(failure);
    act(() => root.unmount());
    mounted = false;
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("applies custom width and each supplied partial brand CSS variable", async () => {
    await renderShell({
      width: 512,
      brandColors: {
        headerBackground: "#111111",
        headerForeground: "#eeeeee",
        primary: "#ff0000",
      },
    });
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;
    expect(shell.style.width).toBe("512px");
    expect(shell.style.getPropertyValue("--overlay-header-background")).toBe(
      "#111111"
    );
    expect(shell.style.getPropertyValue("--overlay-header-foreground")).toBe(
      "#eeeeee"
    );
    expect(shell.style.getPropertyValue("--primary")).toBe("#ff0000");
    expect(shell.style.getPropertyValue("--primary-foreground")).toBe("");
  });

  it.each([
    ["input", <input aria-label="interactive" key="input" />],
    ["textarea", <textarea aria-label="interactive" key="textarea" />],
    [
      "contenteditable",
      <span contentEditable aria-label="interactive" key="editable">
        edit
      </span>,
    ],
  ])(
    "does not start a drag from an interactive %s target",
    async (_name, title) => {
      const onStateChange = vi.fn(async () => undefined);
      await renderShell({ title, onStateChange });
      const target = container.querySelector<HTMLElement>(
        '[aria-label="interactive"]'
      )!;

      await act(async () => {
        target.dispatchEvent(pointer("pointerdown", 50, 50));
        window.dispatchEvent(pointer("pointermove", 200, 200));
        window.dispatchEvent(pointer("pointerup", 200, 200));
      });

      expect(onStateChange).not.toHaveBeenCalled();
      const shell = container.querySelector<HTMLElement>(
        "[data-overlay-shell]"
      )!;
      expect(shell.style.left).toBe("40px");
      expect(shell.style.top).toBe("50px");
    }
  );

  it("clamps on viewport resize, persists the clamped position, and removes listeners on unmount", async () => {
    const onStateChange = vi.fn(async () => undefined);
    const addListener = vi.spyOn(window, "addEventListener");
    const removeListener = vi.spyOn(window, "removeEventListener");
    await renderShell({
      onStateChange,
      initialState: {
        ...INITIAL_STATE,
        position: { x: 700, y: 500 },
      },
    });
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;
    shell.getBoundingClientRect = () =>
      ({
        x: 700,
        y: 500,
        top: 500,
        left: 700,
        right: 940,
        bottom: 700,
        width: 240,
        height: 200,
        toJSON: () => ({}),
      }) as DOMRect;

    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 300,
      writable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 240,
      writable: true,
    });
    await act(async () => window.dispatchEvent(new Event("resize")));
    expect(shell.style.left).toBe("60px");
    expect(shell.style.top).toBe("40px");
    expect(onStateChange).toHaveBeenLastCalledWith({
      ...INITIAL_STATE,
      position: { x: 60, y: 40 },
    });

    await act(async () => {
      container
        .querySelector<HTMLElement>("[data-overlay-handle]")!
        .dispatchEvent(pointer("pointerdown", 10, 10));
    });
    expect(addListener).toHaveBeenCalledWith(
      "pointermove",
      expect.any(Function)
    );
    expect(addListener).toHaveBeenCalledWith("pointerup", expect.any(Function));
    act(() => root.unmount());
    mounted = false;
    expect(removeListener).toHaveBeenCalledWith(
      "pointermove",
      expect.any(Function)
    );
    expect(removeListener).toHaveBeenCalledWith(
      "pointerup",
      expect.any(Function)
    );
    expect(removeListener).toHaveBeenCalledWith("resize", expect.any(Function));
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
});
