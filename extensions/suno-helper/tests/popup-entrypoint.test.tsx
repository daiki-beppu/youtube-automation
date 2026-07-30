// @vitest-environment jsdom

import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/App", async () => {
  const { createElement } = await import("react");
  return {
    App: () =>
      createElement("div", { "data-suno-popup-app": "mounted" }, "Suno App"),
  };
});

// REQ-2919-01: popup boot fails loud without #root and mounts App with it.
describe("popup entrypoint", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    document.body.innerHTML = "";
  });

  afterEach(() => {
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
  });

  it("root が欠落していると既定エラーで fail loud する", async () => {
    await expect(import("../entrypoints/popup/main")).rejects.toThrow(
      "popup root 要素が見つかりません。"
    );
  });

  it("root があると App を描画する", async () => {
    document.body.innerHTML = '<div id="root"></div>';

    await act(async () => {
      await import("../entrypoints/popup/main");
    });

    expect(
      document.querySelector('[data-suno-popup-app="mounted"]')?.textContent
    ).toBe("Suno App");
  });
});
