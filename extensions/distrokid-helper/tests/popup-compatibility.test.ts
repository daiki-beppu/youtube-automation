// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../components/App";
import { sendMessage } from "../lib/messaging";
import { migrateServerSourcesStorage, serverUrlItem } from "../lib/storage";
import type { ReleasePayload } from "../lib/types";

const BASE_URL = "http://localhost:7873";
const FALLBACK_URL = "http://localhost:7877";
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
    tracks: [
      {
        title: "track-01",
        filename: "track-01.mp3",
        asset_path: "/distrokid/assets/track-01.mp3",
      },
    ],
    cover: { filename: "main.png", asset_path: "/distrokid/assets/main.png" },
    release_date: "2026-07-01",
  },
};

const SECOND_RELEASE_PAYLOAD: ReleasePayload = {
  ...RELEASE_PAYLOAD,
  release: {
    ...RELEASE_PAYLOAD.release,
    album_title: "Winter Focus",
  },
};

const DISC1 = {
  collection_id: "20260526-coding-focus-collection",
  name: "coding focus",
  disc: "disc1",
  album_title: RELEASE_PAYLOAD.release.album_title,
  track_count: 1,
  released: false,
};

const DISC2 = {
  ...DISC1,
  disc: "disc2",
  album_title: SECOND_RELEASE_PAYLOAD.release.album_title,
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

const legacySourceState = vi.hoisted(() => ({ present: true }));

vi.mock("../lib/storage", () => ({
  serverUrlItem: {
    getValue: vi.fn(async () => ""),
    setValue: vi.fn(async () => undefined),
  },
  migrateServerSourcesStorage: vi.fn(async () => {
    legacySourceState.present = false;
  }),
}));

const discoveryMocks = vi.hoisted(() => ({
  discoverServerSources: vi.fn(async () => [
    {
      id: "youtube-automation-localhost-7873",
      label: "YouTube Automation (default)",
      url: "http://youtube-automation.localhost:7873",
    },
    { id: "abyss-mi", label: "ABYSS MI", url: "http://localhost:7873" },
    {
      id: "localhost-7877",
      label: "localhost fallback 7877",
      url: "http://localhost:7877",
    },
  ]),
}));

vi.mock("../../shared/server-discovery", () => discoveryMocks);

vi.mock("../lib/background-fetch", async () => {
  const { encodeAsset } = await import("../lib/asset-transfer");
  return {
    backgroundFetch: (input: string | URL | Request, init?: RequestInit) =>
      init === undefined ? fetch(input) : fetch(input, init),
    backgroundFetchAsset: async (url: string, filename: string) => {
      const response = await fetch(url, { method: "GET" });
      if (!response.ok)
        throw new Error(`asset fetch failed: HTTP ${response.status}`);
      return encodeAsset(filename, await response.blob());
    },
  };
});

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

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function setSelectValue(select: HTMLSelectElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype,
    "value"
  )?.set;
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
    vi.mocked(serverUrlItem.getValue).mockResolvedValue("");
    vi.mocked(serverUrlItem.setValue).mockResolvedValue(undefined);
    discoveryMocks.discoverServerSources.mockReset().mockResolvedValue([
      {
        id: "youtube-automation-localhost-7873",
        label: "YouTube Automation (default)",
        url: "http://youtube-automation.localhost:7873",
      },
      { id: "abyss-mi", label: "ABYSS MI", url: BASE_URL },
      {
        id: "localhost-7877",
        label: "localhost fallback 7877",
        url: FALLBACK_URL,
      },
    ]);
    legacySourceState.present = true;
    vi.mocked(migrateServerSourcesStorage).mockImplementation(async () => {
      legacySourceState.present = false;
    });
  });

  async function renderApp(): Promise<void> {
    await act(async () => {
      root.render(createElement(App));
    });
  }

  function stubDirModeServer(): void {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/server-info`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/version`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/collections`) {
        return jsonResponse(200, [DISC1, DISC2]);
      }
      if (url.includes(`/${DISC1.disc}/release.json`)) {
        return jsonResponse(200, RELEASE_PAYLOAD);
      }
      if (url.includes(`/${DISC2.disc}/release.json`)) {
        return jsonResponse(200, SECOND_RELEASE_PAYLOAD);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
  }

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("ローカル配信元 option は URL を表示せず、URL value はデータ取得先として維持する", async () => {
    await renderApp();
    const select = container.querySelector<HTMLSelectElement>("#server-url")!;
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[aria-haspopup="listbox"]'
    )!;

    await waitFor(() => {
      expect(select.options).toHaveLength(3);
    });

    expect(
      Array.from(select.options, (option) => ({
        text: option.text,
        value: option.value,
      }))
    ).toEqual([
      {
        text: "YouTube Automation (default) | distrokid-helper",
        value: "http://youtube-automation.localhost:7873",
      },
      { text: "ABYSS MI | distrokid-helper", value: BASE_URL },
      {
        text: "localhost fallback 7877 | distrokid-helper",
        value: FALLBACK_URL,
      },
    ]);
    expect(select.labels?.[0]?.textContent?.trim()).toBe("ローカル配信元");
    expect(select.value).toBe("http://youtube-automation.localhost:7873");
    expect(trigger.dataset.slot).toBe("button");
    expect(Array.from(trigger.classList)).toEqual(
      expect.arrayContaining([
        "border",
        "bg-background",
        "focus-visible:border-ring",
      ])
    );
    expect(select.textContent).not.toContain("http://");
  });

  it("popup 初回表示時に保存 URL から一覧と選択 disc の release を自動取得し、取得ボタンを表示しない", async () => {
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(200, [DISC1, DISC2]))
      .mockResolvedValueOnce(jsonResponse(200, RELEASE_PAYLOAD));

    await renderApp();

    await waitFor(() => {
      expect(container.textContent).toContain(
        RELEASE_PAYLOAD.release.album_title
      );
      expect(container.textContent).toContain(
        RELEASE_PAYLOAD.release.cover?.filename
      );
    });
    expect(container.textContent).not.toContain("データ取得");
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/distrokid/collections`
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      `${BASE_URL}/collections/${DISC1.collection_id}/distrokid/${DISC1.disc}/release.json`,
      { method: "GET" }
    );
    const collectionSelect = container.querySelector<HTMLSelectElement>(
      "select:not(#server-url)"
    )!;
    const collectionTrigger = container.querySelector<HTMLButtonElement>(
      '[data-distrokid-control="collection-select"]'
    )!;
    expect(collectionSelect.value).toBe("0");
    expect(collectionTrigger.getAttribute("aria-labelledby")).toBe(
      "collection-select-label"
    );
    expect(collectionTrigger.dataset.slot).toBe("select-trigger");
    expect(collectionTrigger.getAttribute("role")).toBe("combobox");
    expect(Array.from(collectionTrigger.classList)).toEqual(
      expect.arrayContaining([
        "border-input",
        "bg-transparent",
        "focus-visible:border-ring",
      ])
    );
    const injectButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "フォーム一括入力"
    );
    expect(injectButton?.disabled).toBe(false);
    expect(injectButton?.dataset.slot).toBe("button");
    expect(injectButton?.dataset.variant).toBe("default");
    const stopButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "停止"
    );
    expect(stopButton?.disabled).toBe(true);
    expect(stopButton?.dataset.slot).toBe("button");
    expect(stopButton?.dataset.variant).toBe("outline");
  });

  it("全 disc が配信済みなら選択肢を表示せず all-released 状態を案内する", async () => {
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/server-info` || url === `${BASE_URL}/version`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/collections`) {
        return jsonResponse(200, [{ ...DISC1, released: true }]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    await renderApp();

    await waitFor(() => {
      expect(container.textContent).toContain("未配信の disc はありません。");
    });
    expect(container.querySelector("select:not(#server-url)")).toBeNull();
    const injectButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "フォーム一括入力"
    );
    expect(injectButton?.disabled).toBe(true);
  });

  it("配信元選択時に manifest version で /version を先に呼び、非互換警告を表示して release 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          channel_name: "Localhost",
          channel_short: "local",
          hostname: "localhost",
          port: 7873,
          base_url: BASE_URL,
          label: "localhost",
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { version: "5.5.7", min_extension_version: "0.2.0" })
      )
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(200, RELEASE_PAYLOAD));

    await renderApp();

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("#server-url")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain(
        `拡張を更新してください（拡張 ${MANIFEST_VERSION}`
      );
      expect(container.textContent).toContain(
        RELEASE_PAYLOAD.release.album_title
      );
    });
    expect(
      container.querySelector('[data-slot="card"] [data-slot="card-title"]')
        ?.textContent
    ).toBe(RELEASE_PAYLOAD.release.album_title);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/server-info`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/distrokid/collections`
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      `${BASE_URL}/distrokid/release.json`,
      { method: "GET" }
    );
    expect(serverUrlItem.setValue).toHaveBeenCalledWith(BASE_URL);
  });

  it("旧サーバーの /version 404 は警告なしで release 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(200, RELEASE_PAYLOAD));

    await renderApp();

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("#server-url")!,
        BASE_URL
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain(
        RELEASE_PAYLOAD.release.album_title
      );
    });
    expect(container.textContent).not.toContain("拡張を更新してください");
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/server-info`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/distrokid/collections`
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      `${BASE_URL}/distrokid/release.json`,
      { method: "GET" }
    );
  });

  it("collection 選択時に一覧を最新化し、選択 disc の release へ自動更新する", async () => {
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    stubDirModeServer();
    await renderApp();

    await waitFor(() => {
      expect(container.textContent).toContain(
        RELEASE_PAYLOAD.release.album_title
      );
    });
    const collectionSelect = container.querySelector<HTMLSelectElement>(
      "select:not(#server-url)"
    )!;
    await act(async () => {
      setSelectValue(collectionSelect, "1");
    });

    await waitFor(() => {
      expect(container.textContent).toContain(
        SECOND_RELEASE_PAYLOAD.release.album_title
      );
    });
    expect(
      fetchMock.mock.calls.filter(
        ([url]) => url === `${BASE_URL}/distrokid/collections`
      )
    ).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/collections/${DISC2.collection_id}/distrokid/${DISC2.disc}/release.json`,
      { method: "GET" }
    );
    expect(collectionSelect.value).toBe("1");
  });

  it("注入中は両 selector をロックし、停止ボタンは有効なまま選択変更による取得を開始しない", async () => {
    const injectionStart = deferred<void>();
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    stubDirModeServer();
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type === "injectStart") {
        await injectionStart.promise;
      }
      return undefined;
    });
    await renderApp();

    await waitFor(() => {
      expect(container.textContent).toContain(
        RELEASE_PAYLOAD.release.album_title
      );
    });
    const sourceSelect =
      container.querySelector<HTMLSelectElement>("#server-url")!;
    const collectionSelect = container.querySelector<HTMLSelectElement>(
      "select:not(#server-url)"
    )!;
    const injectButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "フォーム一括入力"
    )!;
    const stopButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "停止"
    )!;
    const sourceTrigger = container.querySelector<HTMLButtonElement>(
      'button[aria-haspopup="listbox"]'
    )!;
    await act(async () => sourceTrigger.click());
    await waitFor(() =>
      expect(container.querySelector('[role="listbox"]')).not.toBeNull()
    );
    const requestCountBeforeChange = fetchMock.mock.calls.length;

    await act(async () => {
      injectButton.click();
    });
    await waitFor(() => {
      expect(sourceSelect.disabled).toBe(true);
      expect(collectionSelect.disabled).toBe(true);
      expect(injectButton.disabled).toBe(true);
      expect(stopButton.disabled).toBe(false);
      expect(container.querySelector('[role="listbox"]')).toBeNull();
    });
    expect(sendMessage).toHaveBeenCalledWith("injectStart", {
      payload: RELEASE_PAYLOAD,
    });
    const discoveryCountDuringInjection =
      discoveryMocks.discoverServerSources.mock.calls.length;

    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"]')!
        .click();
      setSelectValue(sourceSelect, FALLBACK_URL);
      setSelectValue(collectionSelect, "1");
    });
    expect(fetchMock).toHaveBeenCalledTimes(requestCountBeforeChange);
    expect(discoveryMocks.discoverServerSources).toHaveBeenCalledTimes(
      discoveryCountDuringInjection
    );

    await act(async () => {
      stopButton.click();
    });
    expect(sendMessage).toHaveBeenCalledWith("stop");

    await act(async () => {
      injectionStart.resolve();
      await injectionStart.promise;
    });
  });

  it("取得失敗後も配信元 selector は操作可能で、変更すると再取得できる", async () => {
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    fetchMock.mockImplementation(async (url: string) => {
      if (url.startsWith(BASE_URL)) {
        throw new Error("server stopped");
      }
      if (
        url === `${FALLBACK_URL}/server-info` ||
        url === `${FALLBACK_URL}/version` ||
        url === `${FALLBACK_URL}/distrokid/collections`
      ) {
        return jsonResponse(404, {});
      }
      if (url === `${FALLBACK_URL}/distrokid/release.json`) {
        return jsonResponse(200, SECOND_RELEASE_PAYLOAD);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    await renderApp();

    await waitFor(() => {
      expect(container.textContent).toContain("server stopped");
    });
    const sourceSelect =
      container.querySelector<HTMLSelectElement>("#server-url")!;
    expect(sourceSelect.disabled).toBe(false);

    await act(async () => {
      setSelectValue(sourceSelect, FALLBACK_URL);
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        `${FALLBACK_URL}/distrokid/release.json`,
        { method: "GET" }
      );
      expect(container.textContent).toContain(
        SECOND_RELEASE_PAYLOAD.release.album_title
      );
    });
    expect(sourceSelect.disabled).toBe(false);
  });

  it("選択 disc の取得失敗後も collection selector は操作可能で、別 disc へ切り替えられる", async () => {
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/server-info` || url === `${BASE_URL}/version`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/collections`) {
        return jsonResponse(200, [DISC1, DISC2]);
      }
      if (url.includes(`/${DISC1.disc}/release.json`)) {
        throw new Error("disc1 server stopped");
      }
      if (url.includes(`/${DISC2.disc}/release.json`)) {
        return jsonResponse(200, SECOND_RELEASE_PAYLOAD);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    await renderApp();

    await waitFor(() => {
      expect(container.textContent).toContain("disc1 server stopped");
    });
    const collectionSelect = container.querySelector<HTMLSelectElement>(
      "select:not(#server-url)"
    )!;
    expect(collectionSelect.disabled).toBe(false);

    await act(async () => {
      setSelectValue(collectionSelect, "1");
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        SECOND_RELEASE_PAYLOAD.release.album_title
      );
    });
    expect(collectionSelect.disabled).toBe(false);
  });

  it("collection 再選択時に一覧取得が失敗してもエラーを表示し、一覧と選択を維持する", async () => {
    let collectionsRequestCount = 0;
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/server-info` || url === `${BASE_URL}/version`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/collections`) {
        collectionsRequestCount += 1;
        if (collectionsRequestCount === 2) {
          throw new Error("collections server stopped");
        }
        return jsonResponse(200, [DISC1, DISC2]);
      }
      if (url.includes(`/${DISC1.disc}/release.json`)) {
        return jsonResponse(200, RELEASE_PAYLOAD);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    await renderApp();

    await waitFor(() => {
      expect(container.textContent).toContain(
        RELEASE_PAYLOAD.release.album_title
      );
    });
    const sourceSelect =
      container.querySelector<HTMLSelectElement>("#server-url")!;
    const collectionSelect = container.querySelector<HTMLSelectElement>(
      "select:not(#server-url)"
    )!;

    await act(async () => {
      setSelectValue(collectionSelect, "1");
    });
    await waitFor(() => {
      expect(container.textContent).toContain("collections server stopped");
    });

    expect(
      container.querySelector<HTMLSelectElement>("select:not(#server-url)")
    ).toBe(collectionSelect);
    expect(collectionSelect.options).toHaveLength(2);
    expect(collectionSelect.value).toBe("1");
    expect(collectionSelect.disabled).toBe(false);
    expect(sourceSelect.disabled).toBe(false);
  });

  it("遅い旧 release 応答が後から完了しても最新 disc の payload と DOM を維持する", async () => {
    const firstRelease = deferred<Response>();
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/server-info` || url === `${BASE_URL}/version`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/collections`) {
        return jsonResponse(200, [DISC1, DISC2]);
      }
      if (url.includes(`/${DISC1.disc}/release.json`)) {
        return firstRelease.promise;
      }
      if (url.includes(`/${DISC2.disc}/release.json`)) {
        return jsonResponse(200, SECOND_RELEASE_PAYLOAD);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    await renderApp();

    await waitFor(() => {
      expect(container.querySelector("select:not(#server-url)")).not.toBeNull();
    });
    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("select:not(#server-url)")!,
        "1"
      );
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        SECOND_RELEASE_PAYLOAD.release.album_title
      );
    });

    await act(async () => {
      firstRelease.resolve(jsonResponse(200, RELEASE_PAYLOAD));
      await firstRelease.promise;
    });
    expect(container.textContent).toContain(
      SECOND_RELEASE_PAYLOAD.release.album_title
    );
    expect(container.textContent).not.toContain(
      `アルバム名${RELEASE_PAYLOAD.release.album_title}`
    );
    expect(
      container.querySelector<HTMLSelectElement>("select:not(#server-url)")!
        .value
    ).toBe("1");
  });

  it("遅い初期一覧が後から完了しても最新配信元の URL・payload・DOM を維持する", async () => {
    const initialCollections = deferred<Response>();
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/server-info` || url === `${BASE_URL}/version`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/collections`) {
        return initialCollections.promise;
      }
      if (
        url === `${FALLBACK_URL}/server-info` ||
        url === `${FALLBACK_URL}/version`
      ) {
        return jsonResponse(404, {});
      }
      if (url === `${FALLBACK_URL}/distrokid/collections`) {
        return jsonResponse(404, {});
      }
      if (url === `${FALLBACK_URL}/distrokid/release.json`) {
        return jsonResponse(200, SECOND_RELEASE_PAYLOAD);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    await renderApp();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        `${BASE_URL}/distrokid/collections`
      );
    });

    const sourceSelect =
      container.querySelector<HTMLSelectElement>("#server-url")!;
    await act(async () => {
      setSelectValue(sourceSelect, FALLBACK_URL);
    });
    await waitFor(() => {
      expect(container.textContent).toContain(
        SECOND_RELEASE_PAYLOAD.release.album_title
      );
    });

    await act(async () => {
      initialCollections.resolve(jsonResponse(200, [DISC1, DISC2]));
      await initialCollections.promise;
    });
    expect(sourceSelect.value).toBe(FALLBACK_URL);
    expect(container.textContent).toContain(
      SECOND_RELEASE_PAYLOAD.release.album_title
    );
    expect(container.querySelector("select:not(#server-url)")).toBeNull();
  });

  it("遅い旧 URL 保存後に最新 URL を保存し、永続化値を latest-wins にする", async () => {
    const firstWrite = deferred<void>();
    let persistedUrl = "";
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(BASE_URL);
    vi.mocked(serverUrlItem.setValue).mockImplementation(async (url) => {
      if (url === BASE_URL) {
        await firstWrite.promise;
      }
      persistedUrl = url;
    });
    fetchMock.mockImplementation(async (url: string) => {
      if (
        url.endsWith("/server-info") ||
        url.endsWith("/version") ||
        url.endsWith("/distrokid/collections")
      ) {
        return jsonResponse(404, {});
      }
      if (url === `${FALLBACK_URL}/distrokid/release.json`) {
        return jsonResponse(200, SECOND_RELEASE_PAYLOAD);
      }
      if (url === `${BASE_URL}/distrokid/release.json`) {
        return jsonResponse(200, RELEASE_PAYLOAD);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    await renderApp();
    await waitFor(() => {
      expect(serverUrlItem.setValue).toHaveBeenCalledWith(BASE_URL);
    });

    await act(async () => {
      setSelectValue(
        container.querySelector<HTMLSelectElement>("#server-url")!,
        FALLBACK_URL
      );
    });
    await act(async () => {
      firstWrite.resolve();
      await firstWrite.promise;
    });
    await waitFor(() => {
      expect(persistedUrl).toBe(FALLBACK_URL);
      expect(container.textContent).toContain(
        SECOND_RELEASE_PAYLOAD.release.album_title
      );
    });
  });

  it("should rerun shared discovery before the selector opens and replace a stopped port", async () => {
    const defaultSource = {
      id: "youtube-automation-localhost-7873",
      label: "YouTube Automation (default)",
      url: "http://youtube-automation.localhost:7873",
    };
    discoveryMocks.discoverServerSources
      .mockResolvedValueOnce([
        defaultSource,
        { id: "old", label: "Old", url: "http://old.localhost:9001" },
      ])
      .mockResolvedValueOnce([
        defaultSource,
        { id: "new", label: "New", url: "http://new.localhost:49152" },
      ])
      .mockResolvedValueOnce([
        defaultSource,
        { id: "new", label: "New", url: "http://new.localhost:49152" },
      ]);

    await renderApp();
    const select = container.querySelector<HTMLSelectElement>("#server-url")!;
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[aria-haspopup="listbox"]'
    )!;
    await waitFor(() => expect(select.textContent).toContain("Old"));
    await act(async () => {
      trigger.click();
    });

    await waitFor(() => expect(select.textContent).toContain("New"));
    expect(select.textContent).not.toContain("Old");
    expect(Array.from(select.options, ({ value }) => value)).toEqual([
      defaultSource.url,
      "http://new.localhost:49152",
    ]);

    await act(async () => {
      trigger.click();
    });
    await waitFor(() =>
      expect(discoveryMocks.discoverServerSources).toHaveBeenCalledTimes(3)
    );
  });

  it("should run discovery once when opening an unfocused selector with the mouse", async () => {
    await renderApp();
    const initialCalls = discoveryMocks.discoverServerSources.mock.calls.length;

    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"]')!
        .click();
    });

    await waitFor(() =>
      expect(discoveryMocks.discoverServerSources).toHaveBeenCalledTimes(
        initialCalls + 1
      )
    );
  });

  it("should replace a restored URL removed by discovery during an early selector refresh", async () => {
    const initialDiscovery =
      deferred<Array<{ id: string; label: string; url: string }>>();
    const defaultSource = {
      id: "youtube-automation-localhost-7873",
      label: "YouTube Automation (default)",
      url: "http://youtube-automation.localhost:7873",
    };
    const restoredSource = {
      id: "restored",
      label: "Restored",
      url: "http://restored.localhost:49152",
    };
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(restoredSource.url);
    discoveryMocks.discoverServerSources
      .mockReturnValueOnce(initialDiscovery.promise)
      .mockResolvedValueOnce([defaultSource]);

    await renderApp();
    const select = container.querySelector<HTMLSelectElement>("#server-url")!;
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"]')!
        .click();
      initialDiscovery.resolve([defaultSource, restoredSource]);
      await initialDiscovery.promise;
    });

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).startsWith(defaultSource.url)
        )
      ).toBe(true)
    );
    expect(select.value).toBe(defaultSource.url);
    expect(discoveryMocks.discoverServerSources).toHaveBeenCalledTimes(2);
  });

  it.each([
    [
      "keeps a saved live URL",
      "http://live.localhost:49152",
      "http://live.localhost:49152",
    ],
    [
      "replaces a saved stopped URL",
      "http://stopped.localhost:9001",
      "http://youtube-automation.localhost:7873",
    ],
  ])(
    "should %s without fetching the stopped URL",
    async (_label, savedUrl, expectedUrl) => {
      const defaultSource = {
        id: "youtube-automation-localhost-7873",
        label: "YouTube Automation (default)",
        url: "http://youtube-automation.localhost:7873",
      };
      const liveSource = {
        id: "live",
        label: "Live",
        url: "http://live.localhost:49152",
      };
      vi.mocked(serverUrlItem.getValue).mockResolvedValue(savedUrl);
      discoveryMocks.discoverServerSources.mockResolvedValueOnce([
        defaultSource,
        liveSource,
      ]);
      fetchMock.mockImplementation(async (url: string) => {
        if (url.startsWith("http://stopped.localhost:9001")) {
          throw new Error("stopped URL must not be fetched");
        }
        return jsonResponse(404, {});
      });

      await renderApp();
      const select = container.querySelector<HTMLSelectElement>("#server-url")!;
      await waitFor(() => expect(select.value).toBe(expectedUrl));

      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).startsWith("http://stopped.localhost:9001")
        )
      ).toBe(false);
      if (savedUrl !== expectedUrl)
        expect(serverUrlItem.setValue).toHaveBeenCalledWith(expectedUrl);
    }
  );

  it("should select a discovered non-default URL without recreating candidate history", async () => {
    const live = {
      id: "channel-b",
      label: "Channel B",
      url: "http://channel-b.localhost:49152",
    };
    const liveSources = [
      {
        id: "youtube-automation-localhost-7873",
        label: "YouTube Automation (default)",
        url: "http://youtube-automation.localhost:7873",
      },
      live,
    ];
    discoveryMocks.discoverServerSources.mockResolvedValue(liveSources);
    await renderApp();
    const select = container.querySelector<HTMLSelectElement>("#server-url")!;
    await waitFor(() =>
      expect(Array.from(select.options, ({ value }) => value)).toContain(
        live.url
      )
    );
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"]')!
        .click()
    );
    await waitFor(() =>
      expect(container.querySelector('[role="listbox"]')).not.toBeNull()
    );
    await act(async () => {
      Array.from(
        container.querySelectorAll<HTMLButtonElement>('[role="option"]')
      )
        .find((option) => option.textContent?.includes("Channel B"))!
        .click();
    });

    await waitFor(() =>
      expect(serverUrlItem.setValue).toHaveBeenCalledWith(live.url)
    );
    expect(container.querySelector('[role="listbox"]')).toBeNull();
    expect(migrateServerSourcesStorage).toHaveBeenCalled();
    expect(legacySourceState.present).toBe(false);
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).startsWith(live.url))
    ).toBe(true);

    act(() => root.unmount());
    container.innerHTML = "";
    root = createRoot(container);
    vi.mocked(serverUrlItem.getValue).mockResolvedValue(live.url);
    await renderApp();
    await waitFor(() =>
      expect(
        container.querySelector<HTMLSelectElement>("#server-url")?.value
      ).toBe(live.url)
    );
  });
});
