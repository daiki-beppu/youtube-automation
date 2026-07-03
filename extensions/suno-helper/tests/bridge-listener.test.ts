// @vitest-environment jsdom
//
// ISOLATED 側 bridge 受信配線 (#948) の回帰テスト。
//   - source マーカー / event.source の検証で他者の message を弾く
//   - GENERATE_CLIPS → registerSubmitted / FEED_CLIPS・FEED_POLL_RESPONSE → applyFeedStatuses
//   - feed poller は「未終端 clip あり かつ passive 観測が stale」のときだけ poll を発行する
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BRIDGE_MSG, BRIDGE_SOURCE } from "../../shared/constants";
import { attachBridgeListener, createFeedPoller, requestFeedPoll, requestSliderSet } from "../lib/bridge-listener";
import { createClipTracker } from "../lib/clip-tracker";

/** bridge からの postMessage を模した MessageEvent を同期 dispatch する。 */
function dispatchBridgeMessage(data: unknown, source: Window | null = window): void {
  window.dispatchEvent(new MessageEvent("message", { data, source: source as WindowProxy | null }));
}

describe("attachBridgeListener: 観測イベントの tracker 配線", () => {
  it("Given GENERATE_CLIPS message When 受信する Then registerSubmitted される", () => {
    const tracker = createClipTracker();
    const detach = attachBridgeListener(tracker);

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.GENERATE_CLIPS,
      clips: [
        { id: "c1", status: "submitted", duration: 241.2 },
        { id: "c2", status: "submitted" },
      ],
    });

    expect(tracker.submissionCount()).toBe(1);
    expect(tracker.getInFlightCount()).toBe(2);
    expect(tracker.getSubmittedIds()).toEqual(["c1", "c2"]);
    detach();
  });

  it("Given feed に未知 clip が混ざる When 受信する Then playlist 候補 ID は generate 観測分だけを保持する", () => {
    const tracker = createClipTracker();
    const detach = attachBridgeListener(tracker);

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.GENERATE_CLIPS,
      clips: [{ id: "fresh", status: "submitted" }],
    });
    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.FEED_CLIPS,
      clips: [{ id: "leftover", status: "streaming" }],
    });

    expect(tracker.getPendingIds()).toEqual(["fresh", "leftover"]);
    expect(tracker.getSubmittedIds()).toEqual(["fresh"]);
    detach();
  });

  it("Given FEED_CLIPS / FEED_POLL_RESPONSE message When 受信する Then applyFeedStatuses される", () => {
    const tracker = createClipTracker();
    const applyFeedStatuses = vi.spyOn(tracker, "applyFeedStatuses");
    const detach = attachBridgeListener(tracker);
    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.GENERATE_CLIPS,
      clips: [{ id: "c1", status: "submitted" }],
    });

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.FEED_CLIPS,
      clips: [{ id: "c1", status: "streaming", duration: 187.25 }],
    });
    expect(applyFeedStatuses).toHaveBeenLastCalledWith([{ id: "c1", status: "streaming", duration: 187.25 }]);
    expect(tracker.getInFlightCount()).toBe(1);

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.FEED_POLL_RESPONSE,
      requestId: 1,
      clips: [{ id: "c1", status: "complete", duration: 187.25 }],
    });
    expect(applyFeedStatuses).toHaveBeenLastCalledWith([{ id: "c1", status: "complete", duration: 187.25 }]);
    expect(tracker.getInFlightCount()).toBe(0); // active poll の応答も観測として合流する
    detach();
  });

  it("Given source マーカー不一致 / event.source 非 window / 形崩れ clips When 受信する Then 無視する", () => {
    const tracker = createClipTracker();
    const detach = attachBridgeListener(tracker);

    // source マーカー不一致（ページ本体や他拡張の message）
    dispatchBridgeMessage({ source: "other", type: BRIDGE_MSG.GENERATE_CLIPS, clips: [{ id: "x", status: "s" }] });
    // event.source が window でない（cross-window message）
    dispatchBridgeMessage(
      { source: BRIDGE_SOURCE, type: BRIDGE_MSG.GENERATE_CLIPS, clips: [{ id: "x", status: "s" }] },
      null,
    );
    // clips の形崩れ
    dispatchBridgeMessage({ source: BRIDGE_SOURCE, type: BRIDGE_MSG.GENERATE_CLIPS, clips: [{ id: 1 }] });
    dispatchBridgeMessage({ source: BRIDGE_SOURCE, type: BRIDGE_MSG.GENERATE_CLIPS });
    // duration は optional だが、存在する場合は finite number のみ受け入れる
    for (const duration of ["241.2", Number.NaN, Infinity]) {
      dispatchBridgeMessage({
        source: BRIDGE_SOURCE,
        type: BRIDGE_MSG.GENERATE_CLIPS,
        clips: [{ id: "x", status: "submitted", duration }],
      });
    }

    expect(tracker.hasObservedAnyTraffic()).toBe(false);
    expect(tracker.getInFlightCount()).toBe(0);
    detach();
  });

  it("Given detach 済み When message を受信する Then tracker は更新されない", () => {
    const tracker = createClipTracker();
    const detach = attachBridgeListener(tracker);
    detach();

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.GENERATE_CLIPS,
      clips: [{ id: "c1", status: "submitted" }],
    });
    expect(tracker.hasObservedAnyTraffic()).toBe(false);
  });
});

