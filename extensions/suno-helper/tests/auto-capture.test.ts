// 連続実行完了時の自動 capture orchestration の回帰テスト (#893 追加要件 A)。
//
// 受け入れ基準「playlist 化完了 → bg tab で /me を開いて閉じ、POST /suno/playlists が走る」の中核。
// background.ts は wxt globals を伴い node 環境から import 不可のため、orchestration を lib/auto-capture へ
// 切り出し（overlay-relay と同方針）、副作用を引数注入にして純ロジックを検証する。
import { describe, expect, it, vi } from "vitest";

import { autoCapturePlaylists, captureFromTab, triggerPlaylistCaptureFailSoft } from "../lib/auto-capture";
import type { AutoCaptureDeps } from "../lib/auto-capture";
import type { CapturedPlaylist } from "../../shared/api";

const ITEMS: CapturedPlaylist[] = [
  { title: "df365 | Deep Focus", url: "https://suno.com/playlist/u1" },
  { title: "df365 | Night Drive", url: "https://suno.com/playlist/u2" },
];

// 即時 resolve する sleep。deadline 進行は now を手動制御するため待たない。
const noSleep = () => Promise.resolve();

// 呼び出し回数に応じて時刻を進める now を作る（deadline ループの脱出を決定的にする）。
function steppingNow(steps: number[]): () => number {
  let i = 0;
  return () => steps[Math.min(i++, steps.length - 1)];
}

describe("captureFromTab: content script 応答までリトライする", () => {
  it("Given 最初の N 回 reject → その後 resolve When capture Then リトライ後に scrape 結果を返す", async () => {
    const sendCapture = vi
      .fn<(tabId: number) => Promise<CapturedPlaylist[]>>()
      .mockRejectedValueOnce(new Error("no content script"))
      .mockRejectedValueOnce(new Error("no content script"))
      .mockResolvedValueOnce(ITEMS);

    const result = await captureFromTab(99, {
      sendCapture,
      sleep: noSleep,
      // now はループ判定で複数回読まれる。deadline (0+1000) 未満を維持して 3 回目で resolve させる。
      now: () => 0,
      timeoutMs: 1000,
      pollMs: 10,
    });

    expect(result).toEqual(ITEMS);
    expect(sendCapture).toHaveBeenCalledTimes(3);
    expect(sendCapture).toHaveBeenLastCalledWith(99);
  });

  it("Given deadline 超過まで reject 継続 When capture Then 最後のエラーを throw する（fail-loud）", async () => {
    const sendCapture = vi
      .fn<(tabId: number) => Promise<CapturedPlaylist[]>>()
      .mockRejectedValue(new Error("timed out content"));

    await expect(
      captureFromTab(1, {
        sendCapture,
        sleep: noSleep,
        // now 呼び出し順: deadline 算出(0) → 1 回目 while 判定(0<100 true・試行) → sleep → 2 回目 while 判定(200>=100 脱出)。
        now: steppingNow([0, 0, 200]),
        timeoutMs: 100,
        pollMs: 10,
      }),
    ).rejects.toThrow("timed out content");
  });

  it("Given 開始時点で既に deadline When capture Then 1 度も送信せず timeout エラーを throw する", async () => {
    const sendCapture = vi.fn<(tabId: number) => Promise<CapturedPlaylist[]>>();

    await expect(
      captureFromTab(1, {
        sendCapture,
        sleep: noSleep,
        now: () => 1000, // now() >= now()+0 でループに入らない
        timeoutMs: 0,
        pollMs: 10,
      }),
    ).rejects.toThrow("capturePlaylists timed out");
    expect(sendCapture).not.toHaveBeenCalled();
  });
});

// AutoCaptureDeps の各メソッドを typed mock で構築する。各 fn は vi.fn のため
// toHaveBeenCalledWith / not.toHaveBeenCalled を呼べる（型は AutoCaptureDeps に一致）。
function makeDeps(overrides: Partial<AutoCaptureDeps> = {}): AutoCaptureDeps {
  return {
    getServerUrl: vi.fn<() => Promise<string>>(async () => "http://localhost:7873"),
    createMeTab: vi.fn<() => Promise<{ id?: number }>>(async () => ({ id: 7 })),
    removeTab: vi.fn<(tabId: number) => Promise<void>>(async () => undefined),
    capture: vi.fn<(tabId: number) => Promise<CapturedPlaylist[]>>(async () => ITEMS),
    post: vi.fn<(baseUrl: string, items: CapturedPlaylist[]) => Promise<unknown>>(async () => ({
      written: 2,
      path: "/p",
    })),
    ...overrides,
  };
}

