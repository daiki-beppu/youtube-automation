// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../entrypoints/popup/App";
import type { ReleasePayload } from "../lib/types";

const BASE_URL = "http://localhost:7873";
const MANIFEST_VERSION = "0.1.9";

const RELEASE_PAYLOAD: ReleasePayload = {
  profile: {
    artist: "Summer Artist",
    language: "en",
    main_genre: "Electronic",
    sub_genre: "House",
    songwriter: { first: "Jane", last: "Doe", middle: null },
    ai_disclosure: {
      enabled: true,
      lyrics: true,
      music: true,
      recording_scope: "full",
      partial_audio_type: null,
      artist_persona: true,
      apply_to_all: true,
    },
    credits: {
      performer_role: "Audio",
      producer_role: "Producer",
    },
  },
  release: {
    album_title: "Summer Vibes",
    tracks: [{ title: "track-01", filename: "track-01.mp3", asset_path: "/distrokid/assets/track-01.mp3" }],
    cover: { filename: "main.png", asset_path: "/distrokid/assets/main.png" },
    release_date: "2026-07-01",
  },
};

vi.mock("wxt/browser", () => ({
  browser: {
    runtime: {
      getManifest: vi.fn(() => ({ version: MANIFEST_VERSION })),
    },
    tabs: {
      query: vi.fn(async () => [{ id: 1 }]),
    },
  },
}));

vi.mock("../lib/storage", () => ({
  serverUrlItem: {
    getValue: vi.fn(async () => ""),
    setValue: vi.fn(async () => undefined),
  },
  readServerSources: vi.fn(async () => [{ id: "localhost-7873", label: "localhost", url: BASE_URL }]),
  rememberServerSource: vi.fn(async () => [{ id: "localhost-7873", label: "localhost", url: BASE_URL }]),
}));

vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn(() => () => undefined),
  sendMessage: vi.fn(async () => ({ ok: true })),
  PHASES: {
    ERROR: "error",
    INJECTING: "injecting",
  },
}));

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function setSelectValue(select: HTMLSelectElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
  if (!setter) {
    throw new Error("HTMLSelectElement.value setter is unavailable");
  }
  setter.call(select, value);
  select.dispatchEvent(new Event("change", { bubbles: true }));
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

describe("DistroKid popup compatibility check", () => {
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

  it("データ取得時に manifest version で /version を先に呼び、非互換警告を表示して release 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          channel_name: "Localhost",
          channel_short: "local",
          hostname: "localhost",
          port: 7873,
          base_url: BASE_URL,
          label: "localhost",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: "0.2.0" }))
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(200, RELEASE_PAYLOAD));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("#server-url")!, BASE_URL);
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain(`拡張を更新してください（拡張 ${MANIFEST_VERSION}`);
      expect(container.textContent).toContain(RELEASE_PAYLOAD.release.album_title);
    });
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/server-info`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(3, `${BASE_URL}/distrokid/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(4, `${BASE_URL}/distrokid/release.json`, { method: "GET" });
  });

  it("旧サーバーの /version 404 は警告なしで release 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(200, RELEASE_PAYLOAD));

    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("#server-url")!, BASE_URL);
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain(RELEASE_PAYLOAD.release.album_title);
    });
    expect(container.textContent).not.toContain("拡張を更新してください");
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/server-info`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(3, `${BASE_URL}/distrokid/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(4, `${BASE_URL}/distrokid/release.json`, { method: "GET" });
  });
});
