// background.ts の recordRelease ハンドラの契約テスト (#1360)。
//
// popup は server state を更新する POST を直接呼ばず background に委譲する
// （ADR-0016 の書き込み境界）。ここでは background が recordRelease message を受けて
// shared/api の recordDistrokidRelease（token 取得 / 403 retry 込み）へ委譲することを固定する。
// suno-helper tests/background-handlers.test.ts の defineBackground stub パターンを踏襲する。

import { afterEach, describe, expect, it, vi } from "vitest";

type Handler = (msg: { data: Record<string, unknown>; sender: Record<string, unknown> }) => unknown;

const RECORD = {
  collection_id: "20260526-soulful-grooves-coding-focus-collection",
  disc: "disc1-coding-focus-vol1",
  album_title: "Coding Focus Vol.1",
};

async function loadBackground(opts?: { recordError?: Error }) {
  vi.resetModules();

  const handlers = new Map<string, Handler>();

  // defineBackground は WXT の auto-import。stub して即座にコールバックを実行する。
  vi.stubGlobal("defineBackground", (fn: () => void) => {
    fn();
    return fn;
  });

  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((type: string, handler: Handler) => {
      handlers.set(type, handler);
      return vi.fn();
    }),
    sendMessage: vi.fn(),
  }));

  const recordDistrokidReleaseMock = opts?.recordError
    ? vi.fn(() => Promise.reject(opts.recordError))
    : vi.fn(() => Promise.resolve());
  vi.doMock("../../shared/api", () => ({
    recordDistrokidRelease: recordDistrokidReleaseMock,
  }));

  // import が defineBackground コールバックを実行し、ハンドラが登録される。
  await import("../entrypoints/background");

  return { handlers, recordDistrokidReleaseMock };
}

afterEach(() => {
  vi.doUnmock("../lib/messaging");
  vi.doUnmock("../../shared/api");
  vi.unstubAllGlobals();
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

    expect(recordDistrokidReleaseMock).toHaveBeenCalledWith("http://localhost:7873", RECORD);
  });

  it("Given shared/api が reject When handler 実行 Then reject を伝播する（popup が warn 表示する）", async () => {
    const { handlers, recordDistrokidReleaseMock } = await loadBackground({
      recordError: new Error("HTTP 403"),
    });

    await expect(
      handlers.get("recordRelease")!({
        data: { baseUrl: "http://localhost:7873", record: RECORD },
        sender: {},
      }),
    ).rejects.toThrow("HTTP 403");
    expect(recordDistrokidReleaseMock).toHaveBeenCalledTimes(1);
  });
});
