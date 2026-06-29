// @vitest-environment jsdom

import { act } from "react";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../components/App";

const BASE_URL = "http://localhost:7873";
const MANIFEST_VERSION = "0.1.9";

const messagingMocks = vi.hoisted(() => ({
  onMessage: vi.fn(() => () => undefined),
  sendMessage: vi.fn(),
}));

const storageMocks = vi.hoisted(() => ({
  getValue: vi.fn(async () => ""),
  setValue: vi.fn(async () => undefined),
}));

const downloadFormatMocks = vi.hoisted(() => ({
  getValue: vi.fn(async () => "mp3"),
  setValue: vi.fn(async () => undefined),
}));

const resumeStateMocks = vi.hoisted(() => ({
  readResumeState: vi.fn(async () => null),
  writeResumeState: vi.fn(async () => undefined),
}));

vi.mock("wxt/browser", () => ({
  browser: {
    runtime: {
      getManifest: vi.fn(() => ({ version: MANIFEST_VERSION })),
    },
  },
}));

vi.mock("../lib/storage", () => ({
  serverUrlItem: storageMocks,
  downloadFormatItem: downloadFormatMocks,
  readDownloadFormat: vi.fn(() => downloadFormatMocks.getValue()),
}));

vi.mock("../lib/messaging", () => messagingMocks);

async function readJson(url: string): Promise<unknown> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

function defaultSendMessage(message: string, payload?: Record<string, string>): Promise<unknown> {
  if (message === "queryProgress") {
    throw new Error("runner unavailable");
  }
  if (message === "fetchCompatibilityWarning") {
    return (async () => {
      const resp = await fetch(`${payload?.baseUrl}/version`);
      if (!resp.ok) {
        return "";
      }
      const data = (await resp.json()) as { version: string; min_extension_version: string };
      if (payload?.extensionVersion === data.min_extension_version) {
        return "";
      }
      return `拡張を更新してください（拡張 ${payload?.extensionVersion} / 必要 ${data.min_extension_version} / サーバー ${data.version}）。`;
    })();
  }
  if (message === "fetchCollections") {
    return readJson(`${payload?.baseUrl}/collections`);
  }
  if (message === "fetchPrompts") {
    return readJson(`${payload?.baseUrl}/suno/prompts.json`);
  }
  if (message === "fetchCollectionPrompts") {
    return readJson(
      `${payload?.baseUrl}/collections/${encodeURIComponent(payload?.collectionId ?? "")}/suno/prompts.json`,
    );
  }
  return Promise.resolve({ ok: true });
}

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
    readResumeState: resumeStateMocks.readResumeState,
    writeResumeState: resumeStateMocks.writeResumeState,
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