describe("requestFeedPoll: active poll 応答の ObservedClip 境界検証", () => {
  async function captureFeedPollRequestId(): Promise<number> {
    return new Promise<number>((resolve) => {
      const probe = (event: MessageEvent): void => {
        const data = event.data as { requestId?: number; type?: string };
        if (data?.type === BRIDGE_MSG.FEED_POLL_REQUEST && typeof data.requestId === "number") {
          window.removeEventListener("message", probe);
          resolve(data.requestId);
        }
      };
      window.addEventListener("message", probe);
    });
  }

  it("Given duration あり / なしの poll 応答 When 受信する Then ObservedClip[] として resolve する", async () => {
    const pending = requestFeedPoll(["c1", "c2"]);
    const requestId = await captureFeedPollRequestId();

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.FEED_POLL_RESPONSE,
      requestId,
      clips: [
        { id: "c1", status: "streaming", duration: 241.2 },
        { id: "c2", status: "complete" },
      ],
    });

    await expect(pending).resolves.toEqual([
      { id: "c1", status: "streaming", duration: 241.2 },
      { id: "c2", status: "complete" },
    ]);
  });

  it.each([
    ["string", "241.2"],
    ["NaN", Number.NaN],
    ["Infinity", Infinity],
  ])("Given duration が %s の poll 応答 When 受信する Then null で resolve する", async (_label, duration) => {
    const pending = requestFeedPoll(["c1"]);
    const requestId = await captureFeedPollRequestId();

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.FEED_POLL_RESPONSE,
      requestId,
      clips: [{ id: "c1", status: "streaming", duration }],
    });

    await expect(pending).resolves.toBeNull();
  });
});

