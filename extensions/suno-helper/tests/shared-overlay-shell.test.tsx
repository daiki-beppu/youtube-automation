// @vitest-environment jsdom

import { OverlayShell } from "@youtube-automation/ui";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("shared OverlayShell", () => {
  let container: HTMLDivElement;
  let root: Root;
  let toggle: (() => void) | undefined;
  const onStateChange = vi.fn(async () => undefined);
  const subscribeToggle = vi.fn((listener: () => void) => {
    toggle = listener;
    return vi.fn();
  });

  beforeEach(() => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    onStateChange.mockClear();
    subscribeToggle.mockClear();
    toggle = undefined;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  async function renderShell(
    overrides: Partial<Parameters<typeof OverlayShell>[0]> = {}
  ) {
    await act(async () => {
      root.render(
        <OverlayShell
          title="Test Helper"
          initialState={{
            position: { x: 40, y: 50 },
            minimized: false,
            hidden: false,
          }}
          onStateChange={onStateChange}
          subscribeToggle={subscribeToggle}
          {...overrides}
        >
          <div>controls</div>
        </OverlayShell>
      );
    });
  }

  it("hidden 中も購読を保ち、同じ state で再表示できる", async () => {
    await renderShell();
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;

    await act(async () => toggle?.());
    expect(shell.style.display).toBe("none");
    expect(onStateChange).toHaveBeenLastCalledWith({
      position: { x: 40, y: 50 },
      minimized: false,
      hidden: true,
    });

    await act(async () => toggle?.());
    expect(shell.style.display).toBe("block");
    expect(subscribeToggle).toHaveBeenCalledOnce();
  });

  it("handle 内の input 起点では drag を開始しない", async () => {
    await renderShell({
      title: <input aria-label="editable title" />,
    });
    const handle = container.querySelector<HTMLElement>(
      "[data-overlay-handle]"
    )!;
    const input = container.querySelector<HTMLInputElement>(
      'input[aria-label="editable title"]'
    )!;

    await act(async () => {
      input.dispatchEvent(
        new MouseEvent("pointerdown", {
          clientX: 10,
          clientY: 10,
          bubbles: true,
        })
      );
    });

    expect(handle.style.cursor).toBe("grab");
  });

  it("viewport resize で実寸を使って再 clamp し確定位置を通知する", async () => {
    await renderShell();
    const shell = container.querySelector<HTMLElement>("[data-overlay-shell]")!;
    shell.getBoundingClientRect = vi.fn(
      () => ({ width: 360, height: 120 }) as DOMRect
    );
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 300,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 100,
    });

    await act(async () => window.dispatchEvent(new Event("resize")));

    expect(shell.style.left).toBe("0px");
    expect(shell.style.top).toBe("0px");
    expect(onStateChange).toHaveBeenLastCalledWith({
      position: { x: 0, y: 0 },
      minimized: false,
      hidden: false,
    });
  });
});
