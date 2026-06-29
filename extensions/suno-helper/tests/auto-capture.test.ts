// playlist URL 解決用 bg tab scrape orchestration の回帰テスト。
//
// background.ts は wxt globals を伴い node 環境から import 不可のため、orchestration を lib/auto-capture へ
// 切り出し（overlay-relay と同方針）、副作用を引数注入にして純ロジックを検証する。
import { describe, expect, it, vi } from "vitest";

import { captureFromTab } from "../lib/auto-capture";
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

  it("Given 最初の N 回 [] → その後 非空 resolve When capture Then SPA 描画待ちリトライ後に scrape 結果を返す", async () => {
    const sendCapture = vi
      .fn<(tabId: number) => Promise<CapturedPlaylist[]>>()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce(ITEMS);

    const result = await captureFromTab(99, {
      sendCapture,
      sleep: noSleep,
      now: () => 0,
      timeoutMs: 1000,
      pollMs: 10,
    });

    expect(result).toEqual(ITEMS);
    expect(sendCapture).toHaveBeenCalledTimes(3);
  });

  it("Given reject → [] → reject → 非空 resolve When capture Then 混在リトライ後に結果を返す", async () => {
    const sendCapture = vi
      .fn<(tabId: number) => Promise<CapturedPlaylist[]>>()
      .mockRejectedValueOnce(new Error("no content script"))
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new Error("no content script"))
      .mockResolvedValueOnce(ITEMS);

    const result = await captureFromTab(99, {
      sendCapture,
      sleep: noSleep,
      now: () => 0,
      timeoutMs: 1000,
      pollMs: 10,
    });

    expect(result).toEqual(ITEMS);
    expect(sendCapture).toHaveBeenCalledTimes(4);
  });

  it("Given deadline 超過まで [] 継続 When capture Then 空配列を返す（fail-soft、throw しない）", async () => {
    const sendCapture = vi.fn<(tabId: number) => Promise<CapturedPlaylist[]>>().mockResolvedValue([]);

    const result = await captureFromTab(1, {
      sendCapture,
      sleep: noSleep,
      now: steppingNow([0, 0, 200]),
      timeoutMs: 100,
      pollMs: 10,
    });

    expect(result).toEqual([]);
  });

  it("Given reject と [] が混在して deadline 超過 When capture Then 空応答があったため [] を返す（throw しない）", async () => {
    const sendCapture = vi
      .fn<(tabId: number) => Promise<CapturedPlaylist[]>>()
      .mockRejectedValueOnce(new Error("no content script"))
      .mockResolvedValueOnce([]);

    const result = await captureFromTab(1, {
      sendCapture,
      sleep: noSleep,
      now: steppingNow([0, 0, 0, 200]),
      timeoutMs: 100,
      pollMs: 10,
    });

    expect(result).toEqual([]);
  });
});