function setSelectValue(select: HTMLSelectElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
  if (!setter) {
    throw new Error("HTMLSelectElement.value setter is unavailable");
  }
  setter.call(select, value);
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find((candidate) =>
    candidate.textContent?.includes(text),
  );
  if (!button) {
    throw new Error(`button not found: ${text}`);
  }
  return button;
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
    storageMocks.getValue.mockResolvedValue("");
    storageMocks.setValue.mockResolvedValue(undefined);
    downloadFormatMocks.getValue.mockResolvedValue("mp3");
    downloadFormatMocks.setValue.mockResolvedValue(undefined);
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      root.render(createElement(App));
    });
  });

  async function rerenderAppWithDownloadFormat(value: string): Promise<void> {
    await act(async () => {
      root.unmount();
    });
    container.innerHTML = "";
    root = createRoot(container);
    downloadFormatMocks.getValue.mockResolvedValueOnce(value);
    await act(async () => {
      root.render(createElement(App));
    });
  }

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    storageMocks.getValue.mockResolvedValue("");
    storageMocks.setValue.mockResolvedValue(undefined);
    resumeStateMocks.readResumeState.mockResolvedValue(null);
    resumeStateMocks.writeResumeState.mockResolvedValue(undefined);
  });

  it("データ取得時に manifest version で /version を先に呼び、非互換警告を表示して prompts 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: "0.2.0" }))
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain(`拡張を更新してください（拡張 ${MANIFEST_VERSION}`);
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(3, `${BASE_URL}/suno/prompts.json`);
  });

  it("旧サーバーの /version 404 は警告なしで prompts 取得を継続する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(404, {}))
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(container.textContent).not.toContain("拡張を更新してください");
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(3, `${BASE_URL}/suno/prompts.json`);
  });

  it("dir mode で URL 入力後にデータ取得すると collection endpoint の entries を run payload に渡す", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a",
            channel: "clm",
            theme: "theme-a",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "全パターンを連続実行").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("連続実行を開始しました。");
    });
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${BASE_URL}/collections/20260601-clm-theme-a-collection/suno/prompts.json`,
    );
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("run", {
      entries,
      playlistName: "clm | theme-a",
      range: undefined,
      collectionId: "20260601-clm-theme-a-collection",
      indices: undefined,
      submittedClipIds: undefined,
      playlistExpectedClipCount: undefined,
    });
  });

  it("dir mode の channel/theme から multi-word channel の playlist 名を導出する", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-soulful-grooves-wah-groove-collection",
            name: "wah-groove",
            channel: "soulful-grooves",
            theme: "wah-groove",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "全パターンを連続実行").click();
    });

    await waitFor(() => {
      expect(messagingMocks.sendMessage).toHaveBeenCalledWith(
        "run",
        expect.objectContaining({
          playlistName: "soulful-grooves | wah-groove",
        }),
      );
    });
  });

  it("dir mode でデータ取得後に collection を変更すると再取得まで連続実行できない", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
          {
            id: "20260602-clm-theme-b-collection",
            name: "theme-b-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      setSelectValue(container.querySelector<HTMLSelectElement>("select")!, "20260602-clm-theme-b-collection");
    });

    const runButton = buttonByText(container, "全パターンを連続実行");
    expect(runButton.disabled).toBe(true);

    await act(async () => {
      runButton.click();
    });
    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("run", expect.anything());
  });

  it("clip ID が無い再開時に Suno 上の選択中 clip を採用して resume state に保存する", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });
    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("adoptSelectedClips", { expectedClipCount: 2 });
    expect(resumeStateMocks.writeResumeState).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId: "20260601-clm-theme-a-collection",
        failedIndex: 1,
        total: 1,
        submittedClipIds: ["clip-a", "clip-b"],
        playlistExpectedClipCount: 2,
      }),
    );
  });

  it("選択中 clip 採用後に Download から再開すると retryDownload payload を送る", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryDownload", {
      collectionId: "20260601-clm-theme-a-collection",
      playlistName: "clm | theme-a",
      submittedClipIds: ["clip-a", "clip-b"],
      expectedClipCount: 2,
    });
  });

  it("expected_file_count が entries×2 より大きい場合は手動採用と Download 再開に expected_file_count を使う", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 4,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b", "clip-c", "clip-d"] });
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 4 件を採用しました。");
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("adoptSelectedClips", { expectedClipCount: 4 });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryDownload", {
      collectionId: "20260601-clm-theme-a-collection",
      playlistName: "clm | theme-a",
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      expectedClipCount: 4,
    });
  });

  it("DL 形式 select は storage の初期値を反映し、変更時に保存する", async () => {
    await rerenderAppWithDownloadFormat("m4a");

    const select = Array.from(container.querySelectorAll("select")).find((candidate) =>
      Array.from(candidate.options).some((option) => option.value === "wav"),
    );
    if (!select) throw new Error("download format select not found");
    await waitFor(() => {
      expect(select.value).toBe("m4a");
    });

    await act(async () => {
      setSelectValue(select, "wav");
    });

    expect(downloadFormatMocks.setValue).toHaveBeenCalledWith("wav");
    expect(select.value).toBe("wav");
  });

  it("DL 形式 select は不正な storage 値を MP3 に戻す", async () => {
    await rerenderAppWithDownloadFormat("flac");

    const select = Array.from(container.querySelectorAll("select")).find((candidate) =>
      Array.from(candidate.options).some((option) => option.value === "wav"),
    );
    if (!select) throw new Error("download format select not found");
    await waitFor(() => {
      expect(select.value).toBe("mp3");
    });
  });

  it("選択中 clip 採用後に Playlist から再開すると retryPlaylist payload を送る", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryPlaylist", {
      collectionId: "20260601-clm-theme-a-collection",
      playlistName: "clm | theme-a",
      submittedClipIds: ["clip-a", "clip-b"],
      expectedClipCount: 2,
      shouldDownload: true,
    });
    await waitFor(() => {
      expect(container.textContent).toContain("playlist 追加とダウンロードを再実行しています…");
    });
  });

  it("persisted resume が entries 未取得でも Playlist から再開すると Download all 対象として送る", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    resumeStateMocks.readResumeState.mockResolvedValue({
      collectionId: "20260601-clm-theme-a-collection",
      failedIndex: 1,
      total: 1,
      timestamp: Date.now(),
      submittedClipIds: ["clip-a", "clip-b"],
      playlistExpectedClipCount: 2,
    } as never);
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(500, {}));
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);

    await act(async () => {
      root.render(createElement(App));
    });
    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("全 entry 投入済みです。playlist 追加から再開しますか？");
      expect(container.textContent).toContain("Playlist: clm | theme-a");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryPlaylist", {
      collectionId: "20260601-clm-theme-a-collection",
      playlistName: "clm | theme-a",
      submittedClipIds: ["clip-a", "clip-b"],
      expectedClipCount: 2,
      shouldDownload: true,
    });
  });

  it("clip ID が無い状態で Playlist から再開しても retryPlaylist を送らずエラー表示する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("retryPlaylist", expect.anything());
    expect(container.textContent).toContain("playlist 再開に必要な clip ID がありません。");
  });

  it("Playlist から再開の送信に失敗したらエラーを表示して再試行可能にする", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, entries));
    messagingMocks.sendMessage.mockImplementation((message: string, payload?: Record<string, string>) => {
      if (message === "queryProgress") {
        throw new Error("runner unavailable");
      }
      if (message === "adoptSelectedClips") {
        return Promise.resolve({ ok: true, clipIds: ["clip-a", "clip-b"] });
      }
      if (message === "retryPlaylist") {
        return Promise.reject(new Error("relay failed"));
      }
      return defaultSendMessage(message, payload);
    });

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    await act(async () => {
      buttonByText(container, "選択中の曲を採用").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("選択中の曲 2 件を採用しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Playlist から再開").click();
    });

    expect(messagingMocks.sendMessage).toHaveBeenCalledWith("retryPlaylist", expect.anything());
    await waitFor(() => {
      expect(container.textContent).toContain("開始失敗: relay failed");
      expect(buttonByText(container, "Playlist から再開").disabled).toBe(false);
    });
  });

  it("clip ID が無い状態で Download から再開しても retryDownload を送らずエラー表示する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
            expected_file_count: 2,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });
    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      buttonByText(container, "Download から再開").click();
    });

    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("retryDownload", expect.anything());
    expect(container.textContent).toContain("ダウンロード再開に必要な clip ID がありません。");
  });

  it("dir mode でデータ取得後に URL を変更すると再取得まで連続実行できない", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            id: "20260601-clm-theme-a-collection",
            name: "theme-a-collection",
            status: "ready",
            pattern_count: 1,
            downloaded_count: 0,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });

    messagingMocks.sendMessage.mockClear();
    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, `${BASE_URL}/changed`);
    });

    const runButton = buttonByText(container, "全パターンを連続実行");
    expect(runButton.disabled).toBe(true);

    await act(async () => {
      runButton.click();
    });
    expect(messagingMocks.sendMessage).not.toHaveBeenCalledWith("run", expect.anything());
  });

  it("dir mode の collection 一覧に実行可能候補が無い場合は single-file endpoint へフォールバックしない", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockResolvedValueOnce(jsonResponse(200, []));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("取得失敗: prompts を取得できる collection がありません。");
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
  });

  it("popup 起動時の collection 一覧同期は status ベースの新スキーマで動作する (#1216)", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    fetchMock.mockReset();
    storageMocks.getValue.mockResolvedValue(BASE_URL);
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [
        {
          id: "20260601-clm-theme-a-collection",
          name: "theme-a-collection",
          status: "ready",
          pattern_count: 1,
          downloaded_count: 0,
        },
      ]),
    );

    await act(async () => {
      root.render(createElement(App));
    });

    await waitFor(() => {
      expect(container.textContent).toContain("コレクション");
    });
    expect(container.textContent).not.toContain("コレクション一覧取得失敗");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/collections`);
  });

  it("popup 起動時の collection 一覧同期は downloaded collection を表示しない", async () => {
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    fetchMock.mockReset();
    storageMocks.getValue.mockResolvedValue(BASE_URL);
    messagingMocks.sendMessage.mockImplementation(defaultSendMessage);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [
        {
          id: "20260601-clm-done-collection",
          name: "done-collection",
          status: "downloaded",
          pattern_count: 2,
          downloaded_count: 4,
        },
        {
          id: "20260601-clm-ready-collection",
          name: "ready-collection",
          status: "ready",
          pattern_count: 1,
          downloaded_count: 0,
        },
      ]),
    );

    await act(async () => {
      root.render(createElement(App));
    });

    await waitFor(() => {
      expect(container.textContent).toContain("ready-collection");
    });
    expect(container.textContent).not.toContain("done-collection");
  });

  it("CORS なし 404 (TypeError) で /collections が reject されても single-file mode へ fallback する", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { version: "5.5.7", min_extension_version: MANIFEST_VERSION }))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse(200, [{ name: "p1", style: "lofi", lyrics: "" }]));

    await act(async () => {
      setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, BASE_URL);
    });
    await act(async () => {
      buttonByText(container, "データ取得").click();
    });

    await waitFor(() => {
      expect(container.textContent).toContain("1 パターンを取得しました。");
    });
    expect(fetchMock).toHaveBeenNthCalledWith(1, `${BASE_URL}/version`);
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${BASE_URL}/collections`);
    expect(fetchMock).toHaveBeenNthCalledWith(3, `${BASE_URL}/suno/prompts.json`);
  });
});
