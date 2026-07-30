// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COMMUNITY_PHASE } from "../../shared/constants";
import { App } from "../components/App";
import { onMessage, sendMessage } from "../lib/messaging";

const messaging = vi.hoisted(() => ({
  listeners: new Map<string, (message: { data: unknown }) => void>(),
  unsubscribers: [] as Array<ReturnType<typeof vi.fn>>,
}));

vi.mock("wxt/browser", () => ({
  browser: {
    runtime: { getManifest: () => ({ version: "0.1.0" }) },
  },
}));

vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn(
    (type: string, listener: (message: { data: unknown }) => void) => {
      messaging.listeners.set(type, listener);
      const unsubscribe = vi.fn();
      messaging.unsubscribers.push(unsubscribe);
      return unsubscribe;
    }
  ),
  sendMessage: vi.fn(async () => undefined),
}));

function changeInput(input: HTMLInputElement, value: string): void {
  const valueSetter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value"
  )?.set;
  valueSetter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("community-helper app", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    messaging.listeners.clear();
    messaging.unsubscribers.length = 0;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(<App />));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  it("renders server URL, Start and exactly three progress rows", () => {
    expect(container.querySelector('input[name="serverUrl"]')).not.toBeNull();
    expect(container.querySelector('[data-slot="button"]')?.textContent).toBe(
      "Start"
    );
    expect(
      container.querySelectorAll('[data-testid="progress-row"]')
    ).toHaveLength(3);
    expect(container.querySelectorAll('[data-slot="card"]')).toHaveLength(3);
  });

  it("checks /version before relaying run", async () => {
    vi.mocked(sendMessage).mockResolvedValueOnce({
      status: "compatible",
      serverVersion: "0.1.0",
      minExtensionVersion: "0.1.0",
      extensionVersion: "0.1.0",
    });

    await act(async () => {
      container.querySelector("button")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(sendMessage).toHaveBeenNthCalledWith(1, "checkCompatibility", {
      baseUrl: "http://youtube-automation.localhost:7873",
      extensionVersion: "0.1.0",
    });
    expect(sendMessage).toHaveBeenNthCalledWith(2, "run", {
      baseUrl: "http://youtube-automation.localhost:7873",
    });
  });

  it("shows an error and does not run when the server is down", async () => {
    vi.mocked(sendMessage).mockResolvedValueOnce({
      status: "error",
      message: "Failed to fetch",
    });

    await act(async () => {
      container.querySelector("button")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Failed to fetch"
    );
    expect(
      container.querySelector('[role="alert"]')?.getAttribute("data-variant")
    ).toBe("destructive");
    expect(sendMessage).not.toHaveBeenCalledWith("run", expect.anything());
  });

  it("shows an error and does not run on a version mismatch", async () => {
    vi.mocked(sendMessage).mockResolvedValueOnce({
      status: "incompatible",
      serverVersion: "1.0.0",
      minExtensionVersion: "0.2.0",
      extensionVersion: "0.1.0",
    });

    await act(async () => {
      container.querySelector("button")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "互換性がありません"
    );
    expect(sendMessage).not.toHaveBeenCalledWith("run", expect.anything());
  });

  it("rejects an empty URL before compatibility or run side effects", async () => {
    const input = container.querySelector<HTMLInputElement>(
      'input[name="serverUrl"]'
    )!;
    await act(async () => {
      changeInput(input, "   ");
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
      await Promise.resolve();
    });

    expect(sendMessage).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "サーバー URL を入力してください"
    );
    expect(container.querySelector<HTMLButtonElement>("button")!.disabled).toBe(
      false
    );
  });

  it("rejects an unknown compatibility status without relaying run", async () => {
    vi.mocked(sendMessage).mockResolvedValueOnce({
      status: "future-status",
    } as never);

    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "/version を確認できません"
    );
    expect(sendMessage).not.toHaveBeenCalledWith("run", expect.anything());
  });

  it("normalizes the run URL and releases busy with an error when stop relay rejects", async () => {
    vi.mocked(sendMessage)
      .mockResolvedValueOnce({
        status: "compatible",
        serverVersion: "0.1.0",
        minExtensionVersion: "0.1.0",
        extensionVersion: "0.1.0",
      })
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("stop relay unavailable"));
    const input = container.querySelector<HTMLInputElement>(
      'input[name="serverUrl"]'
    )!;
    await act(async () => {
      changeInput(input, "http://localhost:7873/");
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    const buttons = container.querySelectorAll<HTMLButtonElement>("button");
    expect(buttons[0].disabled).toBe(true);
    expect(sendMessage).toHaveBeenNthCalledWith(2, "run", {
      baseUrl: "http://localhost:7873",
    });

    await act(async () => {
      buttons[1].click();
      await Promise.resolve();
    });

    expect(sendMessage).toHaveBeenLastCalledWith("stop");
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "stop relay unavailable"
    );
    expect(buttons[0].disabled).toBe(false);
    expect(buttons[1].disabled).toBe(true);
  });

  it("applies progress and error messages and unsubscribes both listeners", async () => {
    vi.mocked(sendMessage)
      .mockResolvedValueOnce({
        status: "compatible",
        serverVersion: "0.1.0",
        minExtensionVersion: "0.1.0",
        extensionVersion: "0.1.0",
      })
      .mockResolvedValueOnce(undefined);
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      messaging.listeners.get("progress")?.({
        data: {
          index: 2,
          total: 3,
          phase: COMMUNITY_PHASE.DONE,
          message: "投稿完了",
        },
      });
    });
    expect(
      container.querySelectorAll<HTMLElement>('[data-testid="progress-row"]')[2]
        .textContent
    ).toContain("投稿完了");
    expect(container.querySelector<HTMLButtonElement>("button")!.disabled).toBe(
      false
    );

    await act(async () => {
      messaging.listeners.get("error")?.({
        data: { message: "content failed" },
      });
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "content failed"
    );

    expect(onMessage).toHaveBeenCalledTimes(2);
    await act(async () => root.unmount());
    expect(messaging.unsubscribers).toHaveLength(2);
    for (const unsubscribe of messaging.unsubscribers) {
      expect(unsubscribe).toHaveBeenCalledOnce();
    }
    root = createRoot(container);
  });
});
