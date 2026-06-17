// @vitest-environment jsdom

import { act } from "react";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../components/App";

const BASE_URL = "http://localhost:7873";
const MANIFEST_VERSION = "0.1.9";

vi.mock("wxt/browser", () => ({
  browser: {
    runtime: {
      getManifest: vi.fn(() => ({ version: MANIFEST_VERSION })),
    },
  },
}));

vi.mock("../lib/storage", () => ({
  serverUrlItem: {
    getValue: vi.fn(async () => ""),
    setValue: vi.fn(async () => undefined),
  },
}));

vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn(() => () => undefined),
  sendMessage: vi.fn(async () => {
    throw new Error("runner unavailable");
  }),
}));

vi.mock("../lib/preset-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/preset-state")>("../lib/preset-state");
  return {
    ...actual,
    readSpeedPresetId: vi.fn(async () => actual.DEFAULT_SPEED_PRESET_ID),
    writeSpeedPresetId: vi.fn(async () => undefined),
  };
});

vi.mock("../lib/resume-state", async () => {
  const actual = await vi.importActual<typeof import("../lib/resume-state")>("../lib/resume-state");
  return {
    ...actual,
    readResumeState: vi.fn(async () => null),
  };
});

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (!setter) {
    throw new Error("HTMLInputElement.value setter is unavailable");
  }
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

async function waitFor(assertion: () => void): Promise<void> {
  for (let i = 0; i < 20; i += 1) {
    try {
      assertion();
      return;
    } catch (error) {
      if (i === 19) {
        throw error;
      }
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }
  }
}

describe("Suno popup compatibility check", () => {
  let root: Root;
  let container: HTMLDivElement;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      root.render(createElement(App));
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("データ取得時に manifest version で /version を先に呼び、非互換警告を表示して prompts 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: "0.2.0" }))
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain(`拡張を更新してください（拡張 ${MANIFEST_VERSION}`);
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/suno/prompts.json`);
  });

  it("旧サーバーの /version 404 は警告なしで prompts 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(container.textContent).not.toContain("拡張を更新してください");
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/suno/prompts.json`);
  });
});
