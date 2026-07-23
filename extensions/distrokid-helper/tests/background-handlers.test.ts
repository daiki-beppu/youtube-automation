// background.ts の recordRelease ハンドラの契約テスト (#1360)。
//
// overlay は server state を更新する POST を直接呼ばず background に委譲する
// （ADR-0016 の書き込み境界）。ここでは background が recordRelease message を受けて
// shared/api の recordDistrokidRelease（token 取得 / 403 retry 込み）へ委譲することを固定する。
// suno-helper tests/background-handlers.test.ts の defineBackground stub パターンを踏襲する。

import { afterEach, describe, expect, it, vi } from "vitest";

type Handler = (msg: {
  data: Record<string, unknown>;
  sender: { tab?: { id?: number } };
}) => unknown;

const RECORD = {
  collection_id: "20260526-soulful-grooves-coding-focus-collection",
  disc: "disc1-coding-focus-vol1",
  album_title: "Coding Focus Vol.1",
};

async function loadBackground(opts?: {
  recordError?: Error;
  migrationError?: Error;
}) {
  vi.resetModules();

  const handlers = new Map<string, Handler>();
  const installedListeners: Array<() => void> = [];
  const actionListeners: Array<(tab: { id?: number }) => void> = [];

  // defineBackground は WXT の auto-import。stub して即座にコールバックを実行する。
  vi.stubGlobal("defineBackground", (fn: () => void) => {
    fn();
    return fn;
  });
  vi.stubGlobal("browser", {
    action: {
      onClicked: {
        addListener: vi.fn((listener: (tab: { id?: number }) => void) =>
          actionListeners.push(listener)
        ),
      },
    },
    runtime: {
      getURL: (path: string) =>
        `chrome-extension://distrokid-helper-id/${path}`,
      onInstalled: {
        addListener: vi.fn((listener: () => void) =>
          installedListeners.push(listener)
        ),
      },
    },
  });

  const sendMessageMock = vi.fn(() => Promise.resolve());
  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((type: string, handler: Handler) => {
      handlers.set(type, handler);
      return vi.fn();
    }),
    sendMessage: sendMessageMock,
  }));

  const recordDistrokidReleaseMock = opts?.recordError
    ? vi.fn(() => Promise.reject(opts.recordError))
    : vi.fn(() => Promise.resolve());
  vi.doMock("../../shared/api", () => ({
    recordDistrokidRelease: recordDistrokidReleaseMock,
  }));
  const migrateServerSourcesStorageMock = opts?.migrationError
    ? vi.fn(() => Promise.reject(opts.migrationError))
    : vi.fn(() => Promise.resolve());
  vi.doMock("../lib/storage", () => ({
    migrateServerSourcesStorage: migrateServerSourcesStorageMock,
  }));

  // import が defineBackground コールバックを実行し、ハンドラが登録される。
  await import("../entrypoints/background");

  return {
    handlers,
    actionListeners,
    installedListeners,
    migrateServerSourcesStorageMock,
    recordDistrokidReleaseMock,
    sendMessageMock,
  };
}

afterEach(() => {
  vi.doUnmock("../lib/messaging");
  vi.doUnmock("../../shared/api");
  vi.unstubAllGlobals();
});

describe("background overlay relay", () => {
  it("action click はクリックされた同一タブの overlay だけを切り替える", async () => {
    const { actionListeners, sendMessageMock } = await loadBackground();

    actionListeners[0]({ id: 42 });
    await Promise.resolve();

    expect(sendMessageMock).toHaveBeenCalledWith(
      "toggleOverlay",
      undefined,
      42
    );
  });

  it("overlay command と runner progress を送信元と同一タブへ中継する", async () => {
    const { handlers, sendMessageMock } = await loadBackground();
    const sender = { tab: { id: 42 } };

    await handlers.get("injectStart")!({
      data: { payload: { release: {} } },
      sender,
    });
    await handlers.get("progress")!({
      data: { phase: "injecting", message: "working" },
      sender,
    });

    expect(sendMessageMock).toHaveBeenCalledWith(
      "injectStart",
      { payload: { release: {} } },
      42
    );
    expect(sendMessageMock).toHaveBeenCalledWith(
      "progress",
      { phase: "injecting", message: "working" },
      42
    );
  });

  it("tab を持たない sender の relay は fail-loud に拒否する", async () => {
    const { handlers } = await loadBackground();

    expect(() => handlers.get("stop")!({ data: {}, sender: {} })).toThrow(
      "stop: 送信元タブが特定できません"
    );
  });
});

describe('background onMessage("recordRelease"): serve token 書き込み境界 (#1360)', () => {
  it("Given background 起動 When ハンドラ登録を確認 Then recordRelease が登録される", async () => {
    const { handlers } = await loadBackground();

    expect(handlers.has("recordRelease")).toBe(true);
  });

  it("Given recordRelease message When handler 実行 Then shared/api に baseUrl と record を委譲する", async () => {
    const { handlers, recordDistrokidReleaseMock } = await loadBackground();

    await handlers.get("recordRelease")!({
      data: { baseUrl: "http://localhost:7873", record: RECORD },
      sender: {},
    });

    expect(recordDistrokidReleaseMock).toHaveBeenCalledWith(
      "http://localhost:7873",
      RECORD,
      { extensionOrigin: "chrome-extension://distrokid-helper-id" }
    );
  });

  it("Given shared/api が reject When handler 実行 Then reject を伝播する（overlay が warn 表示する）", async () => {
    const { handlers, recordDistrokidReleaseMock } = await loadBackground({
      recordError: new Error("HTTP 403"),
    });

    await expect(
      handlers.get("recordRelease")!({
        data: { baseUrl: "http://localhost:7873", record: RECORD },
        sender: {},
      })
    ).rejects.toThrow("HTTP 403");
    expect(recordDistrokidReleaseMock).toHaveBeenCalledTimes(1);
  });
});

describe("background onInstalled: legacy server source migration", () => {
  it("runs migration when the extension is updated", async () => {
    const { installedListeners, migrateServerSourcesStorageMock } =
      await loadBackground();

    installedListeners.forEach((listener) => listener());
    await Promise.resolve();

    expect(migrateServerSourcesStorageMock).toHaveBeenCalledOnce();
  });

  it("logs migration failures instead of leaving an unhandled rejection", async () => {
    const error = new Error("storage unavailable");
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const { installedListeners } = await loadBackground({
      migrationError: error,
    });

    installedListeners.forEach((listener) => listener());
    await Promise.resolve();
    await Promise.resolve();

    expect(consoleError).toHaveBeenCalledWith(
      "[distrokid-helper] legacy server source migration failed:",
      error
    );
    consoleError.mockRestore();
  });
});
