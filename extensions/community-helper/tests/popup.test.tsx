// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../components/App";
import { sendMessage } from "../lib/messaging";

vi.mock("wxt/browser", () => ({
  browser: {
    runtime: { getManifest: () => ({ version: "0.1.0" }) },
  },
}));

vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn(() => () => undefined),
  sendMessage: vi.fn(async () => undefined),
}));

describe("community-helper app", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
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
});
