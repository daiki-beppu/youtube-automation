// @vitest-environment jsdom

// useDistrokidRunner の unit test (#1361)。
//
// popup-compatibility.test.ts が App 経由でカバーする compatibility 警告 / 単一 mode fallback
// 以外の runner 制御を hook 単体で検証する:
//   - dir mode: collection-scoped release.json の取得と選択 index の維持
//   - 全 disc 配信済み: allReleased フラグと fetch 時のガイダンス
//   - stop: content への stop message 送信
//   - inject 完了後の released record（成功 → 一覧再取得 / 失敗 → warning 表示）

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDistrokidRunner, type DistrokidRunnerState } from "../components/useDistrokidRunner";
import { sendMessage } from "../lib/messaging";
import { migrateServerSourcesStorage, serverUrlItem } from "../lib/storage";
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
    album_title: "Coding Focus Vol.1",
    tracks: [{ title: "track-01", filename: "track-01.mp3", asset_path: "/distrokid/assets/track-01.mp3" }],
    cover: null,
    release_date: "2026-07-01",
  },
};

const DISC1 = {
  collection_id: "20260526-coding-focus-collection",
  name: "coding focus",
  disc: "disc1",
  album_title: "Coding Focus Vol.1",
  track_count: 1,
  released: false,
};

const DISC2 = {
  collection_id: "20260526-coding-focus-collection",
  name: "coding focus",
  disc: "disc2",
  album_title: "Coding Focus Vol.2",
  track_count: 1,
  released: false,
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
  migrateServerSourcesStorage: vi.fn(async () => undefined),
}));

const discoveryMocks = vi.hoisted(() => ({
  discoverServerSources: vi.fn(async () => [
    {
      id: "youtube-automation-localhost-7873",
      label: "YouTube Automation (default)",
      url: "http://youtube-automation.localhost:7873",
    },
  ]),
}));

vi.mock("../../shared/server-discovery", () => discoveryMocks);

vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn(() => () => undefined),
  sendMessage: vi.fn(async () => undefined),
  PHASES: {
    INJECTING: "injecting",
    DONE: "done",
    ERROR: "error",
    STOPPED: "stopped",
  },
}));

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

