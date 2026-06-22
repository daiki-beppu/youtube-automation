// clip-tracker (#948) の回帰テスト。
//
// in-flight の SSOT。「Remix disabled」DOM プロキシ（生成完了後も disabled が残り
// 過大カウント、実測 20 中 16 誤判定）を置き換える status ベース集計の契約を pin する。
import { describe, expect, it } from "vitest";

import { createClipTracker } from "../lib/clip-tracker";

describe("createClipTracker: status ベースの in-flight 集計", () => {
  it("Given 観測ゼロ When 読む Then in-flight 0 / traffic 未観測 / submission 0", () => {
    const tracker = createClipTracker();
    expect(tracker.getInFlightCount()).toBe(0);
    expect(tracker.hasObservedAnyTraffic()).toBe(false);
    expect(tracker.submissionCount()).toBe(0);
    expect(tracker.getPendingIds()).toEqual([]);
    expect(tracker.getSubmittedIds()).toEqual([]);
  });

  it("Given generate 観測（2 clip submitted） When 読む Then in-flight 2 / submission 1", () => {
    const tracker = createClipTracker();
    tracker.registerSubmitted([
      { id: "c1", status: "submitted" },
      { id: "c2", status: "submitted" },
    ]);
    expect(tracker.getInFlightCount()).toBe(2);
    expect(tracker.submissionCount()).toBe(1);
    expect(tracker.hasObservedAnyTraffic()).toBe(true);
    expect(tracker.getPendingIds()).toEqual(["c1", "c2"]);
  });

  it("Given feed 観測で complete へ遷移 When 読む Then in-flight から外れる（バグ本体の修正点）", () => {
    // DOM プロキシは complete 後も「生成中」に数え続けるのが #948 のバグ本体。
    // status ベースでは complete/error が即座に slot を解放する。
    const tracker = createClipTracker();
    tracker.registerSubmitted([
      { id: "c1", status: "submitted" },
      { id: "c2", status: "submitted" },
    ]);
    tracker.applyFeedStatuses([
      { id: "c1", status: "streaming" },
      { id: "c2", status: "complete" },
    ]);
    expect(tracker.getInFlightCount()).toBe(1);
    expect(tracker.getPendingIds()).toEqual(["c1"]);

    tracker.applyFeedStatuses([{ id: "c1", status: "error" }]);
    expect(tracker.getInFlightCount()).toBe(0);
  });

  it("Given feed 観測に未知の未終端 clip When 読む Then passive 合流で数える（前 run の残留分）", () => {
    const tracker = createClipTracker();
    tracker.applyFeedStatuses([
      { id: "leftover", status: "streaming" }, // 前 run / 手動投入の残留 in-flight
      { id: "done", status: "complete" }, // 終端済みの未知 clip は合流させない
    ]);
    expect(tracker.getInFlightCount()).toBe(1);
    expect(tracker.getPendingIds()).toEqual(["leftover"]);
    expect(tracker.hasObservedAnyTraffic()).toBe(true);
  });

  it("Given 既知 clip の終端後 feed 観測 When status が再掲される Then 二重登録せず status を維持する", () => {
    const tracker = createClipTracker();
    tracker.registerSubmitted([{ id: "c1", status: "submitted" }]);
    tracker.applyFeedStatuses([{ id: "c1", status: "complete" }]);
    tracker.applyFeedStatuses([{ id: "c1", status: "complete" }]); // 既知の終端 clip の再掲
    expect(tracker.getInFlightCount()).toBe(0);
    expect(tracker.getPendingIds()).toEqual([]);
  });

  it("Given submission ごとに registerSubmitted When 数える Then submissionCount が単調増加（ACK marker 契約）", () => {
    const tracker = createClipTracker();
    expect(tracker.submissionCount()).toBe(0);
    tracker.registerSubmitted([{ id: "c1", status: "submitted" }]);
    tracker.registerSubmitted([{ id: "c2", status: "submitted" }]);
    expect(tracker.submissionCount()).toBe(2);
  });

  it("Given now を注入 When 観測する Then lastFeedAt / lastChangeAt が観測時刻を反映する", () => {
    let t = 1000;
    const tracker = createClipTracker(() => t);
    expect(tracker.lastFeedAt()).toBe(0);
    expect(tracker.lastChangeAt()).toBe(0);

    tracker.registerSubmitted([{ id: "c1", status: "submitted" }]);
    expect(tracker.lastChangeAt()).toBe(1000);
    expect(tracker.lastFeedAt()).toBe(0); // generate 観測は feed 時刻を進めない

    t = 2000;
    tracker.applyFeedStatuses([{ id: "c1", status: "streaming" }]);
    expect(tracker.lastFeedAt()).toBe(2000);
    expect(tracker.lastChangeAt()).toBe(2000);

    t = 3000;
    tracker.applyFeedStatuses([{ id: "c1", status: "streaming" }]); // status 変化なし
    expect(tracker.lastFeedAt()).toBe(3000); // feed 観測時刻は進む
    expect(tracker.lastChangeAt()).toBe(2000); // 集合は不変なので change は進まない（stall 判定用）
  });
});

describe("createClipTracker: playlist 対象 submitted ID 管理", () => {
  it("Given generate 観測が複数回ある When 読む Then submitted ID を初回観測順で重複なく返す", () => {
    const tracker = createClipTracker();

    tracker.registerSubmitted([
      { id: "fresh-a", status: "submitted" },
      { id: "fresh-b", status: "submitted" },
    ]);
    tracker.registerSubmitted([
      { id: "fresh-b", status: "queued" },
      { id: "fresh-c", status: "submitted" },
    ]);

    expect(tracker.getSubmittedIds()).toEqual(["fresh-a", "fresh-b", "fresh-c"]);
  });

  it("Given feed の passive unknown clip When 読む Then submitted ID には含めない", () => {
    const tracker = createClipTracker();

    tracker.registerSubmitted([{ id: "fresh-a", status: "submitted" }]);
    tracker.applyFeedStatuses([{ id: "leftover", status: "streaming" }]);

    expect(tracker.getPendingIds()).toEqual(["fresh-a", "leftover"]);
    expect(tracker.getSubmittedIds()).toEqual(["fresh-a"]);
  });

  it("Given submitted clip が terminal status へ遷移 When 読む Then playlist 対象 ID として保持する", () => {
    const tracker = createClipTracker();

    tracker.registerSubmitted([{ id: "fresh-a", status: "submitted" }]);
    tracker.applyFeedStatuses([{ id: "fresh-a", status: "complete" }]);

    expect(tracker.getInFlightCount()).toBe(0);
    expect(tracker.getSubmittedIds()).toEqual(["fresh-a"]);
  });

  it("Given clearSubmittedIds When 実行 Then playlist 対象だけを消し in-flight status は保持する", () => {
    const tracker = createClipTracker();

    tracker.registerSubmitted([{ id: "fresh-a", status: "submitted" }]);
    tracker.clearSubmittedIds();

    expect(tracker.getSubmittedIds()).toEqual([]);
    expect(tracker.getPendingIds()).toEqual(["fresh-a"]);
    expect(tracker.getInFlightCount()).toBe(1);
    expect(tracker.submissionCount()).toBe(1);
    expect(tracker.hasObservedAnyTraffic()).toBe(true);
  });
});