describe("createFeedPoller: stale 時のみ active poll", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given 未終端 clip あり + passive 観測なし（stale） When tick する Then pending ids で poll を発行する", async () => {
    const tracker = createClipTracker(() => 0); // lastFeedAt = 0 のまま（観測なし = stale）
    tracker.registerSubmitted([{ id: "c1", status: "submitted" }]);
    const poll = vi.fn().mockResolvedValue(null);
    const poller = createFeedPoller(tracker, { intervalMs: 100, staleMs: 50, now: () => 1000, poll });

    poller.start();
    await vi.advanceTimersByTimeAsync(100);

    expect(poll).toHaveBeenCalledWith(["c1"]);
    poller.stop();
  });

  it("Given 未終端 clip なし When tick する Then poll しない", async () => {
    const tracker = createClipTracker();
    const poll = vi.fn().mockResolvedValue(null);
    const poller = createFeedPoller(tracker, { intervalMs: 100, staleMs: 50, now: () => 1000, poll });

    poller.start();
    await vi.advanceTimersByTimeAsync(300);

    expect(poll).not.toHaveBeenCalled();
    poller.stop();
  });

  it("Given passive 観測が新鮮（stale 未満） When tick する Then poll しない（bot シグナル最小化）", async () => {
    let t = 0;
    const tracker = createClipTracker(() => t);
    tracker.registerSubmitted([{ id: "c1", status: "submitted" }]);
    t = 990;
    tracker.applyFeedStatuses([{ id: "c1", status: "streaming" }]); // lastFeedAt = 990
    const poll = vi.fn().mockResolvedValue(null);
    const poller = createFeedPoller(tracker, { intervalMs: 100, staleMs: 50, now: () => 1000, poll });

    poller.start();
    await vi.advanceTimersByTimeAsync(100); // now=1000, lastFeedAt=990 → 経過 10 < staleMs 50

    expect(poll).not.toHaveBeenCalled();
    poller.stop();
  });

  it("Given stop 済み When 時間が進む Then poll しない", async () => {
    const tracker = createClipTracker(() => 0);
    tracker.registerSubmitted([{ id: "c1", status: "submitted" }]);
    const poll = vi.fn().mockResolvedValue(null);
    const poller = createFeedPoller(tracker, { intervalMs: 100, staleMs: 50, now: () => 1000, poll });

    poller.start();
    poller.stop();
    await vi.advanceTimersByTimeAsync(500);

    expect(poll).not.toHaveBeenCalled();
  });

  it("Given poll 応答が遅い When 次 tick が来る Then 二重発行しない", async () => {
    const tracker = createClipTracker(() => 0);
    tracker.registerSubmitted([{ id: "c1", status: "submitted" }]);
    let resolvePoll: (() => void) | undefined;
    const poll = vi.fn().mockImplementation(
      () =>
        new Promise<null>((resolve) => {
          resolvePoll = () => resolve(null);
        }),
    );
    const poller = createFeedPoller(tracker, { intervalMs: 100, staleMs: 50, now: () => 1000, poll });

    poller.start();
    await vi.advanceTimersByTimeAsync(350); // 3 tick 分進めても応答待ちの間は 1 回だけ

    expect(poll).toHaveBeenCalledTimes(1);
    resolvePoll?.();
    poller.stop();
  });
});

describe("requestSliderSet: slider 注入 RPC の応答処理 (#973)", () => {
  it("Given ok:true の応答 When 受信する Then true で resolve する", async () => {
    const pending = requestSliderSet("Style Influence", 95);
    // requestId は module 内 counter のため、応答側は postMessage された request を読んで合わせる
    const requestId = await new Promise<number>((resolve) => {
      const probe = (event: MessageEvent): void => {
        const data = event.data as { type?: string; requestId?: number };
        if (data?.type === BRIDGE_MSG.SLIDER_SET_REQUEST && typeof data.requestId === "number") {
          window.removeEventListener("message", probe);
          resolve(data.requestId);
        }
      };
      window.addEventListener("message", probe);
    });

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.SLIDER_SET_RESPONSE,
      requestId,
      ok: true,
      actual: 95,
    });
    await expect(pending).resolves.toBe(true);
  });

  it("Given ok:false の応答 When 受信する Then false で resolve する（合成イベント経路へ縮退）", async () => {
    const pending = requestSliderSet("Weirdness", 30);
    const requestId = await new Promise<number>((resolve) => {
      const probe = (event: MessageEvent): void => {
        const data = event.data as { type?: string; requestId?: number };
        if (data?.type === BRIDGE_MSG.SLIDER_SET_REQUEST && typeof data.requestId === "number") {
          window.removeEventListener("message", probe);
          resolve(data.requestId);
        }
      };
      window.addEventListener("message", probe);
    });

    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.SLIDER_SET_RESPONSE,
      requestId,
      ok: false,
      actual: null,
    });
    await expect(pending).resolves.toBe(false);
  });

  it("Given 応答が来ない（bridge 不在） When timeout する Then false で resolve する", async () => {
    await expect(requestSliderSet("Weirdness", 30, 50)).resolves.toBe(false);
  });

  it("Given requestId 不一致の応答 When 受信する Then 無視して timeout で false", async () => {
    const pending = requestSliderSet("Weirdness", 30, 100);
    dispatchBridgeMessage({
      source: BRIDGE_SOURCE,
      type: BRIDGE_MSG.SLIDER_SET_RESPONSE,
      requestId: -1,
      ok: true,
      actual: 30,
    });
    await expect(pending).resolves.toBe(false);
  });
});
