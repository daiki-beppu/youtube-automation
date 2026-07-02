// content script SSOT スナップショット reducer (#852) の回帰テスト。
//
// popup を閉じても進捗を維持・復元するため、content script は現在の進捗を
// `SnapshotPayload` として保持し、popup の再 open 時に `queryProgress` で返す。
// その snapshot を組み立てる純関数 (`lib/snapshot.ts`) の契約を担保する:
//   - initSnapshot(entries, options): collectionId / 全 idle / isRunning=true / entries 保持で初期化
//   - nextItemStates(prev, phase, index): INJECTING / DONE のみ遷移、他 phase は prev 不変
//   - applyProgress(snap, payload): itemStates 遷移 + progress 更新。終了 phase で isRunning=false（snapshot は保持）
//
// itemStates の遷移ロジックは useSunoRunner.ts の live handler と同一であり、
// content (snapshot 構築) と popup (live 表示 / restore) で二重定義しないための SSOT。
import { describe, expect, it } from "vitest";

import { PHASE } from "../../shared/constants";
import { applyProgress, initSnapshot, nextItemStates } from "../lib/snapshot";
import { makePromptEntries, snapshotOptions, TEST_COLLECTION_ID } from "./_helpers";

describe("initSnapshot: 連続実行開始時の初期スナップショット", () => {
  it("Given 3 entries When initSnapshot Then itemStates は全 idle で entries 件数ぶん", () => {
    const snap = initSnapshot(makePromptEntries(3), snapshotOptions());

    expect(snap.itemStates).toEqual(["idle", "idle", "idle"]);
  });

  it("Given collectionId When initSnapshot Then collectionId を保持する", () => {
    const snap = initSnapshot(makePromptEntries(1), snapshotOptions());

    expect(snap.collectionId).toBe(TEST_COLLECTION_ID);
  });

  it("Given entries When initSnapshot Then entries をそのまま保持する", () => {
    const entries = makePromptEntries(2);
    const snap = initSnapshot(entries, snapshotOptions());

    expect(snap.entries).toEqual(entries);
  });

  it("Given entries When initSnapshot Then isRunning=true（実行中として開始）", () => {
    const snap = initSnapshot(makePromptEntries(2), snapshotOptions());

    expect(snap.isRunning).toBe(true);
  });

  it("Given 空 entries When initSnapshot Then itemStates も空（content が null から emit する初期化に対応）", () => {
    const snap = initSnapshot([], snapshotOptions());

    expect(snap.itemStates).toEqual([]);
    expect(snap.entries).toEqual([]);
  });
});

describe("nextItemStates: itemStates の遷移ロジック (useSunoRunner live handler と同一)", () => {
  const base = initSnapshot(makePromptEntries(3), snapshotOptions()).itemStates; // ["idle","idle","idle"]

  it("Given 全 idle When INJECTING index=0 Then index を active にする", () => {
    expect(nextItemStates(base, PHASE.INJECTING, 0)).toEqual(["active", "idle", "idle"]);
  });

  it("Given 直前 active が残る When 別 index を INJECTING Then 旧 active は idle へ戻す", () => {
    const prev = nextItemStates(base, PHASE.INJECTING, 0); // ["active","idle","idle"]

    expect(nextItemStates(prev, PHASE.INJECTING, 1)).toEqual(["idle", "active", "idle"]);
  });

  it("Given done を含む When 別 index を INJECTING Then done は維持し active のみ移す", () => {
    const done0 = nextItemStates(base, PHASE.DONE, 0); // ["done","idle","idle"]

    expect(nextItemStates(done0, PHASE.INJECTING, 1)).toEqual(["done", "active", "idle"]);
  });

  it("Given 全 idle When DONE index=0 Then index を done にする", () => {
    expect(nextItemStates(base, PHASE.DONE, 0)).toEqual(["done", "idle", "idle"]);
  });

  it.each([PHASE.WAITING_SLOT, PHASE.GENERATING, PHASE.ADDING_TO_PLAYLIST, PHASE.FINISHED, PHASE.STOPPED, PHASE.ERROR])(
    "Given prev When phase=%s Then itemStates は遷移させない（prev と等価）",
    (phase) => {
      const prev = nextItemStates(base, PHASE.INJECTING, 0); // ["active","idle","idle"]

      expect(nextItemStates(prev, phase, 0)).toEqual(prev);
    },
  );

  it("Given prev When nextItemStates Then 新しい配列を返す（React state 更新のため非破壊）", () => {
    const result = nextItemStates(base, PHASE.INJECTING, 0);

    expect(result).not.toBe(base);
    expect(base).toEqual(["idle", "idle", "idle"]); // 入力は不変
  });
});

describe("applyProgress: progress 受信でスナップショットを更新する", () => {
  it("Given 実行中 snap When INJECTING を適用 Then itemStates を遷移し progress を保持する", () => {
    const snap = initSnapshot(makePromptEntries(3), snapshotOptions());

    const next = applyProgress(snap, { phase: PHASE.INJECTING, index: 0, total: 3 });

    expect(next.itemStates).toEqual(["active", "idle", "idle"]);
    expect(next.progress).toEqual({ phase: PHASE.INJECTING, index: 0, total: 3 });
  });

  it("Given 実行中 snap When DONE を適用 Then itemStates を done にしつつ isRunning は true 維持（非終了 phase）", () => {
    const snap = initSnapshot(makePromptEntries(3), snapshotOptions());

    const next = applyProgress(snap, { phase: PHASE.DONE, index: 0, total: 3 });

    expect(next.itemStates).toEqual(["done", "idle", "idle"]);
    expect(next.isRunning).toBe(true);
  });

  it("Given 実行中 snap When duration-check NG の DONE を適用 Then itemStates を done 化しない", () => {
    const snap = applyProgress(initSnapshot(makePromptEntries(3), snapshotOptions()), {
      phase: PHASE.INJECTING,
      index: 0,
      total: 3,
    });

    const next = applyProgress(snap, {
      phase: PHASE.DONE,
      index: 0,
      total: 3,
      log: { kind: "duration-check", entryName: "pattern-1", durationSec: 312, ok: false, maxSec: 300 },
    });

    expect(next.itemStates).toEqual(["active", "idle", "idle"]);
    expect(next.isRunning).toBe(true);
  });

  it.each([PHASE.FINISHED, PHASE.STOPPED, PHASE.ERROR])(
    "Given 実行中 snap When 終了 phase=%s を適用 Then isRunning=false にする",
    (phase) => {
      const snap = initSnapshot(makePromptEntries(2), snapshotOptions());

      const next = applyProgress(snap, { phase, total: 2 });

      expect(next.isRunning).toBe(false);
    },
  );

  it("Given 実行中 snap When FINISHED を適用 Then entries / itemStates を破棄せず保持する（再 open 表示用）", () => {
    const entries = makePromptEntries(2);
    const running = applyProgress(initSnapshot(entries, snapshotOptions()), { phase: PHASE.DONE, index: 0, total: 2 });

    const finished = applyProgress(running, { phase: PHASE.FINISHED, total: 2 });

    expect(finished.entries).toEqual(entries);
    expect(finished.itemStates).toEqual(["done", "idle"]);
    expect(finished.isRunning).toBe(false);
  });

  it("Given snap When ERROR を message 付きで適用 Then progress.message を保持する", () => {
    const snap = initSnapshot(makePromptEntries(2), snapshotOptions());

    const next = applyProgress(snap, { phase: PHASE.ERROR, index: 1, total: 2, message: "boom" });

    expect(next.progress.message).toBe("boom");
    expect(next.isRunning).toBe(false);
  });
});