describe("autoCapturePlaylists: 正常系 create→capture→POST→remove", () => {
  it("Given URL あり・capture 結果あり When 実行 Then tab を開き scrape→POST し finally で閉じる", async () => {
    const deps = makeDeps();

    await autoCapturePlaylists(deps);

    expect(deps.createMeTab).toHaveBeenCalledTimes(1);
    expect(deps.capture).toHaveBeenCalledWith(7);
    expect(deps.post).toHaveBeenCalledWith("http://localhost:7873", ITEMS);
    expect(deps.removeTab).toHaveBeenCalledWith(7);
  });

  it("Given サーバー URL が末尾空白付き When 実行 Then trim した baseUrl で POST する", async () => {
    const deps = makeDeps({ getServerUrl: vi.fn(async () => "  http://localhost:7873  ") });

    await autoCapturePlaylists(deps);

    expect(deps.post).toHaveBeenCalledWith("http://localhost:7873", ITEMS);
  });
});

describe("autoCapturePlaylists: fail-soft / 早期 return の分岐", () => {
  it("Given サーバー URL 未設定 When 実行 Then tab を開かず POST もしない（fail soft）", async () => {
    const deps = makeDeps({ getServerUrl: vi.fn(async () => "   ") });

    await autoCapturePlaylists(deps);

    expect(deps.createMeTab).not.toHaveBeenCalled();
    expect(deps.post).not.toHaveBeenCalled();
    expect(deps.removeTab).not.toHaveBeenCalled();
  });

  it("Given tab.id が取れない When 実行 Then capture/POST せず（閉じる対象も無い）", async () => {
    const deps = makeDeps({ createMeTab: vi.fn(async () => ({})) });

    await autoCapturePlaylists(deps);

    expect(deps.capture).not.toHaveBeenCalled();
    expect(deps.post).not.toHaveBeenCalled();
    expect(deps.removeTab).not.toHaveBeenCalled();
  });

  it("Given capture 結果が空 When 実行 Then POST せず tab は閉じる", async () => {
    const deps = makeDeps({ capture: vi.fn(async () => [] as CapturedPlaylist[]) });

    await autoCapturePlaylists(deps);

    expect(deps.post).not.toHaveBeenCalled();
    expect(deps.removeTab).toHaveBeenCalledWith(7);
  });

  it("Given capture が throw When 実行 Then POST せず finally で tab を閉じ、例外を伝播する", async () => {
    const deps = makeDeps({ capture: vi.fn(async () => Promise.reject(new Error("scrape failed"))) });

    await expect(autoCapturePlaylists(deps)).rejects.toThrow("scrape failed");
    expect(deps.post).not.toHaveBeenCalled();
    expect(deps.removeTab).toHaveBeenCalledWith(7);
  });

  it("Given POST が throw When 実行 Then finally で tab を閉じ、例外を伝播する", async () => {
    const deps = makeDeps({ post: vi.fn(async () => Promise.reject(new Error("HTTP 403"))) });

    await expect(autoCapturePlaylists(deps)).rejects.toThrow("HTTP 403");
    expect(deps.removeTab).toHaveBeenCalledWith(7);
  });
});

describe("triggerPlaylistCaptureFailSoft: content→background trigger は FINISHED を妨げない", () => {
  it("Given send 成功 When trigger Then onError を呼ばず正常に resolve する", async () => {
    const send = vi.fn(async () => undefined);
    const onError = vi.fn();

    await triggerPlaylistCaptureFailSoft(send, onError);

    expect(send).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
  });

  it("Given send が throw（background 不在等）When trigger Then 握って onError へ流し、reject しない（fail soft）", async () => {
    const err = new Error("no receiving end");
    const send = vi.fn(async () => Promise.reject(err));
    const onError = vi.fn();

    // reject せず resolve することで、呼び出し側の PHASE.FINISHED 進行が妨げられないことを担保する。
    await expect(triggerPlaylistCaptureFailSoft(send, onError)).resolves.toBeUndefined();
    expect(onError).toHaveBeenCalledWith(err);
  });
});