// jsdom の Blob は arrayBuffer() 未実装のため、encodeAsset が使う interface だけを持つ
// Blob 互換スタブを返す。
function blobResponse(): Response {
  return {
    ok: true,
    status: 200,
    blob: async () => ({
      type: "audio/mpeg",
      arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer,
    }),
  } as unknown as Response;
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

// hook を直接マウントする probe。render のたびに最新の runner state を onState 経由で捕捉する
// （component 内からモジュール変数へ直接代入すると react-hooks/globals に抵触するため）。
function Probe({ onState }: { onState: (state: DistrokidRunnerState) => void }): null {
  onState(useDistrokidRunner());
  return null;
}

describe("useDistrokidRunner", () => {
  let root: Root;
  let container: HTMLDivElement;
  let fetchMock: ReturnType<typeof vi.fn>;
  let current: DistrokidRunnerState;

  beforeEach(async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      root.render(
        createElement(Probe, {
          onState: (state) => {
            current = state;
          },
        }),
      );
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    discoveryMocks.discoverServerSources.mockResolvedValue([
      {
        id: "youtube-automation-localhost-7873",
        label: "YouTube Automation (default)",
        url: "http://youtube-automation.localhost:7873",
      },
    ]);
    vi.mocked(migrateServerSourcesStorage).mockResolvedValue(undefined);
  });

  // dir mode サーバーの URL ルーティング fetch mock。released record は background message
  // に委譲されるため、recordRelease message を受けると以降の /distrokid/collections で
  // 該当 disc を released:true にする（サーバー挙動の再現）。
  function stubDirModeServer({ recordStatus = 200 }: { recordStatus?: number } = {}) {
    let disc1Released = false;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === `${BASE_URL}/version`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/collections`) {
        return jsonResponse(200, [{ ...DISC1, released: disc1Released }, DISC2]);
      }
      if (url === `${BASE_URL}/collections/${DISC1.collection_id}/distrokid/${DISC1.disc}/release.json`) {
        return jsonResponse(200, RELEASE_PAYLOAD);
      }
      if (url === `${BASE_URL}/collections/${DISC2.collection_id}/distrokid/${DISC2.disc}/release.json`) {
        return jsonResponse(200, {
          ...RELEASE_PAYLOAD,
          release: { ...RELEASE_PAYLOAD.release, album_title: DISC2.album_title },
        });
      }
      if (url === `${BASE_URL}/distrokid/assets/track-01.mp3`) {
        return blobResponse();
      }
      if (url === `${BASE_URL}/distrokid/releases` && init?.method === "POST") {
        if (recordStatus < 300) {
          disc1Released = true;
        }
        return jsonResponse(recordStatus, {});
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type === "recordRelease") {
        if (recordStatus >= 300) {
          throw new Error(`HTTP ${recordStatus}`);
        }
        disc1Released = true;
      }
      return undefined;
    });
  }

  async function fetchDirModeRelease(): Promise<void> {
    await act(async () => {
      current.setServerUrl(BASE_URL);
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
      expect(current.busy).toBe(false);
    });
  }

  it("dir mode: 選択中 disc の collection-scoped release.json を取得して payload をセットする", async () => {
    stubDirModeServer();

    await fetchDirModeRelease();

    expect(current.collections).toHaveLength(2);
    expect(current.selectedIndex).toBe(0);
    expect(current.payload?.release.album_title).toBe(RELEASE_PAYLOAD.release.album_title);
    expect(current.busy).toBe(false);
    expect(current.allReleased).toBe(false);
  });

  it("dir mode: 全 disc 配信済みのとき allReleased を立て、fetch はガイダンスを表示して payload を返さない", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/version`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/collections`) {
        return jsonResponse(200, [
          { ...DISC1, released: true },
          { ...DISC2, released: true },
        ]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    await fetchDirModeRelease();

    expect(current.allReleased).toBe(true);
    expect(current.collections).toHaveLength(0);
    expect(current.payload).toBeNull();
    expect(current.message).toBe("未配信の disc はありません。");
    expect(current.busy).toBe(false);
  });

  it("単一 mode: release が利用不可なら既存ガイダンスを表示して payload を返さない", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/version` || url === `${BASE_URL}/distrokid/collections`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/release.json`) {
        return jsonResponse(404, {});
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    await fetchDirModeRelease();

    expect(current.payload).toBeNull();
    expect(current.phase).toBe("error");
    expect(current.message).toContain("distrokid 連携が無効です");
    expect(current.busy).toBe(false);
  });

  it("単一 mode: 一般取得エラーなら詳細を表示して古い payload を無効化する", async () => {
    stubDirModeServer();
    await fetchDirModeRelease();
    expect(current.payload).not.toBeNull();

    fetchMock.mockImplementation(async (url: string) => {
      if (url === `${BASE_URL}/version` || url === `${BASE_URL}/distrokid/collections`) {
        return jsonResponse(404, {});
      }
      if (url === `${BASE_URL}/distrokid/release.json`) {
        return jsonResponse(500, {});
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    await act(async () => {
      current.setServerUrl(BASE_URL);
    });
    await waitFor(() => {
      expect(current.message).toContain("HTTP 500");
      expect(current.busy).toBe(false);
    });

    expect(current.payload).toBeNull();
    expect(current.phase).toBe("error");
    expect(current.message).toContain("HTTP 500");
    expect(current.busy).toBe(false);
  });

  it("stop: content へ stop message を送る", async () => {
    await act(async () => {
      await current.stop();
    });

    expect(sendMessage).toHaveBeenCalledWith("stop", undefined, 1);
  });

  it("inject: 完了後に配信済み記録を POST し、一覧を再取得して配信済み disc を除外する", async () => {
    stubDirModeServer();
    await fetchDirModeRelease();

    await act(async () => {
      await current.inject();
    });

    // injectStart → injectTrack → injectFinish（cover なし）を tab 1 へ送る。
    expect(sendMessage).toHaveBeenCalledWith("injectStart", expect.anything(), 1);
    expect(sendMessage).toHaveBeenCalledWith("injectTrack", expect.objectContaining({ trackIndex: 0 }), 1);
    expect(sendMessage).toHaveBeenCalledWith("injectFinish", undefined, 1);
    // 配信済み記録は background に委譲し、その成功後の再取得で disc1 が select から消える。
    expect(sendMessage).toHaveBeenCalledWith("recordRelease", {
      baseUrl: BASE_URL,
      record: {
        collection_id: DISC1.collection_id,
        disc: DISC1.disc,
        album_title: DISC1.album_title,
      },
    });
    expect(current.collections.map((c) => c.disc)).toEqual([DISC2.disc]);
  });

  it("inject: collection 自動切替後は取得した最新 disc に配信済み記録を束縛する", async () => {
    stubDirModeServer();
    await fetchDirModeRelease();

    await act(async () => {
      current.selectCollection(1);
    });
    await waitFor(() => {
      expect(current.payload?.release.album_title).toBe(DISC2.album_title);
      expect(current.busy).toBe(false);
    });
    await act(async () => {
      await current.inject();
    });

    expect(sendMessage).toHaveBeenCalledWith("recordRelease", {
      baseUrl: BASE_URL,
      record: {
        collection_id: DISC2.collection_id,
        disc: DISC2.disc,
        album_title: DISC2.album_title,
      },
    });
  });

  it("inject: 開始後の強制選択変更を受け付けず、開始時 URL・payload・disc で完了する", async () => {
    let resolveInjectionStart!: () => void;
    const injectionStart = new Promise<void>((resolve) => {
      resolveInjectionStart = resolve;
    });
    stubDirModeServer();
    await fetchDirModeRelease();
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type === "injectStart") {
        await injectionStart;
      }
      return undefined;
    });

    let injectionPromise!: Promise<void>;
    await act(async () => {
      injectionPromise = current.inject();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith("injectStart", { payload: RELEASE_PAYLOAD }, 1);
      expect(current.isInjecting).toBe(true);
    });

    const discoveryCalls = discoveryMocks.discoverServerSources.mock.calls.length;
    await act(async () => {
      await current.refreshServerSources();
      current.setServerUrl("http://localhost:7999");
      current.selectCollection(1);
    });
    expect(discoveryMocks.discoverServerSources).toHaveBeenCalledTimes(discoveryCalls);
    await act(async () => {
      resolveInjectionStart();
      await injectionPromise;
    });

    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/distrokid/assets/track-01.mp3`, { method: "GET" });
    expect(sendMessage).toHaveBeenCalledWith("recordRelease", {
      baseUrl: BASE_URL,
      record: {
        collection_id: DISC1.collection_id,
        disc: DISC1.disc,
        album_title: DISC1.album_title,
      },
    });
    expect(current.serverUrl).toBe(BASE_URL);
    expect(current.selectedIndex).toBe(0);
    expect(current.isInjecting).toBe(false);
  });

  it("inject: 配信済み記録の POST 失敗はフィル結果を覆さず warning を表示する", async () => {
    stubDirModeServer({ recordStatus: 500 });
    await fetchDirModeRelease();

    await act(async () => {
      await current.inject();
    });

    expect(current.phase).not.toBe("error");
    expect(current.message).toContain("注入完了（配信済み記録に失敗しました");
    // 記録失敗時は一覧を再取得しない（disc1 は select に残る）。
    expect(current.collections.map((c) => c.disc)).toEqual([DISC1.disc, DISC2.disc]);
  });

  it("should refresh from shared discovery and persist only the selected URL", async () => {
    const live = { id: "channel-b-49152", label: "Channel B", url: "http://channel-b.localhost:49152" };
    discoveryMocks.discoverServerSources.mockResolvedValueOnce([
      {
        id: "youtube-automation-localhost-7873",
        label: "YouTube Automation (default)",
        url: "http://youtube-automation.localhost:7873",
      },
      live,
    ]);

    await act(async () => {
      await current.refreshServerSources();
    });
    await act(async () => {
      current.setServerUrl(live.url);
    });

    expect(current.serverSources.map(({ url }) => url)).toContain(live.url);
    expect(serverUrlItem.setValue).toHaveBeenCalledWith(live.url);
  });

  it("should ignore stale discovery completions", async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof discoveryMocks.discoverServerSources>>) => void;
    let resolveNew!: (value: Awaited<ReturnType<typeof discoveryMocks.discoverServerSources>>) => void;
    const oldResult = new Promise<Awaited<ReturnType<typeof discoveryMocks.discoverServerSources>>>((resolve) => {
      resolveOld = resolve;
    });
    const newResult = new Promise<Awaited<ReturnType<typeof discoveryMocks.discoverServerSources>>>((resolve) => {
      resolveNew = resolve;
    });
    discoveryMocks.discoverServerSources.mockReturnValueOnce(oldResult).mockReturnValueOnce(newResult);

    let oldRefresh!: Promise<void>;
    let newRefresh!: Promise<void>;
    await act(async () => {
      oldRefresh = current.refreshServerSources();
      newRefresh = current.refreshServerSources();
    });
    resolveNew([{ id: "new", label: "New", url: "http://new.localhost:49152" }]);
    await act(async () => newRefresh);
    resolveOld([{ id: "old", label: "Old", url: "http://old.localhost:9001" }]);
    await act(async () => oldRefresh);

    expect(current.serverSources.map(({ label }) => label)).toContain("New");
    expect(current.serverSources.map(({ label }) => label)).not.toContain("Old");
  });

  it("should discard a deferred discovery result when injection starts", async () => {
    stubDirModeServer();
    await fetchDirModeRelease();
    let resolveDiscovery!: (value: Awaited<ReturnType<typeof discoveryMocks.discoverServerSources>>) => void;
    const pendingDiscovery = new Promise<Awaited<ReturnType<typeof discoveryMocks.discoverServerSources>>>(
      (resolve) => {
        resolveDiscovery = resolve;
      },
    );
    let resolveInjectionStart!: () => void;
    const injectionStart = new Promise<void>((resolve) => {
      resolveInjectionStart = resolve;
    });
    discoveryMocks.discoverServerSources.mockReturnValueOnce(pendingDiscovery);
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type === "injectStart") await injectionStart;
      return undefined;
    });

    let refresh!: Promise<void>;
    let injection!: Promise<void>;
    await act(async () => {
      refresh = current.refreshServerSources();
      injection = current.inject();
      await Promise.resolve();
    });
    await waitFor(() => expect(current.isInjecting).toBe(true));
    resolveDiscovery([{ id: "new", label: "New", url: "http://new.localhost:49152" }]);
    await act(async () => refresh);

    expect(current.serverSources.map(({ label }) => label)).not.toContain("New");
    expect(current.serverUrl).toBe(BASE_URL);

    resolveInjectionStart();
    await act(async () => injection);
  });

  it("should report storage migration failures without leaving an unhandled rejection", async () => {
    vi.mocked(migrateServerSourcesStorage).mockRejectedValueOnce(new Error("storage unavailable"));
    await act(async () => {
      root.unmount();
      root = createRoot(container);
      root.render(
        createElement(Probe, {
          onState: (state) => {
            current = state;
          },
        }),
      );
    });
    await waitFor(() => {
      expect(current.phase).toBe("error");
      expect(current.message).toContain("storage unavailable");
    });
  });

  it("should report selected URL persistence failures as an explicit error phase", async () => {
    vi.mocked(serverUrlItem.setValue).mockRejectedValueOnce(new Error("URL storage unavailable"));

    await act(async () => {
      current.setServerUrl("http://live.localhost:49152");
    });

    await waitFor(() => {
      expect(current.phase).toBe("error");
      expect(current.message).toContain("URL storage unavailable");
    });
  });
});
